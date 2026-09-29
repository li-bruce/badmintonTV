"""Bounded GNU du preflight for the separate VL runtime; no GPU or writes."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def measure(path, exclude=None):
    if not Path(path).exists():
        return 0
    argv = ['/usr/bin/du','-sb']
    if exclude:
        argv += ['--exclude='+exclude]
    argv.append(str(path))
    output = subprocess.run(argv,check=True,capture_output=True,text=True,timeout=45).stdout
    return int(output.split('\t',1)[0])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--models-peak',type=int,default=0)
    parser.add_argument('--shared-peak',type=int,default=0)
    args=parser.parse_args()
    if min(args.models_peak,args.shared_peak)<0:
        raise ValueError('nonnegative finite reservations required')
    root=Path('/mnt/d/video')
    usage={'models_runtime':measure(root/'runtime/models'),
           'shared_disk':measure(root/'runtime/shared'),
           'native_base_and_pkgs':measure('/home/ubuntu/miniforge3','/home/ubuntu/miniforge3/envs')}
    shared=usage['shared_disk']+usage['native_base_and_pkgs']
    total=usage['models_runtime']+shared+20_000_000_000
    free=shutil.disk_usage(root).free
    checks={'models_35GB':usage['models_runtime']+args.models_peak<=35_000_000_000,
            'shared_15GB':shared+args.shared_peak<=15_000_000_000,
            'runtime_70GB':total+args.models_peak+args.shared_peak<=70_000_000_000,
            'free_5GB_margin':free>=args.models_peak+args.shared_peak+5_000_000_000}
    print(json.dumps({'usage_bytes':usage,'other_runtime_reserved_bytes':20_000_000_000,
                      'additional_models_peak_bytes':args.models_peak,'additional_shared_peak_bytes':args.shared_peak,
                      'free_bytes':free,'checks':checks,'passed':all(checks.values())}),flush=True)
    if not all(checks.values()):
        raise SystemExit('runtime capacity preflight refused')


if __name__=='__main__':
    main()
