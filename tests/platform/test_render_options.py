"""Saved export settings and administrator catalog/commands, without rendering."""
import copy
import json

import pytest
from fastapi.testclient import TestClient
from test_api import setup
from apps.platform.main import create_app


def timeline(client,fps=30):
    result=client.post('/api/v1/timelines',json={'schema_version':'1.0','timeline_id':'settings-timeline','title':'Fixture',
        'segments':[{'segment_id':'clip','asset_id':'asset-a','in_ms':0,'out_ms':1000}],
        'output':{'width':1080,'height':1920,'fps':fps,'video_codec':'h264','audio_codec':'aac'}})
    assert result.status_code==200,result.text
    return result.json()


def test_options_persist_cas_and_trusted_render_payload(setup,monkeypatch):
    client,app,_,_,root=setup
    timeline(client,60)
    path='/api/v1/timelines/settings-timeline/render-options'
    initial=client.get(path).json()
    assert initial['revision']==0 and initial['options']['export_preset']=='portrait_1080p60'
    options={**initial['options'],'safe_area':{'x':.1,'y':.1,'width':.7,'height':.7},'platform_profile':'youtube_shorts'}
    assert client.put(path,json={'expected_revision':0,'options':options}).json()['revision']==1
    assert client.put(path,json={'expected_revision':0,'options':options}).status_code==409
    fresh=TestClient(create_app(root,root/'platform/platform.sqlite3'))
    assert fresh.get(path).json()['options']==options
    monkeypatch.setenv('BTV_RENDER_BACKEND','auto')
    response=fresh.post('/api/v1/timelines/settings-timeline/render',json={'research_preview':True,'gpu_required':False,'model_id':'forged','render_backend':'cpu','parameters':{'export_preset':'forged'}})
    assert response.status_code==202,response.text
    payload=response.json()['payload']
    assert payload['gpu_required'] is True and payload['model_id']=='render-nvenc' and payload['render_backend']=='auto'
    assert payload['render_options_revision']==1
    assert all(payload['parameters'][key]==value for key,value in options.items())


@pytest.mark.parametrize('change',[{'export_preset':'portrait_1080p60'},{'safe_area':{'x':True,'y':0,'width':1,'height':1}},
    {'safe_area':{'x':.2,'y':0,'width':1,'height':1}},{'safe_area':{'x':0,'y':0,'width':0,'height':1}},
    {'platform_profile':'unregistered-platform'},{'backend':'nvenc'}])
def test_invalid_settings_do_not_persist_or_enqueue(setup,change):
    client,app,*_=setup;timeline(client)
    path='/api/v1/timelines/settings-timeline/render-options'
    options={**client.get(path).json()['options'],**change}
    response=client.put(path,json={'expected_revision':0,'options':options})
    assert response.status_code in (409,422),response.text
    assert client.get(path).json()['revision']==0 and app.state.queue.list()==[]


def test_legacy_fps_is_preserved_without_explicit_preset(setup):
    client,*_=setup;timeline(client,25)
    assert client.get('/api/v1/timelines/settings-timeline/render-options').json()['options']['export_preset'] is None
    result=client.post('/api/v1/timelines/settings-timeline/render',json={'research_preview':True}).json()['payload']['parameters']
    assert 'export_preset' not in result and result['timeline']['output']['fps']==25


@pytest.mark.parametrize('width,height,fps',[(1280,720,30),(720,1280,60),(1080,1080,30)])
def test_default_preset_does_not_change_legacy_dimensions(setup,width,height,fps):
    client,*_=setup
    body=timeline(client,fps)
    body['output'].update(width=width,height=height)
    assert client.post('/api/v1/timelines',json=body).status_code==200
    assert client.get('/api/v1/timelines/settings-timeline/render-options').json()['options']['export_preset'] is None
    response=client.post('/api/v1/timelines/settings-timeline/render',json={'research_preview':True})
    assert response.status_code==202,response.text
    parameters=response.json()['payload']['parameters']
    assert 'export_preset' not in parameters
    assert parameters['timeline']['output']==body['output']


def test_render_parameters_and_revision_use_one_snapshot_during_concurrent_save(setup,monkeypatch):
    client,app,*_=setup;timeline(client)
    path='/api/v1/timelines/settings-timeline/render-options'
    initial=client.get(path).json()['options']
    assert client.put(path,json={'expected_revision':0,'options':initial}).status_code==200
    changed={**initial,'safe_area':{'x':.1,'y':.1,'width':.7,'height':.7}}
    original=app.state.store.get; raced=[]
    def racing_get(kind,identifier):
        snapshot=original(kind,identifier)
        if kind=='render_options' and identifier=='settings-timeline' and not raced:
            raced.append(True)
            app.state.store.save_render_options(identifier,changed,1)
        return snapshot
    monkeypatch.setattr(app.state.store,'get',racing_get)
    response=client.post('/api/v1/timelines/settings-timeline/render',json={'research_preview':True})
    assert response.status_code==202,response.text
    payload=response.json()['payload']
    assert payload['render_options_revision']==1
    assert payload['parameters']['safe_area']==initial['safe_area']
    assert original('render_options','settings-timeline')['revision']==2
    assert original('render_options','settings-timeline')['options']==changed


def test_current_admin_catalog_overrides_stale_import_and_keeps_uninstalled(setup,monkeypatch,tmp_path):
    client,*_=setup
    card={'schema_version':'1.0','model_id':'tracknetv3-reuse','version':'0.1.0','display_name':'Fixture component',
          'capabilities':['tracking'],'status':'ready','resource_requirements':{'gpu_required':True}}
    catalog=tmp_path/'catalog.json';catalog.write_text(json.dumps({'schema_version':'1.0','models':[card]}))
    monkeypatch.setenv('BTV_MODEL_CATALOG_PATH',str(catalog))
    monkeypatch.delenv('BTV_MODEL_COMMANDS_JSON',raising=False)
    assert client.get('/api/v1/models').json()[0]['status']=='unavailable'
    monkeypatch.setenv('BTV_MODEL_COMMANDS_JSON',json.dumps({'tracknetv3-reuse':['python','-m','packages.runtime.wsl_bridge']}))
    assert client.get('/api/v1/models').json()[0]['status']=='ready'
    response=client.post('/api/v1/models/tracknetv3-reuse/run',json={'asset_ids':['asset-a']})
    assert response.status_code==202 and response.json()['payload']['gpu_required'] is True
    card.update(status='not_installed',reason='Dependency installation incomplete')
    catalog.write_text(json.dumps({'schema_version':'1.0','models':[card]}))
    assert client.get('/api/v1/models/tracknetv3-reuse/health').json()['status']=='not_installed'
