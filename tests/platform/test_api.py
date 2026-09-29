import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault('BTV_STORAGE_ROOT',tempfile.mkdtemp(prefix='btv-import-test-'))
from apps.platform.main import create_app


@pytest.fixture
def setup(tmp_path):
    root=tmp_path/'video'; (root/'data').mkdir(parents=True)
    raw=b'contract-test-media-not-real-video'; (root/'data/test.mp4').write_bytes(raw)
    app=create_app(root,root/'platform/platform.sqlite3')
    client=TestClient(app)
    library=client.post('/api/v1/libraries',json={'name':'测试库'}).json()
    asset={'schema_version':'1.0','asset_id':'asset-a','relative_path':'data/test.mp4','sha256':hashlib.sha256(raw).hexdigest(),
        'size_bytes':len(raw),'duration_ms':10000,'width':1280,'height':720,'fps_num':30,'fps_den':1,'time_base':'1/90000',
        'title':'合同测试，不是真实视频','match_id':'match-a','source_type':'synthetic','players':[], 'split':'test',
        'rights':{'status':'owned','allowed_uses':['test'],'evidence':'unit test bytes'}}
    response=client.post('/api/v1/assets/import',json={'library_id':library['library_id'],'manifest':{'schema_version':'1.0','assets':[asset]}})
    assert response.status_code==200,response.text
    return client,app,asset,library,root


def event(id='e1',start=1000,end=1500,player='a',rally='r1',labels=None):
    return {'schema_version':'1.0','event_id':id,'asset_id':'asset-a','match_id':'match-a','rally_id':rally,'player_id':player,
            'kind':'stroke','start_ms':start,'end_ms':end,'labels':labels or {'stroke':'net_shot','hand_technique':'unknown'},
            'visibility':'partial','review_status':'confirmed','revision':1,'provenance':{'source':'manual'},'evidence':[]}


def save(c,e,expected=0):
    return c.post('/api/v1/events',json={'event':e,'expected_revision':expected,'reviewer':'tester'})


def query():
    return {'schema_version':'1.0','query_id':'q1','text':'网前，随后杀球','player_id':'a','scope':{},
        'steps':[{'step_id':'s1','kind':'stroke','labels':{'stroke':'net_shot'}},{'step_id':'s2','kind':'stroke','labels':{'stroke':'smash'}}],
        'relations':[{'from_step':'s1','to_step':'s2','relation':'before','same_player':True,'same_rally':True,'max_gap_ms':5000}],
        'include_uncertain':False}


def test_manual_sequence_allows_opponent_and_persists(setup):
    c,app,a,library,root=setup
    for e in [event(),event('opponent',2000,2400,'b'),event('e3',3000,3500,labels={'stroke':'smash'})]:
        assert save(c,e).status_code==200
    result=c.post('/api/v1/queries/search',json=query()).json()
    assert len(result['candidates'])==1
    candidate=result['candidates'][0]
    assert candidate['event_ids']==['e1','e3']
    # A fresh app opens the same native database: annotations survive process replacement.
    restarted=TestClient(create_app(root,root/'platform/platform.sqlite3'))
    assert len(restarted.get('/api/v1/events').json())==3
    assert restarted.post('/api/v1/queries/search',json=query()).json()['candidates'][0]['event_ids']==['e1','e3']


@pytest.mark.parametrize('player,rally',[('b','r1'),('a','r2'),('a',None),(None,'r1')])
def test_sequence_does_not_cross_player_rally_or_unknown(setup,player,rally):
    c,*_=setup
    save(c,event());save(c,event('e2',3000,3500,player,rally,{'stroke':'smash'}))
    assert c.post('/api/v1/queries/search',json=query()).json()['candidates']==[]


def test_unknown_is_not_negative_or_confirmed_match(setup):
    c,*_=setup;save(c,event())
    q=query();q['steps']=[{'step_id':'s1','kind':'stroke','labels':{'hand_technique':'net_zhan_cuo'}}];q['relations']=[]
    assert c.post('/api/v1/queries/search',json=q).json()['candidates']==[]
    q['include_uncertain']=True
    candidate=c.post('/api/v1/queries/search',json=q).json()['candidates'][0]
    assert candidate['missing_conditions'] and candidate['uncertainty_reasons'] and not candidate['matched_conditions']


def test_revision_conflict_model_protection_and_history(setup):
    c,app,*_=setup;e=event()
    assert save(c,e).status_code==200
    assert save(c,e).status_code==409
    e.update(revision=2,labels={'stroke':'smash'})
    assert save(c,e,1).json()['revision']==2
    assert len(c.get('/api/v1/events/e1/revisions').json())==2
    e.update(revision=3,provenance={'source':'model'})
    # Source provenance describes generation, while this route is an explicit edit.
    assert save(c,e,2).status_code==200
    queued=app.state.queue.enqueue('model',{})
    claimed=app.state.queue.claim('test-worker')
    app.state.queue.finish(queued['job_id'],'test-worker','succeeded',result={'events':[e]})
    assert c.post('/api/v1/jobs/'+queued['job_id']+'/apply').status_code==409


def test_confirmed_candidate_required_for_timeline(setup):
    c,*_=setup;save(c,event());save(c,event('e2',3000,3500,labels={'stroke':'smash'}))
    candidate=c.post('/api/v1/queries/search',json=query()).json()['candidates'][0]
    body={'candidate_ids':[candidate['candidate_id']]}
    assert c.post('/api/v1/timelines/from-candidates',json=body).status_code==409
    c.post('/api/v1/candidates/'+candidate['candidate_id']+'/confirm',json={'review_status':'confirmed','reviewer':'tester'})
    timeline=c.post('/api/v1/timelines/from-candidates',json=body).json()
    assert timeline['segments'][0]['in_ms']==0
    response=c.post('/api/v1/timelines/'+timeline['timeline_id']+'/render',json={})
    assert response.status_code==202,response.text
    assert response.json()['status']=='queued'
    editorial=response.json()['payload']['parameters']['segment_options'][timeline['segments'][0]['segment_id']]['editorial_review']
    assert editorial['reviewer_type']=='human'
    assert editorial['event_revisions']=={'e1':1,'e2':1}
    timeline['segments'][0]['in_ms']=100
    assert c.post('/api/v1/timelines',json=timeline).status_code==200
    assert c.post('/api/v1/timelines/'+timeline['timeline_id']+'/render',json={}).status_code==409
    assert c.post('/api/v1/timelines',json={'timeline':timeline,'reviewer':'agent','reviewer_type':'agent'}).status_code==200
    assert c.post('/api/v1/timelines/'+timeline['timeline_id']+'/render',json={}).status_code==409
    assert c.post('/api/v1/timelines',json={'timeline':timeline,'reviewer':'tester','reviewer_type':'human'}).status_code==200
    assert c.post('/api/v1/timelines/'+timeline['timeline_id']+'/render',json={}).status_code==202
    changed={**event(), 'labels':{'stroke':'smash'}}
    assert save(c,changed,1).status_code==200
    assert c.post('/api/v1/timelines/'+timeline['timeline_id']+'/render',json={}).status_code==409


def test_probe_apply_large_source_uses_worker_digest_without_rehash(setup,monkeypatch):
    c,app,a,l,root=setup
    raw=b'x'*8_000_001
    (root/'data/large.mp4').write_bytes(raw)
    large={**a,'asset_id':'large','relative_path':'data/large.mp4','size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    job=app.state.queue.enqueue('probe',{'library_id':l['library_id'],'relative_path':large['relative_path']})
    app.state.queue.claim('worker')
    app.state.queue.finish(job['job_id'],'worker','succeeded',result={'asset':large,'source_identities':{'large':app.state.store._file_identity(root/'data/large.mp4')}})
    def rehash_forbidden(*args,**kwargs):
        raise AssertionError('probe apply must not hash large media in web process')
    monkeypatch.setattr(hashlib,'file_digest',rehash_forbidden)
    response=c.post('/api/v1/jobs/'+job['job_id']+'/apply')
    assert response.status_code==200,response.text
    assert response.json()['imported'][0]['asset']['asset_id']=='large'
    assert len(app.state.queue.list())==1
    assert len(c.get('/api/v1/assets').json())==2


def test_global_top_candidates_keep_late_exact_match(setup):
    from apps.platform.retrieval import search
    c,app,a,*_=setup
    events=[{**event('unknown-'+str(i),i,i+1,labels={'stroke':'unknown'}),'visibility':'insufficient','review_status':'unreviewed'} for i in range(500)]
    events.append({**event('late-exact',600,601),'reviewer_type':'human'})
    q=query();q['steps']=q['steps'][:1];q['relations']=[];q['include_uncertain']=True
    results=search(q,events,[a])
    assert len(results)==500
    assert results[0]['event_ids']==['late-exact']
    assert results[0]['rank_score']==1


def test_asset_dedup_and_unsafe_paths(setup):
    c,app,a,l,root=setup
    response=c.post('/api/v1/assets/import',json={'library_id':l['library_id'],'manifest':{'assets':[a]}})
    assert response.json()['imported'][0]['duplicate']
    upper={**a,'asset_id':'same-uppercase','sha256':a['sha256'].upper()}
    assert c.post('/api/v1/assets/import',json={'library_id':l['library_id'],'manifest':{'assets':[upper]}}).json()['imported'][0]['duplicate']
    assert len(c.get('/api/v1/assets').json())==1
    spoof={**a,'asset_id':'spoof','relative_path':'data/spoof.mp4'}
    (root/'data/spoof.mp4').write_bytes(b'x'*a['size_bytes'])
    assert c.post('/api/v1/assets/import',json={'library_id':l['library_id'],'manifest':{'assets':[spoof]}}).status_code==422
    a['relative_path']='../secrets.txt'
    assert c.post('/api/v1/assets/import',json={'library_id':l['library_id'],'manifest':{'assets':[a]}}).status_code==422


def test_secret_mask_and_cross_origin(setup,monkeypatch):
    c,*_=setup
    monkeypatch.setenv('BTV_TEST_SECRET','do-not-leak-123')
    r=c.put('/api/v1/settings/llm',json={'base_url':'http://127.0.0.1:1/v1','model':'test','key_env':'BTV_TEST_SECRET','timeout':1})
    assert r.status_code==200 and 'do-not-leak' not in r.text and r.json()['key_present']
    assert 'do-not-leak' not in c.post('/api/v1/settings/llm/test').text
    assert c.put('/api/v1/settings/llm',json={'api_key':'secret'}).status_code==422
    assert c.post('/api/v1/libraries',json={'name':'bad'},headers={'Origin':'https://evil.example'}).status_code==403


def test_invalid_event_time_and_unknown_query(setup):
    c,*_=setup
    assert save(c,event(end=10001)).status_code==422
    assert c.post('/api/v1/queries/parse',json={'text':'未实现动作请不要命中全部'}).status_code==422
    assert c.post('/api/v1/queries/parse',json={'text':'不要网前击球，只要杀球'}).status_code==422
    assert c.post('/api/v1/queries/parse',json={'text':'后退起跳杀球'}).status_code==422
    assert c.get('/api/v1/health').json()['torch_loaded'] is False
    gpu=c.get('/api/v1/resources/gpu').json()
    assert gpu['code']=='GPU_LEASE_REQUIRED' and not gpu['available']
    assert c.get('/api/v1/models').json()[0]['status']=='not_installed'
    assert c.get('/').status_code==200


def test_label_studio_roundtrip_and_idempotency(setup):
    c,*_=setup
    fm={'mapping_id':'test-map','source_duration_ms':10000,'frames':[{'ls_frame':1,'source_start_ms':0,'source_end_ms':1000},{'ls_frame':2,'source_start_ms':1000,'source_end_ms':10000}]}
    task=c.post('/api/v1/annotation/label-studio/task',json={'asset_id':'asset-a','frame_map':fm}).json()
    task['id']=11
    task['annotations']=[{'id':22,'result':[{'id':'region1','from_name':'events','to_name':'video','type':'timelinelabels','value':{'ranges':[{'start':1,'end':1}],'timelinelabels':['stroke.net_shot']}}]}]
    body={'export':[task],'reviewer':'tester','tool_version':'1.23.1'}
    response=c.post('/api/v1/annotation/label-studio/import',json=body)
    assert response.status_code==200,response.text
    e=response.json()['events'][0]
    assert (e['start_ms'],e['end_ms'],e['review_status'])==(0,1000,'unreviewed')
    assert c.post('/api/v1/annotation/label-studio/import',json=body).json()['events']==[]
