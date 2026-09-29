"""Explicit one-job Windows worker / WSL / GPU-ledger experiment.

The caller must already coordinate the short GPU window with other modules.
Use the existing platform environment; no SQL or direct GPU process launching.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--payload',required=True,help='Reviewed model payload JSON')
    p.add_argument('--repo',default=str(Path(__file__).resolve().parents[2]))
    p.add_argument('--runtime-repo',required=True,help='Read-only platform/contracts checkout')
    p.add_argument('--env-prefix',default='/mnt/d/video/runtime/models/env')
    p.add_argument('--window-seconds',type=int,default=600)
    p.add_argument('--coordination-note',required=True)
    args=p.parse_args()
    if os.name!='nt': raise SystemExit('Run in native Windows platform environment')
    if not 30<=args.window_seconds<=1800: raise ValueError('window must be 30..1800 seconds')
    repo=Path(args.repo).resolve(); runtime=Path(args.runtime_repo).resolve()
    sys.path.insert(0,str(runtime))
    from packages.runtime.queue import Queue
    from packages.runtime.gpu import GPUCoordinator
    from packages.runtime.worker import run_once
    root=Path('D:/video'); queue=Queue(root/'platform/runtime.sqlite3')
    payload=json.loads(Path(args.payload).read_text(encoding='utf-8'))
    allowed={'tracknetv3-reuse','qwen3-vl-embedding-2b','torchvision-continuous-pose','bst-cg-ap-reuse','yolo11n-pose-bytetrack'}
    mid=payload.get('model_id')
    if mid not in allowed or payload.get('model_version')!='0.1.0' or payload.get('gpu_required') is not True:
        raise ValueError('Expected explicitly registered research model/version/GPU payload')
    if queue.list(status='queued') or queue.list(status='running'):
        raise RuntimeError('Shared queue is busy; no job enqueued/window granted')
    gpu=GPUCoordinator(queue.db_path)
    before=gpu.status()
    if before['lease'] or before['active_window']:
        raise RuntimeError('GPU is assigned; no job enqueued/window granted')
    if (root/'models/.writer-reservation.json').exists():
        raise RuntimeError('Models writer occupied; wait before granting GPU window')
    command=[sys.executable,'-m','packages.runtime.wsl_bridge','--distribution','Ubuntu',
             '--env-prefix',args.env_prefix,'--repo',str(repo)]
    os.environ['BTV_MODEL_COMMANDS_JSON']=json.dumps({mid:command})
    # Native bridge resolves shared contracts from the selected runtime checkout;
    # its Linux worker changes to the models checkout for adapter execution.
    os.environ['PYTHONPATH']=str(runtime)
    # -m checks the current directory before PYTHONPATH. Pin the native bridge
    # checkout as well; the explicit --repo still selects only the ML checkout.
    os.chdir(runtime)
    window='models-reuse-'+uuid.uuid4().hex
    gpu.grant_window(window,[mid],args.window_seconds,granted_by='models-coordinated-experiment',
                     coordination_note=args.coordination_note)
    try:
        job=queue.enqueue('model',payload,max_attempts=1)
        print(json.dumps({'enqueued':job['job_id'],'window_id':window,'model_id':mid}),flush=True)
        done=run_once(queue,root,worker_id='models-reuse-'+uuid.uuid4().hex,lease_seconds=120)
        if not done or done['job_id']!=job['job_id']:
            raise RuntimeError('Worker claimed another job; inspect shared queue')
        print(json.dumps({'job_id':done['job_id'],'status':done['status'],'error':done['error'],
                          'result':done['result']},ensure_ascii=False),flush=True)
        exit_code={'succeeded':0,'failed':1,'blocked':2,'cancelled':130}.get(done['status'],1)
    finally:
        state=gpu.status()
        if state['lease']:
            print(json.dumps({'gpu_cleanup':'lease retained; inspect matching bridge stop evidence',
                              'state':state}),flush=True)
        else:
            gpu.revoke_window(window,reason='Models one-job experiment ended and trusted worker released lease')
            print(json.dumps({'gpu_after':gpu.status()}),flush=True)
    return exit_code


if __name__=='__main__': raise SystemExit(main())
