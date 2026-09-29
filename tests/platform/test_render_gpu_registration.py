"""Administrator-only render resource selection; no hardware is used."""
import json
import sys
from pathlib import Path

import pytest

from packages.runtime import Queue
from packages.runtime.gpu import GPUCoordinator
from packages.runtime.worker import WorkerContext, run_once


@pytest.mark.parametrize('backend',['nvenc','auto'])
def test_admin_gpu_backend_cannot_be_disabled_by_payload(tmp_path,monkeypatch,backend):
    monkeypatch.setenv('BTV_RENDER_BACKEND',backend)
    queue=Queue(tmp_path/'runtime.sqlite3')
    queue.enqueue('render',{'model_id':'render-nvenc','gpu_required':False,'parameters':{},'assets':[]})
    result=run_once(queue,tmp_path)
    assert result['status']=='blocked'
    assert result['error']['code']=='GPU_LEASE_REQUIRED'


def test_gpu_render_requires_trusted_resource_identity(tmp_path,monkeypatch):
    monkeypatch.setenv('BTV_RENDER_BACKEND','nvenc')
    queue=Queue(tmp_path/'runtime.sqlite3')
    queue.enqueue('render',{'gpu_required':False,'parameters':{},'assets':[]})
    result=run_once(queue,tmp_path)
    assert result['error']['code']=='GPU_RESOURCE_MISMATCH'


def test_render_child_gets_only_current_native_lease(tmp_path,monkeypatch):
    monkeypatch.setenv('BTV_RENDER_BACKEND','auto')
    monkeypatch.setenv('BTV_RENDER_COMMAND_JSON',json.dumps([sys.executable,'-m','packages.render']))
    monkeypatch.setenv('BTV_GPU_LEASE_ID','stale-inherited-id')
    queue=Queue(tmp_path/'runtime.sqlite3')
    gpu=GPUCoordinator(queue.db_path)
    gpu.grant_window('fixture',['render-nvenc'],60,coordination_note='CPU-only registration test')
    def execute(self,argv,*args,extra_env=None,**kwargs):
        lease=gpu.get(extra_env['BTV_GPU_LEASE_ID'])
        assert extra_env['BTV_RUNTIME_DB']==queue.db_path
        assert extra_env['BTV_RENDER_BACKEND']=='auto'
        assert lease['status']=='active' and lease['model_id']=='render-nvenc'
        assert lease['job_id']==self.job['job_id'] and lease['attempt']==self.job['attempt']
        request=json.loads(Path(argv[argv.index('--request')+1]).read_text())
        Path(argv[argv.index('--result')+1]).write_text(json.dumps({'schema_version':'1.0','job_id':request['job_id'],'attempt_id':request['attempt_id'],'status':'succeeded','artifacts':[],'events':[],'error':None}))
        return 0,'',''
    monkeypatch.setattr(WorkerContext,'execute',execute)
    queue.enqueue('render',{'model_id':'render-nvenc','gpu_required':False,'parameters':{},'assets':[]})
    assert run_once(queue,tmp_path)['status']=='succeeded'
    assert gpu.status()['lease'] is None


def test_changed_admin_backend_requires_new_job(tmp_path,monkeypatch):
    monkeypatch.setenv('BTV_RENDER_BACKEND','nvenc')
    queue=Queue(tmp_path/'runtime.sqlite3')
    queue.enqueue('render',{'model_id':'render-nvenc','render_backend':'cpu','parameters':{},'assets':[]})
    assert run_once(queue,tmp_path)['error']['code']=='RENDER_CONFIG_CHANGED'
