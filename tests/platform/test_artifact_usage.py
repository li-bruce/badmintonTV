"""Artifact-serving usage checks with actual synthetic output hashes."""
import hashlib
import json

import pytest

from test_api import setup
from packages.contracts import TRAINING_REGISTRY_PATH


def completed_output(setup, *, artifact_changes=None, result_changes=None, relative=None):
    client,app,source,_,root=setup
    job=app.state.queue.enqueue('render',{'assets':[source],'parameters':{'research_preview':True}})
    assert app.state.queue.claim('artifact-fixture')['job_id']==job['job_id']
    relative=relative or f"render/jobs/{job['job_id']}/attempt-1/output.mp4"
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
    raw=b'synthetic output bytes, distinct from the input asset'
    path.write_bytes(raw)
    artifact={'artifact_id':'output','kind':'video','relative_path':relative,'sha256':hashlib.sha256(raw).hexdigest(),
              'size_bytes':len(raw),'created_at':'2026-09-29T00:00:00Z','producer':'synthetic-render',**(artifact_changes or {})}
    result={'schema_version':'1.0','job_id':job['job_id'],'attempt_id':'attempt-1','status':'succeeded',
            'artifacts':[artifact],'events':[],'error':None,**(result_changes or {})}
    app.state.queue.finish(job['job_id'],'artifact-fixture','succeeded',result=result)
    return f"/api/v1/jobs/{job['job_id']}/artifacts/output",artifact,raw


def registry(root,digest=None):
    path=root/TRAINING_REGISTRY_PATH;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'schema_version':'1.0','assets':[] if digest is None else [{
        'asset_id':'registered-training-output','relative_path':'data/training/original.mp4',
        'sha256':digest,'usage_scope':'training_only'}]}),encoding='utf-8')


def test_existing_general_output_is_blocked_when_its_actual_sha_is_later_registered(setup):
    client,_,source,_,root=setup
    url,artifact,raw=completed_output(setup)
    before=client.get(url,headers={'Range':'bytes=0-8'})
    assert before.status_code==206 and before.content==raw[:9]
    assert before.headers['cache-control']=='no-store'
    assert artifact['sha256']!=source['sha256']
    registry(root,hashlib.sha256(raw).hexdigest())
    after=client.get(url,headers={'Range':'bytes=0-8'})
    assert after.status_code==422 and 'TRAINING_ONLY' in after.text,after.content
    assert after.content!=raw[:9]


@pytest.mark.parametrize('declaration',[
    {'usage_scope':'training_only','producer':{'usage_scope':'general'}},
    {'provenance':{'usage_scope':'training_only'}},
    {'usage_scope':'general','producer':{'usage_scope':'training_only'}},
    {'producer':{'usage_scope':'general','provenance':{'usage_scope':'training_only'}}},
])
def test_artifact_and_producer_restrictions_cannot_be_overwritten_by_general(setup,declaration):
    client,*_=setup
    url,_,_=completed_output(setup,artifact_changes=declaration)
    response=client.get(url)
    assert response.status_code==422 and 'TRAINING_ONLY' in response.text,response.text


@pytest.mark.parametrize('result_changes',[
    {'usage_scope':'training_only'},
    {'provenance':{'usage_scope':'training_only'}},
    {'producer':{'usage_scope':'training_only'}},
    {'preview':{'usage_scope':'training_only'}},
    {'frame':{'usage_scope':'training_only'}},
])
def test_internal_result_usage_applies_to_its_artifacts(setup,result_changes):
    client,*_=setup
    url,_,_=completed_output(setup,artifact_changes={'usage_scope':'general'},result_changes=result_changes)
    response=client.get(url)
    assert response.status_code==422 and 'TRAINING_ONLY' in response.text,response.text


@pytest.mark.parametrize('location',['artifact_provenance','producer','producer_provenance','result','frame'])
def test_artifact_or_result_source_lineage_is_checked_against_registry(setup,location):
    client,_,_,_,root=setup
    training_sha='f'*64; registry(root,training_sha)
    reference={'source_asset_id':'registered-training-output','source_sha256':training_sha}
    changes,result={},{}
    if location=='artifact_provenance': changes={'provenance':reference}
    elif location=='producer': changes={'producer':reference}
    elif location=='producer_provenance': changes={'producer':{'provenance':reference}}
    elif location=='result': result=reference
    else: result={'frame':reference}
    url,_,_=completed_output(setup,artifact_changes=changes,result_changes=result)
    response=client.get(url)
    assert response.status_code==422 and 'TRAINING_ONLY' in response.text,response.text


def test_artifact_logical_training_path_is_rejected(setup):
    client,_,_,_,root=setup
    registry(root)
    url,_,_=completed_output(setup,relative='data/training/synthetic-output.mp4')
    response=client.get(url)
    assert response.status_code==422 and 'TRAINING_ONLY' in response.text,response.text
