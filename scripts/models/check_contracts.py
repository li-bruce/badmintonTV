"""Read shared platform contracts from a supplied checkout without modifying it."""
import argparse
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--contracts-repo',required=True)
parser.add_argument('--storage-root',default='D:/video')
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(repo))
import packages.models.protocol as local
from packages.models.registry import catalog
from packages.models.query import parse_rule
# Both are namespace packages, so add the other checkout to the namespace path.
import packages
packages.__path__.append(str(Path(args.contracts_repo)/'packages'))
from packages.contracts import AssetManifest, JobRequest, JobResult, ModelManifest, QuerySpec, validate_job_result

fixtures = Path(args.contracts_repo)/'packages/contracts/fixtures'
request = json.loads((fixtures/'model-request.json').read_text(encoding='utf-8'))
local.validate_request(request)
JobRequest.model_validate(request)
for name in ['result-succeeded.json','result-failed.json','result-blocked.json','result-cancelled.json']:
    JobResult.model_validate_json((fixtures/name).read_text(encoding='utf-8'))
for model in catalog()['models']:
    ModelManifest.model_validate(model)
QuerySpec.model_validate(parse_rule('交叉步后退，随后起跳杀球，然后上网扑球')[0])
root = Path(args.storage_root)
assets = AssetManifest.model_validate_json((root/'data/handoff/assets.v1.json').read_text(encoding='utf-8'))
asset_count = len(assets.assets)
doubles_path = root/'data/handoff/assets.doubles.v1.json'
if doubles_path.exists():
    asset_count += len(AssetManifest.model_validate_json(doubles_path.read_text(encoding='utf-8')).assets)
runtime_catalog = root/'models/handoff/models.runtime-001.v1.json'
runtime_statuses = None
if runtime_catalog.exists():
    snapshot = json.loads(runtime_catalog.read_text(encoding='utf-8'))
    for model in snapshot['models']:
        ModelManifest.model_validate(model)
    runtime_statuses = {m['model_id']:m['status'] for m in snapshot['models']}
count = 0
for request_file in (root/'models/handoff/requests').glob('*.json'):
    request = JobRequest.model_validate_json(request_file.read_text(encoding='utf-8'))
    local.validate_request(json.loads(request_file.read_text(encoding='utf-8')),root)
    result_file = root/request.output_dir/'result.json'
    if result_file.exists():
        result = JobResult.model_validate_json(result_file.read_text(encoding='utf-8'))
        validate_job_result(request,result,{'succeeded':0,'failed':1,'blocked':2,'cancelled':130}[result.status])
        count += 1
print(json.dumps({'shared_fixture':'passed','model_manifests':6,'real_assets':asset_count,'actual_results_checked':count,
                  'wsl_snapshot_statuses':runtime_statuses}))
