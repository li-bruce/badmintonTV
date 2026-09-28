"""Read-only decimal-byte storage accounting; no cleanup of existing files."""
import argparse
import json
import shutil
from pathlib import Path


def size(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink()) if path.exists() else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/mnt/d/video')
    parser.add_argument('--reserve-runtime', type=int, default=0)
    parser.add_argument('--reserve-models', type=int, default=0)
    args = parser.parse_args()
    root = Path(args.root)
    usage = {name: size(root / name) for name in ('data', 'models', 'runtime', 'platform', 'render')}
    usage['runtime_shared'] = size(root / 'runtime/shared')
    usage['runtime_models'] = size(root / 'runtime/models')
    free = shutil.disk_usage(root).free
    checks = [usage['models'] + args.reserve_models <= 180_000_000_000,
              usage['runtime_models'] + args.reserve_runtime <= 35_000_000_000,
              usage['runtime_shared'] <= 15_000_000_000,
              usage['runtime'] + args.reserve_runtime <= 70_000_000_000,
              sum(usage[k] for k in ('data','models','runtime','platform','render')) + args.reserve_models + args.reserve_runtime <= 700_000_000_000,
              free >= args.reserve_runtime + args.reserve_models + 5_000_000_000]
    print(json.dumps({'usage_bytes': usage, 'free_bytes': free, 'checks_passed': all(checks)}))
    if not all(checks):
        raise SystemExit('capacity preflight failed')


if __name__ == '__main__':
    main()
