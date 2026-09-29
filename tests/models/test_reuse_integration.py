"""CPU-only integration of shared worker contracts with this models checkout.

No WSL, GPU, shared runtime database, downloads, or real predictions. The shared
runtime checkout is read-only; all exchange/artifact files are temporary.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get("BTV_REUSE_RUNTIME_REPO", r"C:\Users\USER\Desktop\Program\badmintonTV"))


class ReuseIntegrationTests(unittest.TestCase):
    def run_isolated(self, body, *, shared=False):
        if shared and (not (RUNTIME / "packages/runtime/worker.py").is_file() or importlib.util.find_spec("pydantic") is None):
            self.skipTest("Shared runtime/Pydantic unavailable; set BTV_REUSE_RUNTIME_REPO")
        with tempfile.TemporaryDirectory(prefix="btv-reuse-integration-") as temporary:
            env = dict(os.environ, BTV_STORAGE_ROOT=temporary, PYTHONDONTWRITEBYTECODE="1",
                       BTV_TRACKNET_MANIFEST="models/weights/tracknetv3/reuse-manifest.json")
            prelude = """
import os, sys, json
from pathlib import Path
repo, runtime, root = map(Path, sys.argv[1:])
"""
            result = subprocess.run([sys.executable, "-c", prelude + textwrap.dedent(body), str(REPO), str(RUNTIME), temporary],
                                    cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)

    def test_catalog_is_lazy_and_missing_reuse_is_explicit(self):
        result = self.run_isolated("""
from packages.models.registry import catalog
models = catalog()['models']
selected = [m for m in models if m['model_id'] in {'tracknetv3-reuse', 'qwen3-vl-embedding-2b'}]
assert len(selected) == 2
assert all(m['status'] == 'not_installed' and m['reason'] for m in selected)
assert not any(name in sys.modules for name in ('torch', 'torchvision', 'transformers', 'numpy', 'cv2', 'av'))
print(json.dumps({'ids': [m['model_id'] for m in selected], 'lazy': True}))
""")
        self.assertTrue(result["lazy"])

    def test_reuse_catalog_validates_against_actual_shared_manifest_contract(self):
        result = self.run_isolated("""
sys.path.insert(0, str(runtime))
from packages.contracts import ModelManifest
assert Path(sys.modules['packages.contracts'].__file__).is_relative_to(runtime)
sys.path.insert(0, str(repo))
from packages.models.reuse_catalog import catalog_entries
cards = [ModelManifest.model_validate(card).model_dump(mode='json') for card in catalog_entries(root)]
for card in cards:
    # license_url is explicitly optional in shared Weight, even when populated.
    card['weights'] = [{'relative_path': 'models/weights/metadata-only.pt', 'sha256': 'a' * 64}]
    parsed = ModelManifest.model_validate(card)
    assert parsed.weights[0].license_url is None
assert not any(name in sys.modules for name in ('torch', 'transformers', 'av'))
print(json.dumps({'validated': [card['model_id'] for card in cards]}))
""", shared=True)
        self.assertIn("tracknetv3-reuse", result["validated"])

    def test_main_native_module_origin_with_pinned_runtime_cwd(self):
        result = self.run_isolated("""
import importlib.util, subprocess
code = "import importlib.util,json;print(json.dumps({n:importlib.util.find_spec(n).origin for n in ('packages.runtime.launcher','packages.runtime.wsl_bridge')}))"
env = dict(os.environ, PYTHONPATH=str(runtime))
probe = subprocess.run([sys.executable, '-c', code], cwd=runtime, env=env, capture_output=True, text=True, check=True)
origins = json.loads(probe.stdout)
assert all(Path(origin).is_relative_to(runtime) for origin in origins.values())
print(json.dumps(origins))
""", shared=True)
        self.assertIn("packages.runtime.wsl_bridge", result)

    def test_actual_worker_builds_tracking_attempt_and_dispatch_preserves_scope(self):
        result = self.run_isolated("""
import contextlib, hashlib, io, types
from unittest.mock import Mock, patch
sys.path.insert(0, str(runtime))
from packages.runtime import worker
from packages.contracts import JobResult
assert Path(worker.__file__).is_relative_to(runtime)
sys.path.insert(0, str(repo))
from packages.models import protocol, inference, storage, tracknet_reuse
assert Path(protocol.__file__).is_relative_to(repo)
fixture = json.loads((repo / 'packages/contracts/fixtures/model-request.json').read_text(encoding='utf-8'))
asset = fixture['assets'][0]
source = root / 'data/training/structure-only.bin'
source.parent.mkdir(parents=True)
source.write_bytes(b'CPU structure fixture; no actual media or predictions')
asset.update(relative_path='data/training/structure-only.bin', size_bytes=source.stat().st_size,
             sha256=hashlib.sha256(source.read_bytes()).hexdigest(), usage_scope='general')
asset['provenance']['usage_scope'] = 'training_only'
payload = {'model_id':'tracknetv3-reuse', 'model_version':'0.1.0', 'adapter_operation':'tracking',
           'gpu_required':True, 'assets':[asset], 'parameters':{'model_id':'untrusted-parameter-value',
           'model_version':'wrong-parameter-version', 'mode':'causal_last', 'start_ms':0, 'end_ms':1000}}
job = {'job_id':'job-cpu-reuse-integration', 'attempt':2, 'operation':'model', 'payload':payload}
exchange = root / 'platform/jobs/job-cpu-reuse-integration/attempt-2'
exchange.mkdir(parents=True)
context = types.SimpleNamespace(job=job, storage_root=root, registered_command=['test-only-in-process-protocol'],
                                log=Mock(), check=Mock())
captured = {}
def execute(argv, stage, **kwargs):
    assert stage == 'model' and kwargs['parse_progress'] is True
    request_path, result_path = argv[argv.index('--request')+1], argv[argv.index('--result')+1]
    captured.update(json.loads(Path(request_path).read_text(encoding='utf-8')))
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = protocol.run_request(request_path, result_path)
    wire = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [row['seq'] for row in wire] == list(range(1, len(wire)+1))
    return code, stdout.getvalue(), ''
context.execute = execute
fake_runtime = types.SimpleNamespace(seq_len=3, bg_mode='concat', details=lambda: {'kind':'CPU test double'},
              manifest={'code':{'relative_path':'models/upstream/TEST-ONLY/model.py'},
                        'checkpoint':{'relative_path':'models/weights/TEST-ONLY/not-real.pt'}})
with patch.object(storage.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=10**12)), \
     patch.object(inference, 'reserve', side_effect=AssertionError('legacy reservation must not run')), \
     patch.object(tracknet_reuse, 'Runtime', return_value=fake_runtime), \
     patch.object(tracknet_reuse, 'process', return_value=([], {'test_double':True})):
    outcome = worker.adapter(context, exchange)
assert outcome['status'] == 'succeeded' and outcome['exit_code'] == 0
assert captured['operation'] == 'tracking' and captured['attempt_id'] == 'attempt-2'
assert captured['parameters']['model_id'] == 'tracknetv3-reuse'
assert captured['parameters']['model_version'] == '0.1.0'
assert captured['assets'][0]['provenance']['usage_scope'] == 'training_only'
assert captured['output_dir'] == 'models/jobs/job-cpu-reuse-integration/attempt-2'
for artifact in outcome['artifacts']:
    assert artifact['producer']['usage_scope'] == 'training_only'
    content = json.loads((root / artifact['relative_path']).read_text(encoding='utf-8'))
    assert content['usage_scope'] == 'training_only' and content['accuracy'] is None
assert not (root / 'models/.writer-reservation.json').exists()
assert not any(name in sys.modules for name in ('torch', 'transformers', 'cv2', 'av'))
print(json.dumps({'status':outcome['status'], 'attempt_id':outcome['attempt_id'], 'scope':'training_only'}))
""", shared=True)
        self.assertEqual(result, {"status": "succeeded", "attempt_id": "attempt-2", "scope": "training_only"})

    def test_real_protocol_missing_tracknet_is_blocked_with_worker_identity(self):
        result = self.run_isolated("""
import contextlib, hashlib, io, types
from unittest.mock import patch
from packages.models import protocol, storage
request = json.loads((repo / 'packages/contracts/fixtures/model-request.json').read_text(encoding='utf-8'))
source = root / 'data/general/structure-only.bin'
source.parent.mkdir(parents=True)
source.write_bytes(b'not video; expected to block before decode')
request['assets'][0].update(relative_path='data/general/structure-only.bin', size_bytes=source.stat().st_size,
                            sha256=hashlib.sha256(source.read_bytes()).hexdigest())
request.update(operation='tracking', job_id='job-worker-shaped', attempt_id='attempt-3',
               output_dir='models/jobs/job-worker-shaped/attempt-3')
request['parameters'] = {'model_id':'tracknetv3-reuse','model_version':'0.1.0','mode':'causal_last'}
request_path, result_path = root / 'request.json', root / 'result.json'
request_path.write_text(json.dumps(request), encoding='utf-8')
with patch.object(storage.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=10**12)), contextlib.redirect_stdout(io.StringIO()):
    code = protocol.run_request(request_path, result_path)
outcome = json.loads(result_path.read_text(encoding='utf-8'))
assert code == 2 and outcome['status'] == 'blocked'
assert outcome['error']['code'] == 'TRACKNET_NOT_INSTALLED'
assert outcome['job_id'] == 'job-worker-shaped' and outcome['attempt_id'] == 'attempt-3'
assert not (root / 'models/.writer-reservation.json').exists()
assert not any(name in sys.modules for name in ('torch','cv2','av'))
print(json.dumps({'code':code,'status':outcome['status']}))
""")
        self.assertEqual(result, {"code": 2, "status": "blocked"})


if __name__ == "__main__":
    unittest.main()
