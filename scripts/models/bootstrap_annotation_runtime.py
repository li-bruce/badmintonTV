"""One-shot, bounded CPU contract overlay; never modify the parent environment.

Plan:   /mnt/d/video/runtime/models/env/bin/python -s -B this_script.py
Apply:  /mnt/d/video/runtime/models/env/bin/python -s -B this_script.py --execute

Run only while the models owner holds the runtime writer slot. The existing
preflight checks runtime quotas, not the global 700 GB ledger or concurrency.
Existing target/dependency directories are refused, including failed attempts;
failure evidence is retained for explicit review, never deleted or overwritten.
Only official PyPI JSON and four wheels are fetched. No model/CUDA import.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile
from email.parser import BytesParser


PARENT = Path('/mnt/d/video/runtime/models/env')
PYTHON = PARENT / 'bin/python'
TARGET = PARENT.parent / 'annotation-env'
DEPS = PARENT.parent / 'annotation-deps-v1'
REPO = Path(__file__).resolve().parents[2]
PREFLIGHT = REPO / 'scripts/models/runtime_preflight_reuse.py'
REQUIREMENTS = REPO / 'environments/models-annotation-requirements.txt'
PINS = {'pydantic': '2.13.5', 'pydantic-core': '2.46.5',
        'annotated-types': '0.8.0', 'typing-inspection': '0.4.4'}
INHERITED = {'av': '15.0.0', 'numpy': '2.4.6', 'torch': '2.7.1',
             'typing-extensions': '4.16.0'}
METADATA_LIMIT = 1_000_000
WHEEL_LIMIT = 20_000_000
DOWNLOAD_LIMIT = 30_000_000
PEAK_LIMIT = 100_000_000
VENV_RESERVE = 40_000_000
OTHER_RESERVE = 8_000_000
CHUNK = 64 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def checked_url(url: str, host: str) -> str:
    value = urlparse(url)
    if (value.scheme != 'https' or value.hostname != host or value.port not in (None, 443)
            or value.username or value.password or value.fragment or value.query):
        raise ValueError('unexpected official-source URL')
    return url


class OfficialRedirect(HTTPRedirectHandler):
    def __init__(self, host: str):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl, self.host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def response_for(url: str, host: str):
    checked_url(url, host)
    opener = build_opener(OfficialRedirect(host))
    response = opener.open(Request(url, headers={
        'User-Agent': 'badmintonTV-annotation-bootstrap/1.0',
        'Accept-Encoding': 'identity',
    }), timeout=30)
    try:
        checked_url(response.url, host)
        if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
            raise ValueError('unexpected HTTP status or compressed transfer')
        return response
    except Exception:
        response.close()
        raise


def content_length(response):
    text = response.headers.get('Content-Length')
    if text is None:
        return None
    if not text.isdigit():
        raise ValueError('invalid Content-Length')
    return int(text)


def fetch_metadata(name: str, version: str, destination: Path):
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    with response_for(url, 'pypi.org') as response:
        declared = content_length(response)
        if declared is not None and not 0 < declared <= METADATA_LIMIT:
            raise ValueError('PyPI metadata exceeds 1 MB')
        data = bytearray()
        while len(data) < METADATA_LIMIT:
            chunk = response.read(min(CHUNK, METADATA_LIMIT - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if declared is not None and len(data) != declared:
            raise ValueError('PyPI metadata Content-Length mismatch')
        if len(data) == METADATA_LIMIT and declared is None:
            raise ValueError('cannot prove metadata ends within 1 MB')
    document = json.loads(data)
    if canonical(document['info']['name']) != name or document['info']['version'] != version:
        raise ValueError('PyPI metadata identity mismatch')
    with destination.open('xb') as handle:
        handle.write(data)
    return document, {'source_url': url, 'relative_path': destination.name,
                      'size_bytes': len(data), 'sha256': sha256(data)}


def select_wheel(name: str, version: str, document: dict):
    stem = name.replace('-', '_') + '-' + version
    suffix = ('-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl'
              if name == 'pydantic-core' else '-py3-none-any.whl')
    filename = stem + suffix
    matches = [item for item in document['urls'] if item.get('filename') == filename
               and item.get('packagetype') == 'bdist_wheel' and not item.get('yanked')]
    if len(matches) != 1:
        raise ValueError(f'exact supported non-yanked wheel unavailable: {filename}')
    item = matches[0]
    size = item.get('size')
    digest = item.get('digests', {}).get('sha256', '')
    if type(size) is not int or not 0 < size <= WHEEL_LIMIT:
        raise ValueError('wheel declared size exceeds 20 MB')
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('missing official wheel SHA256')
    url = checked_url(item['url'], 'files.pythonhosted.org')
    if PurePosixPath(unquote(urlparse(url).path)).name != filename:
        raise ValueError('wheel URL basename differs from metadata')
    return {'name': name, 'version': version, 'filename': filename,
            'source_url': url, 'sha256': digest, 'size_bytes': size}


def download_wheel(item: dict, network: dict):
    path = DEPS / item['filename']
    received = 0
    digest = hashlib.sha256()
    deadline = time.monotonic() + 180
    # Exclusive creation leaves partial bytes on failure, never overwrites them.
    with path.open('xb') as output, response_for(item['source_url'], 'files.pythonhosted.org') as response:
        declared = content_length(response)
        if declared is not None and declared != item['size_bytes']:
            raise ValueError('wheel HTTP size differs from official metadata')
        while received < item['size_bytes']:
            allowance = min(CHUNK, item['size_bytes'] - received,
                            WHEEL_LIMIT - received, DOWNLOAD_LIMIT - network['wheel_bytes'])
            if allowance <= 0 or time.monotonic() > deadline:
                raise ValueError('wheel network byte/time budget exceeded')
            chunk = response.read(allowance)
            if not chunk:
                break
            received += len(chunk)
            network['wheel_bytes'] += len(chunk)
            digest.update(chunk)
            output.write(chunk)
        # A known Content-Length bounds the HTTP body. Without it, inspect EOF
        # only if the sentinel itself remains inside both actual byte budgets.
        if declared is None and received == item['size_bytes']:
            if received >= WHEEL_LIMIT or network['wheel_bytes'] >= DOWNLOAD_LIMIT:
                raise ValueError('cannot verify unframed wheel EOF within byte budget')
            extra = response.read(1)
            network['wheel_bytes'] += len(extra)
            if extra:
                raise ValueError('wheel body exceeds official declared size')
    if received != item['size_bytes'] or digest.hexdigest() != item['sha256']:
        raise ValueError('wheel size/SHA256 verification failed')
    return path


def inspect_wheel(path: Path, item: dict):
    # No extraction here. Bound all declared expansion before pip creates files.
    with zipfile.ZipFile(path) as wheel:
        members = wheel.infolist()
        if len(members) > 10_000:
            raise ValueError('too many wheel members')
        seen = set()
        expanded = 0
        metadata_member = None
        for member in members:
            name = member.filename
            parts = name.rstrip('/').split('/')
            mode = member.external_attr >> 16
            if (not name or '\\' in name or name.startswith('/') or ':' in name
                    or any(part in ('..', '.', '') for part in parts) or name in seen
                    or stat.S_ISLNK(mode) or member.flag_bits & 1):
                raise ValueError('unsafe, duplicate or encrypted wheel member')
            seen.add(name)
            expanded += member.file_size
            if expanded > PEAK_LIMIT:
                raise ValueError('wheel expansion alone exceeds reserved peak')
            if name.endswith('.dist-info/METADATA'):
                if metadata_member is not None or member.file_size > 256_000:
                    raise ValueError('invalid wheel METADATA')
                metadata_member = member
        if metadata_member is None:
            raise ValueError('missing wheel METADATA')
        info = BytesParser().parsebytes(wheel.read(metadata_member))
        if canonical(info['Name']) != item['name'] or info['Version'] != item['version']:
            raise ValueError('wheel internal package identity mismatch')
        return expanded, info.get_all('Requires-Dist', []), info.get('Requires-Python')


def clean_environment():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('PYTHON', 'PIP_')) and key not in ('VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT')}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
               PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX='1', PIP_NO_CACHE_DIR='1',
               PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_REQUIRE_VIRTUALENV='1',
               TMPDIR=str(DEPS / 'tmp'), TEMP=str(DEPS / 'tmp'), TMP=str(DEPS / 'tmp'),
               XDG_CACHE_HOME=str(DEPS / 'cache'), CUDA_VISIBLE_DEVICES='')
    return env


def command(argv, report: dict, *, timeout=180):
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                            check=False, timeout=timeout, env=clean_environment())
    report['commands'].append({'argv': [str(a) for a in argv], 'returncode': result.returncode,
                               'stdout_tail': result.stdout[-12_000:], 'stderr_tail': result.stderr[-8_000:]})
    if result.returncode:
        raise RuntimeError(f'command failed with exit {result.returncode}: {argv[0]}')
    return result.stdout


def installed(names):
    result = {}
    for name in names:
        dist = metadata.distribution(name)
        result[name] = {'version': dist.version,
                        'location': str(Path(dist.locate_file('')).resolve())}
    return result


def verify_host():
    if sys.platform != 'linux' or platform.machine() != 'x86_64' or sys.version_info[:2] != (3, 11):
        raise ValueError('requires Linux x86_64 CPython 3.11 parent interpreter')
    if platform.python_implementation() != 'CPython':
        raise ValueError('CPython required')
    if Path(sys.prefix).resolve() != PARENT.resolve() or Path(sys.base_prefix).resolve() != PARENT.resolve():
        raise ValueError('run directly from the isolated parent Conda environment, not a nested venv')
    libc, version = platform.libc_ver()
    if libc != 'glibc' or tuple(map(int, version.split('.')[:2])) < (2, 17):
        raise ValueError('manylinux2014 wheel requires glibc >= 2.17')
    if not sys.flags.no_user_site or os.environ.get('PYTHONPATH'):
        raise ValueError('invoke with -s and cleared PYTHONPATH')
    if not sys.dont_write_bytecode:
        raise ValueError('invoke with -B / PYTHONDONTWRITEBYTECODE=1')
    if PARENT.parent.resolve() != Path('/mnt/d/video/runtime/models'):
        raise ValueError('runtime root must not redirect outside the approved directory')
    for path in (TARGET, DEPS):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'refusing existing target: {path}')
    lines = [line.strip() for line in REQUIREMENTS.read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if lines != [f'{name}=={version}' for name, version in PINS.items()]:
        raise ValueError('requirements differ from the four allowed pins')
    parent = installed(INHERITED)
    for name, expected in INHERITED.items():
        found = parent[name]
        if found['version'].split('+', 1)[0] != expected or not Path(found['location']).is_relative_to(PARENT.resolve()):
            raise ValueError(f'parent package version/origin mismatch: {name}')
    return parent


def check_requirements(rows):
    # pip is already present in the parent; its vendored parser adds no dependency.
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.specifiers import SpecifierSet
    checked = []
    for package, requirements, python_spec in rows:
        if python_spec and platform.python_version() not in SpecifierSet(python_spec):
            raise ValueError(f'wheel Python requirement not satisfied: {package}')
        for text in requirements:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
                continue
            name = canonical(requirement.name)
            version = PINS.get(name) or metadata.version(name)
            if requirement.url or requirement.extras or version not in requirement.specifier:
                raise ValueError(f'unsatisfied wheel dependency: {package}: {text}')
            checked.append({'package': package, 'requires_dist': text, 'resolved_version': version})
    return checked


def own_usage():
    total = 0
    for root in (DEPS, TARGET):
        if not root.exists():
            continue
        for directory, folders, files in os.walk(root, followlinks=False):
            total += Path(directory).lstat().st_size
            for name in files:
                total += (Path(directory) / name).lstat().st_size
            for name in folders:
                path = Path(directory) / name
                if path.is_symlink():
                    total += path.lstat().st_size
    if total > PEAK_LIMIT:
        raise ValueError('actual new directory usage exceeds 100 MB reservation')
    return total


PROBE = r'''
import importlib.metadata as m, json, pathlib, sys
names = ['pydantic','pydantic-core','annotated-types','typing-inspection',
         'av','numpy','torch','typing-extensions']
packages = {}
for name in names:
    d = m.distribution(name)
    packages[name] = {'version': d.version, 'location': str(pathlib.Path(d.locate_file('')).resolve())}
out = {'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'packages': packages,
       'user_site_disabled': bool(sys.flags.no_user_site), 'torch_imported': 'torch' in sys.modules}
if '--imports' in sys.argv:
    import pydantic, av
    class ContractProbe(pydantic.BaseModel):
        value: int
    assert ContractProbe.model_validate({'value': '7'}).value == 7
    out['imports'] = {'pydantic': {'version': pydantic.__version__, 'file': pydantic.__file__},
                      'av': {'version': av.__version__, 'file': av.__file__}}
    out['torch_imported'] = 'torch' in sys.modules
    assert not out['torch_imported']
print(json.dumps(out))
'''


def verify_child(probe, parent):
    if Path(probe['prefix']).resolve() != TARGET.resolve() or Path(probe['base_prefix']).resolve() != PARENT.resolve():
        raise ValueError('child prefix/base_prefix mismatch')
    if not probe['user_site_disabled'] or probe['torch_imported']:
        raise ValueError('unexpected child user-site or torch import')
    for name in INHERITED:
        if probe['packages'][name] != parent[name]:
            raise ValueError(f'inherited package changed origin/version: {name}')
    for name, version in PINS.items():
        found = probe['packages'][name]
        if found['version'] != version or not Path(found['location']).is_relative_to(TARGET.resolve()):
            raise ValueError(f'new package not installed in overlay: {name}')
    for name, expected, prefix in [('pydantic', PINS['pydantic'], TARGET),
                                    ('av', INHERITED['av'], PARENT)]:
        actual = probe.get('imports', {}).get(name, {})
        if (actual.get('version') != expected or not actual.get('file')
                or not Path(actual['file']).resolve().is_relative_to(prefix.resolve())):
            raise ValueError(f'actual imported module origin/version mismatch: {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='perform the one-shot bounded bootstrap')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'parent': str(PARENT), 'target': str(TARGET),
                          'downloads': str(DEPS), 'pins': PINS, 'models_peak_bytes': PEAK_LIMIT}))
        return 0
    report = {'format': 'annotation_runtime_bootstrap', 'schema_version': '1.0',
              'status': 'running', 'parent': str(PARENT), 'target': str(TARGET),
              'downloads': str(DEPS), 'commands': [], 'wheels': [],
              'runtime_reservation_bytes': PEAK_LIMIT,
              'scope': 'runtime-only quota preflight; models owner must serialize writers; no global-ledger claim',
              'network': {'wheel_bytes': 0}, 'torch_imported': False}
    created = False
    try:
        parent = verify_host()
        report['parent_packages'] = parent
        report['source_sha256'] = sha256(Path(__file__).read_bytes())
        report['requirements_sha256'] = sha256(REQUIREMENTS.read_bytes())
        before = command([PYTHON, '-s', '-B', PREFLIGHT, '--models-peak', str(PEAK_LIMIT)], report)
        report['preflight_before'] = json.loads(before)
        if report['preflight_before'].get('passed') is not True:
            raise ValueError('runtime capacity preflight refused')
        DEPS.mkdir(exist_ok=False)
        created = True
        (DEPS / 'tmp').mkdir()
        selected = []
        for name, version in PINS.items():
            document, source = fetch_metadata(name, version, DEPS / f'{name}-{version}.pypi.json')
            item = select_wheel(name, version, document)
            item['metadata'] = source
            package_info = document['info']
            license_text = package_info.get('license')
            item['license'] = {
                'source_url': source['source_url'],
                'license_expression': package_info.get('license_expression'),
                'license': license_text[:16_000] if isinstance(license_text, str) else license_text,
                'license_text_truncated': isinstance(license_text, str) and len(license_text) > 16_000,
                'classifiers': [value for value in package_info.get('classifiers', [])
                                if isinstance(value, str) and value.startswith('License ::')],
                'note': 'Official package metadata; null remains unknown. Complete response retained with SHA256.',
            }
            selected.append(item)
        declared = sum(item['size_bytes'] for item in selected)
        if declared > DOWNLOAD_LIMIT:
            raise ValueError('four wheels exceed total 30 MB download limit')
        report['wheels'] = selected
        rows = []
        expanded = 0
        paths = []
        for item in selected:
            path = download_wheel(item, report['network'])
            size, requirements, python_spec = inspect_wheel(path, item)
            item['expanded_bytes'] = size
            item['requires_dist'] = requirements
            item['requires_python'] = python_spec
            expanded += size
            rows.append((item['name'], requirements, python_spec))
            paths.append(path)
            own_usage()
        report['dependency_checks'] = check_requirements(rows)
        # Include two compressed copies, two expanded copies, venv/ensurepip,
        # four bounded metadata files and logs. This is a conservative estimate,
        # checked again using actual usage before installation and after it.
        estimated = 2 * declared + 2 * expanded + VENV_RESERVE + OTHER_RESERVE
        report['estimated_peak_bytes'] = estimated
        if estimated > PEAK_LIMIT:
            raise ValueError('estimated download/unpack/venv peak exceeds 100 MB')
        if TARGET.exists() or TARGET.is_symlink():
            raise FileExistsError('annotation-env appeared during preparation')
        TARGET.mkdir(exist_ok=False)
        command([PYTHON, '-s', '-B', '-m', 'venv', '--system-site-packages', TARGET], report)
        report['usage_after_venv_bytes'] = own_usage()
        if report['usage_after_venv_bytes'] + declared + 2 * expanded + OTHER_RESERVE > PEAK_LIMIT:
            raise ValueError('actual venv plus pending installation exceeds 100 MB')
        child = TARGET / 'bin/python'
        # Reverify exact local bytes immediately before passing the four files
        # to pip. Paths are fixed in the exclusive new dependency directory.
        for item, path in zip(selected, paths):
            data = path.read_bytes()
            if len(data) != item['size_bytes'] or sha256(data) != item['sha256']:
                raise ValueError('local wheel changed before installation')
        command([child, '-s', '-B', '-m', 'pip', 'install', '--no-index', '--no-deps',
                 '--no-cache-dir', '--no-compile', '--only-binary=:all:', '--ignore-installed', *paths], report)
        # --ignore-installed only installs these local wheels into the new venv;
        # it avoids uninstalling/reusing any corresponding parent distribution.
        report['usage_after_install_bytes'] = own_usage()
        command([child, '-s', '-B', '-m', 'pip', 'check'], report)
        probe = json.loads(command([child, '-s', '-B', '-c', PROBE, '--imports'], report))
        verify_child(probe, parent)
        report['cpu_probe'] = probe
        if installed(INHERITED) != parent:
            raise ValueError('parent package metadata changed during bootstrap')
        after = command([PYTHON, '-s', '-B', PREFLIGHT], report)
        report['preflight_after'] = json.loads(after)
        if report['preflight_after'].get('passed') is not True:
            raise ValueError('post-install runtime capacity check refused')
        report['actual_new_bytes_before_report'] = own_usage()
        report['status'] = 'succeeded'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    report['finished_at_unix'] = time.time()
    report_path = DEPS / 'bootstrap-report.json'
    if created:
        with report_path.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    print(json.dumps({'status': report['status'], 'report': str(report_path) if created else None,
                      'error': report.get('error'), 'retained_on_failure': created}, ensure_ascii=False))
    return 0 if report['status'] == 'succeeded' else 1


if __name__ == '__main__':
    raise SystemExit(main())
