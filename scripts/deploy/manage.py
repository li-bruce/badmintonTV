#!/usr/bin/env python3
"""Portable source distributions and isolated CPU deployment (stdlib only)."""
from __future__ import annotations
import argparse
from contextlib import closing, ExitStack
import io
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MAX_FILE = 8_000_000
MAX_ARCHIVE = 100_000_000
FORBIDDEN_PARTS = {'.git', '.runtime', '.venv', 'venv', 'node_modules', '__pycache__', '.aws', '.codex', '.agents', 'outputs', 'checkpoints', 'logs'}
FORBIDDEN_SUFFIXES = {'.mp4', '.mkv', '.mov', '.avi', '.webm', '.wav', '.mp3', '.pt', '.pth', '.safetensors', '.onnx', '.ckpt', '.bin', '.npy', '.npz', '.parquet', '.sqlite', '.sqlite3', '.db', '.zip', '.7z', '.tar', '.gz', '.pem', '.key', '.pfx', '.log'}
ALLOWED_SUFFIXES = {'.py', '.toml', '.json', '.jsonl', '.md', '.txt', '.ps1', '.sh', '.js', '.cjs', '.mjs', '.css', '.html', '.yml', '.yaml', '.csv', '.tsv', '.svg'}
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{64,}|(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-proj-[A-Za-z0-9_-]{40,}')


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def config(root=ROOT):
    return json.loads((root / 'deployment/modules.json').read_text(encoding='utf-8-sig'))


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + root.as_posix(), '-C', str(root), *args], stderr=subprocess.PIPE)


def safe_relative(value):
    p = PurePosixPath(value)
    if not value or '\\' in value or p.is_absolute() or any(ord(c)<32 or c in ':*?"<>|' for c in value) or any(s in ('', '.', '..') for s in value.split('/')):
        raise ValueError('Unsafe relative path: ' + value)
    for part in p.parts:
        if part.endswith((' ', '.')) or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
            raise ValueError('Nonportable path: ' + value)
    return p


def no_links(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Symlink/junction paths are not allowed: ' + str(item))
    return path


def source_allowed(name):
    p = safe_relative(name)
    if any(part.casefold() in FORBIDDEN_PARTS for part in p.parts):
        return False
    if p.name.startswith('.env') or p.name.startswith('config.local.') or p.suffix.casefold() in FORBIDDEN_SUFFIXES:
        return False
    if any(word in p.name.casefold() for word in ('credentials', 'id_rsa', 'id_ed25519', 'secrets.local')):
        return False
    return p.suffix.casefold() in ALLOWED_SUFFIXES or p.name in ('.gitignore', '.gitattributes', 'LICENSE', 'NOTICE')


def closure(names, cfg):
    result = set()
    def visit(name):
        if name in result:
            return
        if name not in cfg['modules']:
            raise ValueError('Unknown module: ' + name)
        result.add(name)
        for dependency in cfg['modules'][name]['depends']:
            visit(dependency)
    for name in names:
        visit(name)
    return sorted(result)


def selected(name, modules, cfg, full=False):
    if full:
        return name.split('/')[0] in {'apps', 'packages', 'configs', 'scripts', 'tests', 'docs', 'environments', 'deployment'} or '/' not in name
    patterns = cfg['common'] + [p for m in modules for p in cfg['modules'][m]['include']]
    # Root design/contract/acceptance files accompany every component.
    if name.startswith('docs/') and len(PurePosixPath(name).parts) == 2 and name.endswith('.md'):
        return True
    return any(name == p or (p.endswith('/') and name.startswith(p)) or (p.startswith('environments/') and name.startswith(p)) for p in patterns)


def source_files(root, module, allow_dirty=False):
    if module == 'complete': module = 'full'
    cfg = config(root)
    dirty = git(root, 'status', '--porcelain', '--untracked-files=all').decode('utf-8')
    if dirty and not allow_dirty:
        raise ValueError('Working tree has uncommitted/untracked changes. Commit first; --allow-dirty is only for explicitly marked trial packages.')
    modules = closure(list(cfg['modules']) if module == 'full' else [module], cfg)
    revision = git(root, 'rev-parse', 'HEAD').decode().strip()
    specs = []
    entries = []
    for raw in git(root, 'ls-tree', '-r', '-z', revision).split(b'\0'):
        if not raw:
            continue
        metadata, raw_name = raw.split(b'\t', 1)
        name = raw_name.decode('utf-8')
        mode, kind, oid = metadata.decode().split()
        safe_relative(name)
        if not selected(name, modules, cfg, module == 'full'):
            continue
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('Refusing linked/submodule/unmerged source: ' + name)
        if not source_allowed(name):
            raise ValueError('Forbidden tracked content in package selection: ' + name)
        no_links(root / name)
        specs.append((name, mode, oid))
    batch = subprocess.run(['git', '-c', 'safe.directory='+root.as_posix(), '-C', str(root), 'cat-file', '--batch'], input=('\n'.join(oid for _,_,oid in specs)+'\n').encode(), capture_output=True, check=True)
    stream = io.BytesIO(batch.stdout)
    for name, mode, oid in specs:
        header = stream.readline().decode().split()
        if len(header) != 3 or header[0] != oid or header[1] != 'blob':
            raise ValueError('Invalid Git blob response')
        size = int(header[2])
        data = stream.read(size)
        stream.read(1)
        if allow_dirty:
            path = no_links(root / name)
            if path.is_file(): data = path.read_bytes()
        if len(data) > MAX_FILE or b'\0' in data or SECRET.search(data):
            raise ValueError('Oversized/binary/credential content refused: ' + name)
        entries.append((name, data, mode))
    if sum(len(data) for _, data, _ in entries) > MAX_ARCHIVE:
        raise ValueError('Source package exceeds 100 MB limit')
    return modules, entries, dirty, revision


def export_source(root, module, output, allow_dirty=False):
    modules, entries, dirty, revision = source_files(root, module, allow_dirty)
    output = no_links(output)
    if output.exists():
        raise ValueError('Output already exists: ' + str(output))
    if not output.parent.is_dir():
        raise ValueError('Create the output parent directory first')
    manifest = {'schema_version': '1.0', 'module': module, 'included_modules': modules, 'source_commit': revision, 'uncommitted': bool(dirty), 'dirty_status': dirty.splitlines(), 'excluded': ['media', 'weights', 'environments', 'databases', 'credentials', '.git'], 'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data, _ in entries]}
    continuation = ('# Continue development\n\nPackage: '+module+'\nSource commit: '+revision+'\nUncommitted source: '+str(bool(dirty))+'\n\nRead AGENTS.md, PROJECT_PLAN_SIMPLE.md, docs/PRODUCT_CONTEXT.md, docs/ARCHITECTURE.md, docs/CONTRACTS.md, docs/EXECUTION_PLAN.md, docs/ACCEPTANCE.md, and docs/deployment/README.md. The common contract/runtime source is included. Input/output boundaries are in deployment/modules.json. Keep module ownership; do not silently change contracts.\n\nRun `python scripts/deploy/manage.py profiles` then `plan` before setup. Python dependencies need Internet access or a separately prepared wheelhouse; no environments/media/weights/database are included. Rebuild environments on each device.\n\nTo preserve project history use the separately delivered full Git bundle. For a standalone source-only checkout, `git init -b codex/'+module+'` then commit the verified files; do not pretend this recreated the original Git history. Do not import generated source-manifest.json into a later source bundle unless explicitly required.\n')
    # Exclusive output creation prevents overwriting earlier releases.
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (int(mode, 8) << 16)
            archive.writestr(info, data)
        archive.writestr('source-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr('CONTINUE_DEVELOPMENT.md', continuation)
    return {'output': str(output), 'bytes': output.stat().st_size, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'source_commit': revision, 'modules': modules, 'files': len(entries), 'uncommitted': bool(dirty)}


def verify_archive(path):
    with zipfile.ZipFile(no_links(path)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive members')
        if sum(i.file_size for i in archive.infolist()) > MAX_ARCHIVE + 8_000_000:
            raise ValueError('Archive uncompressed size exceeds limit')
        for info in archive.infolist():
            safe_relative(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Linked archive entry')
        manifest = json.loads(archive.read('source-manifest.json'))
        expected = {item['path'] for item in manifest['files']}
        if len(expected) != len(manifest['files']) or set(names) != expected | {'source-manifest.json', 'CONTINUE_DEVELOPMENT.md'}:
            raise ValueError('Manifest/member mismatch')
        for item in manifest['files']:
            if not source_allowed(item['path']):
                raise ValueError('Forbidden archive member')
            data = archive.read(item['path'])
            if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256'] or SECRET.search(data):
                raise ValueError('Source hash/size/secret check failed: ' + item['path'])
    return {'status':'verified', 'source_commit':manifest['source_commit'], 'uncommitted':manifest['uncommitted'], 'files':len(expected), 'module':manifest['module']}


def env_python(prefix):
    return prefix / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def wsl_path(value):
    path = PureWindowsPath(value)
    if len(path.drive) != 2 or path.drive[1] != ':' or not path.is_absolute():
        raise ValueError('WSL delegation needs a local Windows drive path. For UNC/network paths run plan inside WSL with Linux paths.')
    return '/mnt/' + path.drive[0].lower() + '/' + '/'.join(path.parts[1:])


def make_plan(args, root=ROOT):
    if sys.version_info < (3, 11):
        raise ValueError('Python 3.11 or newer is required')
    cfg = config(root)
    profile = cfg['profiles'][args.profile]
    storage = no_links(args.storage_root)
    if not Path(args.storage_root).is_absolute():
        raise ValueError('--storage-root must be absolute')
    env_root = no_links(args.env_root) if args.env_root else storage / 'runtime' / profile['runtime_owner'] / 'envs'
    prefix = env_root / args.profile
    if not env_root.is_relative_to(storage / 'runtime' / profile['runtime_owner']):
        raise ValueError('--env-root must stay within storage-root/runtime/' + profile['runtime_owner'] + ' for quota accounting')
    modules = closure(profile['modules'], cfg)
    missing = [m for m in modules if not (root / ('apps/platform' if m == 'workbench' else 'packages/contracts' if m == 'core' else 'packages/'+m)).is_dir()]
    if missing:
        raise ValueError('This source package lacks modules: ' + ', '.join(missing))
    py = env_python(prefix)
    if 'delegate_profile' in profile:
        script = root/'scripts/models/setup_device.sh'
        if not script.is_file():
            raise ValueError('This source package lacks scripts/models/setup_device.sh; install the current models/full source package')
        if os.name == 'nt':
            command = ['wsl.exe', '-d', 'Ubuntu', '--', 'bash', wsl_path(script), '--profile', profile['delegate_profile'], '--storage-root', wsl_path(storage), '--env-prefix', wsl_path(prefix)]
        else:
            command = ['bash', str(script), '--profile', profile['delegate_profile'], '--storage-root', str(storage), '--env-prefix', str(prefix)]
        return {'profile': args.profile, 'delegated': True, 'command': command, 'installation_platform':'WSL Ubuntu', 'note': 'Add --conda-executable /absolute/prefix/bin/conda and --apply inside WSL Ubuntu. Native Linux/macOS GPU installation is not validated/supported by this installer; CPU setup never installs GPU packages.'}
    requirement = root / ('deployment/requirements-dev.txt' if getattr(args, 'dev', False) else profile['requirements'])
    if getattr(args, 'dev', False) and args.profile not in ('workbench-cpu', 'desktop-cpu'):
        raise ValueError('--dev currently applies only to workbench/desktop (includes their test dependencies)')
    return {'profile': args.profile, 'delegated': False, 'gpu': False, 'source_root': str(root), 'storage_root': str(storage), 'environment': str(prefix), 'python': str(py), 'ffmpeg_required': profile['ffmpeg'], 'commands': [[sys.executable, '-m', 'venv', str(prefix)], [str(py), '-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:', '-r', str(requirement)], [str(py), '-m', 'pip', 'check']], 'environment_variables': {'BTV_STORAGE_ROOT': str(storage), 'BTV_RENDER_BACKEND': 'cpu', 'PYTHONPATH': str(root), 'PYTHONNOUSERSITE': '1', 'PIP_CACHE_DIR': str(storage/'runtime'/profile['runtime_owner']/'pip-cache'), 'TMP': str(storage/'runtime'/profile['runtime_owner']/'tmp'), 'TEMP': str(storage/'runtime'/profile['runtime_owner']/'tmp'), 'TMPDIR': str(storage/'runtime'/profile['runtime_owner']/'tmp')}}


def setup(args, root=ROOT):
    plan = make_plan(args, root)
    if args.dry_run:
        return plan
    if plan['delegated']:
        raise ValueError('Use the delegated models setup command; CPU setup will not create a model environment')
    prefix = no_links(plan['environment'])
    if prefix.exists():
        raise ValueError('Environment exists; select a new --env-root. Existing environments are never overwritten.')
    storage = Path(plan['storage_root'])
    if not storage.is_dir():
        raise ValueError('Create and budget --storage-root first')
    reserve = args.max_install_bytes
    if reserve <= 0 or reserve > 10_000_000_000:
        raise ValueError('--max-install-bytes must be 1..10000000000')
    sys.path.insert(0, str(root))
    from packages.runtime.storage import CapacityLedger, directory_bytes
    used = directory_bytes(storage)
    if args.max_storage_bytes > 700_000_000_000 or used + reserve > args.max_storage_bytes or shutil.disk_usage(storage).free < reserve:
        raise ValueError('Storage budget or physical free space insufficient for reserved installation peak')
    sys.path.insert(0, str(root))
    from packages.runtime.storage import CapacityLedger, directory_bytes
    owner = 'runtime/' + config(root)['profiles'][args.profile]['runtime_owner']
    ledger = CapacityLedger(storage/'platform/runtime.sqlite3', storage)
    reservation = ledger.reserve(owner, reserve, job_id='deployment-' + args.profile)
    before_bytes = directory_bytes(storage/owner)
    # Serialize deployment itself; the shared ledger also accounts for concurrent jobs.
    lock = storage / '.btv-deployment.lock'
    try:
        with lock.open('x', encoding='utf-8') as handle:
            handle.write(str(os.getpid()))
    except BaseException:
        ledger.release(reservation)
        raise
    try:
        prefix.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, **plan['environment_variables']}
        for key in ('PIP_CACHE_DIR', 'TMPDIR'):
            no_links(env[key]).mkdir(parents=True, exist_ok=True)
        for command in plan['commands']:
            process = subprocess.Popen(command, cwd=root, env=env)
            while process.poll() is None:
                if directory_bytes(storage/owner) - before_bytes > reserve:
                    process.terminate()
                    process.wait(timeout=15)
                    raise ValueError('Installation exceeded reserved byte budget; partial environment retained for inspection')
                time.sleep(.5)
            if directory_bytes(storage/owner) - before_bytes > reserve:
                raise ValueError('Installation exceeded reserved byte budget; partial environment retained for inspection')
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        result = {'status': 'installed', **plan}
        (prefix/'btv-deployment.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    finally:
        lock.unlink()
        ledger.release(reservation)


def doctor(args, root=ROOT):
    plan = make_plan(args, root)
    if plan['delegated']:
        return {**plan, 'status': 'use_model_doctor'}
    py = Path(plan['python'])
    probes = {'python': py.is_file(), 'storage_root': Path(plan['storage_root']).is_dir(), 'ffmpeg': shutil.which(args.ffmpeg), 'ffprobe': shutil.which(args.ffprobe)}
    required_ok = probes['python'] and probes['storage_root'] and (not plan['ffmpeg_required'] or (probes['ffmpeg'] and probes['ffprobe']))
    if probes['python']:
        imports = ['packages.contracts', 'packages.runtime']
        imports += ['fastapi', 'uvicorn', 'jinja2', 'httpx', 'multipart', 'apps.platform.store', 'apps.platform.artifact_response', 'apps.platform.training_catalog'] if args.profile in ('workbench-cpu', 'desktop-cpu') else []
        imports += ['packages.'+m for m in ('library', 'render') if m in closure(config(root)['profiles'][args.profile]['modules'], config(root))]
        script = 'import importlib,json,sys; [importlib.import_module(m) for m in '+repr(imports)+']; print(json.dumps({"imports":'+repr(imports)+',"torch_imported":"torch" in sys.modules}))'
        process = subprocess.run([str(py), '-s', '-c', script], cwd=root, env={**os.environ, **plan['environment_variables']}, capture_output=True, text=True)
        probes['imports'] = {'returncode': process.returncode, 'output': process.stdout.strip(), 'error': process.stderr[-2000:]}
        dependency_check = subprocess.run([str(py), '-m', 'pip', 'check'], cwd=root, env={**os.environ, **plan['environment_variables']}, capture_output=True, text=True)
        probes['pip_check'] = {'returncode':dependency_check.returncode, 'output':dependency_check.stdout.strip(), 'error':dependency_check.stderr[-2000:]}
        if args.profile in ('workbench-cpu', 'desktop-cpu'):
            probes['web_resources'] = all((root/p).is_file() for p in ('apps/platform/templates/training.html','apps/platform/static/training.js','configs/models/taxonomy.v1.json'))
            required_ok = required_ok and probes['web_resources']
        required_ok = required_ok and process.returncode == 0 and dependency_check.returncode == 0
    return {'profile': args.profile, 'status': 'ready' if required_ok else 'missing_dependencies', 'checks': probes, 'plan': plan}


def run(args, root=ROOT):
    plan = make_plan(args, root)
    if plan['delegated']:
        raise ValueError('Run model jobs with the models environment/CLI')
    py = Path(args.python) if args.python else Path(plan['python'])
    if not py.is_file():
        raise ValueError('Environment missing: ' + str(py))
    cfg = config(root)
    modules = closure(cfg['profiles'][args.profile]['modules'], cfg)
    if args.target in ('web', 'worker') and 'workbench' not in modules:
        raise ValueError('Web/worker needs a workbench profile')
    if args.target in ('library', 'render') and args.target not in modules:
        raise ValueError('Target is absent from the selected profile')
    env = {**os.environ, **plan['environment_variables'], 'BTV_TRAINING_ACTOR_TYPE': args.reviewer}
    if args.database:
        env['BTV_DB_PATH'] = str(Path(args.database).resolve())
    env['BTV_FFMPEG'], env['BTV_FFPROBE'] = args.ffmpeg, args.ffprobe
    manifest = root/'source-manifest.json'
    env['BTV_CODE_REVISION'] = json.loads(manifest.read_text(encoding='utf-8'))['source_commit'] if manifest.exists() else git(root, 'rev-parse', 'HEAD').decode().strip() if (root/'.git').exists() else 'unversioned'
    command = [str(py)]
    if args.target == 'web':
        command += ['-m', 'uvicorn', 'apps.platform.main:app', '--host', '127.0.0.1', '--port', str(args.port)]
    elif args.target == 'worker':
        db = Path(args.database).resolve().with_name('runtime.sqlite3') if args.database else Path(plan['storage_root'])/'platform/runtime.sqlite3'
        command += ['-m', 'packages.runtime.worker', '--db', str(db), '--storage-root', plan['storage_root']]
    else:
        command += ['-m', 'packages.'+args.target, *(args.extra[1:] if args.extra[:1] == ['--'] else args.extra)]
        if args.target == 'render' and '--backend' not in command:
            command += ['--backend', 'cpu'] if 'run' in command else []
    if args.dry_run:
        return {'command': command, 'cwd': str(root), 'env': {k: v for k,v in env.items() if k.startswith('BTV_') and 'KEY' not in k and 'TOKEN' not in k}}
    return subprocess.call(command, cwd=root, env=env)


def export_state(args):
    storage = no_links(args.storage_root)
    output = no_links(args.output)
    if not output.is_relative_to(storage/'platform'):
        raise ValueError('--output must be within storage-root/platform for backup quota accounting; copy the completed backup separately to the destination device')
    sys.path.insert(0, str(ROOT))
    from packages.runtime.storage import CapacityLedger
    ledger = CapacityLedger(storage/'platform/runtime.sqlite3', storage)
    reservation = ledger.reserve('platform', args.max_bytes, job_id='deployment-state-export')
    try:
        args.reservation_id = reservation
        with ExitStack() as stack:
            watchers = []
            for value in args.database:
                path = no_links(storage / str(safe_relative(value)))
                connection = stack.enter_context(closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)))
                watchers.append((connection, connection.execute('PRAGMA data_version').fetchone()[0]))
            result = _export_state(args)
            if any(connection.execute('PRAGMA data_version').fetchone()[0] != version for connection, version in watchers):
                (output/'INCOMPLETE.txt').write_text('Source changed during export. Stop API/workers, then export to a new directory.',encoding='utf-8')
                raise ValueError('Source database changed during export; output marked INCOMPLETE')
            return result
    finally:
        ledger.release(reservation)


def _export_state(args):
    storage = no_links(args.storage_root)
    output = no_links(args.output)
    if not storage.is_dir() or output.exists() or not output.parent.is_dir():
        raise ValueError('Storage/output parent must exist and output must be new')
    if args.max_bytes <= 0 or args.max_bytes > 60_000_000_000:
        raise ValueError('State export must have a positive budget <= 60 GB')
    if shutil.disk_usage(output.parent).free < args.max_bytes:
        raise ValueError('Insufficient free space for requested export budget')
    references = []
    reference_ids = {}
    source_manifests = []
    manifest_bytes = 0
    for source in args.manifest:
        manifest_path = no_links(source)
        if manifest_path.stat().st_size > 10_000_000:
            raise ValueError('Manifest exceeds 10 MB read limit')
        raw = manifest_path.read_bytes()
        manifest_bytes += len(raw)
        if manifest_bytes > args.max_bytes:
            raise ValueError('Original manifests exceed export budget')
        content = json.loads(raw.decode('utf-8-sig'))
        relative_manifest = 'source-manifests/' + str(len(source_manifests)+1).zfill(4) + '-' + manifest_path.name
        safe_relative(relative_manifest)
        source_manifests.append({'file':relative_manifest, 'original_name':manifest_path.name, 'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw), '_raw':raw})
        for asset in content.get('assets', []):
            relative = asset.get('relative_path') or asset.get('storage', {}).get('relative_path')
            safe_relative(relative or '')
            digest = asset.get('sha256')
            if not re.fullmatch('[0-9a-f]{64}', digest or '') or not asset.get('asset_id'):
                raise ValueError('Each asset must provide asset_id, relative_path and SHA256')
            identity = (relative, digest)
            if asset['asset_id'] in reference_ids and reference_ids[asset['asset_id']] != identity:
                raise ValueError('Conflicting asset identity across manifests')
            reference_ids[asset['asset_id']] = identity
            verification = 'not_checked'
            if args.verify_assets:
                media = no_links(storage/relative)
                hasher = hashlib.sha256()
                with media.open('rb') as handle:
                    for chunk in iter(lambda: handle.read(1024*1024), b''): hasher.update(chunk)
                if hasher.hexdigest() != digest: raise ValueError('Asset SHA256 mismatch: '+asset['asset_id'])
                verification = 'sha256_verified'
            references.append({'asset_id': asset['asset_id'], 'relative_path': relative, 'sha256': digest, 'usage_scope': asset.get('usage_scope'), 'usage_policy': asset.get('usage_policy'), 'rights': asset.get('rights'), 'provenance':asset.get('provenance'), 'source_manifest':relative_manifest, 'manifest': Path(source).name, 'source_verification': verification})
    databases = []
    for value in args.database:
        rel = safe_relative(value)
        source = no_links(storage / str(rel))
        if source.suffix.lower() not in ('.db', '.sqlite', '.sqlite3'):
            raise ValueError('Use a .db/.sqlite/.sqlite3 database filename to prevent output name collisions')
        if not source.is_file():
            raise ValueError('Missing database: ' + str(source))
        databases.append(source)
    if len(databases) > 1 and not args.quiesced:
        raise ValueError('For multiple databases stop API/workers first and pass --quiesced. Separate backups are not a cross-database transaction.')
    if len({p.name for p in databases}) != len(databases):
        raise ValueError('Duplicate database output names')
    output.mkdir()
    incomplete = output/'INCOMPLETE.txt'
    incomplete.write_text('Export is incomplete. Do not restore this directory. See the error from export-state.', encoding='utf-8')
    report = {'schema_version':'1.0', 'media_copied':False, 'quiesced_asserted':args.quiesced, 'assets':references, 'assets_are_reference_inventory_only':True, 'source_manifests':[{k:v for k,v in item.items() if k!='_raw'} for item in source_manifests], 'databases':[], 'note':'Copy media separately by relative path; verify SHA256 at destination. Credentials in database configuration may remain sensitive; keep this backup private.'}
    remaining = args.max_bytes - manifest_bytes
    if source_manifests:
        (output/'source-manifests').mkdir()
        for item in source_manifests:
            with (output/item['file']).open('xb') as handle: handle.write(item['_raw'])
    for source in databases:
        destination = output/source.name
        started = time.monotonic()
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True, timeout=5)) as origin, closing(sqlite3.connect(destination)) as target:
            pages = origin.execute('PRAGMA page_count').fetchone()[0]
            page_size = origin.execute('PRAGMA page_size').fetchone()[0]
            if pages*page_size > remaining:
                raise ValueError('Database exceeds export budget')
            def progress(status, pending, total):
                if total*page_size > remaining or time.monotonic()-started > 60:
                    raise ValueError('Backup budget/time limit exceeded')
            tables = {row[0] for row in origin.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if args.quiesced and 'jobs' in tables and origin.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('running','queued') OR (cancel_requested=1 AND status NOT IN ('succeeded','failed','cancelled','blocked'))").fetchone()[0]:
                raise ValueError('Queue still has runnable/running jobs; finish/cancel/recover them before a quiesced migration')
            if args.quiesced and 'resource_leases' in tables and origin.execute("SELECT COUNT(*) FROM resource_leases WHERE status IN ('active','orphaned')").fetchone()[0]:
                raise ValueError('GPU lease still active/orphaned; recover it on the original device before migration')
            origin.backup(target, pages=128, progress=progress, sleep=.05)
            reset_reservations = 0
            reset_database_binding = 0
            if args.quiesced and 'runtime_metadata' in tables:
                reset_database_binding = target.execute("DELETE FROM runtime_metadata WHERE key='business_database'").rowcount
                target.commit()
            if 'reservations' in tables:
                if args.quiesced:
                    reset_reservations = target.execute('UPDATE reservations SET released_at=? WHERE released_at IS NULL', (time.time(),)).rowcount
                else:
                    reset_reservations = target.execute('UPDATE reservations SET released_at=? WHERE reservation_id=? AND released_at IS NULL', (time.time(),args.reservation_id)).rowcount
                target.commit()
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity check failed')
        remaining -= destination.stat().st_size
        report['databases'].append({'source':source.relative_to(storage).as_posix(), 'file':destination.name, 'capacity_reservations_closed_in_copy': reset_reservations, 'database_binding_removed_in_copy': bool(reset_database_binding), 'bytes':destination.stat().st_size, 'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()})
    data = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')
    if len(data) > remaining:
        raise ValueError('Manifest exceeds remaining export budget')
    (output/'migration-manifest.json').write_bytes(data)
    incomplete.unlink()
    return {'output':str(output), 'databases':len(databases), 'assets':len(references), 'media_copied':False}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='operation', required=True)
    sub.add_parser('profiles')
    for operation in ('plan', 'setup', 'doctor', 'run'):
        q = sub.add_parser(operation)
        q.add_argument('--profile', choices=list(config()['profiles']), default='workbench-cpu')
        q.add_argument('--storage-root', required=True)
        q.add_argument('--env-root')
        q.add_argument('--ffmpeg', default=os.getenv('BTV_FFMPEG', 'ffmpeg'))
        q.add_argument('--ffprobe', default=os.getenv('BTV_FFPROBE', 'ffprobe'))
        q.add_argument('--dry-run', action='store_true')
        if operation in ('plan', 'setup'):
            q.add_argument('--dev', action='store_true')
        if operation == 'setup':
            q.add_argument('--max-install-bytes', type=int, default=2_000_000_000)
            q.add_argument('--max-storage-bytes', type=int, default=700_000_000_000)
        if operation == 'run':
            q.add_argument('--python')
            q.add_argument('--target', choices=('web', 'worker', 'library', 'render'), default='web')
            q.add_argument('--reviewer', choices=('agent', 'human'), default='human')
            q.add_argument('--database')
            q.add_argument('--port', type=int, default=18080)
            q.add_argument('extra', nargs=argparse.REMAINDER)
    q = sub.add_parser('export')
    q.add_argument('--module', choices=[*config()['modules'], 'full', 'complete'], required=True)
    q.add_argument('--output', type=Path, required=True)
    q.add_argument('--allow-dirty', action='store_true')
    q = sub.add_parser('export-state')
    q.add_argument('--storage-root', required=True)
    q.add_argument('--output', required=True)
    q.add_argument('--manifest', action='append', default=[])
    q.add_argument('--database', action='append', default=[], help='Storage-relative SQLite path; repeat for multiple DBs')
    q.add_argument('--quiesced', action='store_true')
    q.add_argument('--verify-assets', action='store_true', help='Read each referenced file and verify SHA256; no copying')
    q.add_argument('--max-bytes', type=int, default=100_000_000)
    q = sub.add_parser('verify')
    q.add_argument('--archive', type=Path, required=True)
    return p


def main():
    args = parser().parse_args()
    try:
        if args.operation == 'profiles': result = config()
        elif args.operation == 'plan': result = make_plan(args)
        elif args.operation == 'setup': result = setup(args)
        elif args.operation == 'doctor': result = doctor(args)
        elif args.operation == 'run': result = run(args)
        elif args.operation == 'verify': result = verify_archive(args.archive)
        elif args.operation == 'export': result = export_source(ROOT, args.module, args.output, args.allow_dirty)
        else: result = export_state(args)
        if isinstance(result, int): return result
        emit(result)
        return 1 if result.get('status') == 'missing_dependencies' else 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, sqlite3.Error, zipfile.BadZipFile) as error:
        emit({'status':'error', 'message':str(error)})
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
