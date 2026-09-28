"""Read-only decimal-byte storage accounting; no cleanup of existing files."""
import argparse
import json
import os
import shutil
import stat
from pathlib import Path


DEFAULT_NATIVE_BASE = '/home/ubuntu/miniforge3'
OWNERS = ('data', 'models', 'runtime', 'platform', 'render')


def _absolute(path):
    # Normalize without following a symlink selected as the native base.
    return Path(os.path.abspath(path))


def _linked(metadata):
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    )


def _walk_error(error):
    # An unreadable tree is not evidence of zero usage.
    raise error


def size(path, *, exclude=()):
    """Count regular-file bytes without visiting excluded or linked subtrees."""
    path = _absolute(path)
    excluded = {_absolute(item) for item in exclude}
    if path in excluded or not path.exists():
        return 0
    metadata = path.lstat()
    if _linked(metadata):
        return 0
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError('capacity accounting root must be a directory')
    total = 0
    for directory, dirs, files in os.walk(path, topdown=True, followlinks=False, onerror=_walk_error):
        parent = Path(directory)
        dirs[:] = [name for name in dirs
                   if parent / name not in excluded and not _linked((parent / name).lstat())]
        for name in files:
            item = parent / name
            if item in excluded:
                continue
            entry = item.lstat()
            if not _linked(entry) and stat.S_ISREG(entry.st_mode):
                total += entry.st_size
    return total


def native_base_usage(path):
    """Account for reused base plus pkgs once; never scan the old envs tree."""
    path = _absolute(path)
    report = {'path': str(path), 'reused': False, 'status': 'not_found', 'size_bytes': 0,
              'excluded_subtree': 'envs', 'free_bytes_reference': None,
              'free_space_policy': 'read_only_reference_not_a_write_reservation'}
    if path.is_symlink() or (path.exists() and _linked(path.lstat())):
        report['status'] = 'symlink_excluded'
        return report
    if not path.exists():
        return report
    report.update(reused=True, status='counted', size_bytes=size(path, exclude=(path / 'envs',)))
    try:
        report['free_bytes_reference'] = shutil.disk_usage(path).free
    except OSError:
        # Usage still counts. Native free space is informational because new
        # package caches/environments are directed to the controlled root.
        report['free_space_note'] = 'native free-space reference unavailable'
    return report


def budget_report(root, native_base=DEFAULT_NATIVE_BASE, reserve_runtime=0, reserve_models=0):
    if type(reserve_runtime) is not int or type(reserve_models) is not int or min(reserve_runtime, reserve_models) < 0:
        raise ValueError('reservation sizes must be non-negative integers')
    root, native_path = _absolute(root), _absolute(native_base)
    native = native_base_usage(native_path)
    # Excluding the native tree here also avoids double counting if an explicit
    # --native-base is already inside a controlled owner directory.
    disk_usage = {name: size(root / name, exclude=(native_path,)) for name in OWNERS}
    disk_usage['runtime_shared'] = size(root / 'runtime/shared', exclude=(native_path,))
    disk_usage['runtime_models'] = size(root / 'runtime/models', exclude=(native_path,))
    usage = dict(disk_usage)
    usage['runtime_shared'] += native['size_bytes']
    usage['runtime'] += native['size_bytes']
    project_total = sum(usage[name] for name in OWNERS)
    free = shutil.disk_usage(root).free
    checks = {
        'models_quota': usage['models'] + reserve_models <= 180_000_000_000,
        'runtime_models_quota': usage['runtime_models'] + reserve_runtime <= 35_000_000_000,
        'runtime_shared_quota': usage['runtime_shared'] <= 15_000_000_000,
        'runtime_total_quota': usage['runtime'] + reserve_runtime <= 70_000_000_000,
        'project_total_quota': project_total + reserve_models + reserve_runtime <= 700_000_000_000,
        'storage_root_free_space': free >= reserve_runtime + reserve_models + 5_000_000_000,
    }
    return {'usage_bytes': usage, 'disk_usage_bytes': disk_usage, 'native_base': native,
            'project_total_bytes': project_total, 'free_bytes': free, 'checks': checks,
            'checks_passed': all(checks.values())}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/mnt/d/video')
    parser.add_argument('--native-base', default=DEFAULT_NATIVE_BASE,
                        help='Existing Miniforge root; count base/pkgs, exclude envs and symlinks')
    parser.add_argument('--reserve-runtime', type=int, default=0)
    parser.add_argument('--reserve-models', type=int, default=0)
    args = parser.parse_args(argv)
    if args.reserve_runtime < 0 or args.reserve_models < 0:
        parser.error('reservation sizes must be non-negative')
    report = budget_report(args.root, args.native_base, args.reserve_runtime, args.reserve_models)
    print(json.dumps(report))
    if not report['checks_passed']:
        raise SystemExit('capacity preflight failed')


if __name__ == '__main__':
    main()
