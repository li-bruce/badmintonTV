"""Snapshot the current model interpreter and verified download manifests.

Run in the WSL model environment after installation. This does not run models,
fetch weights, or promote an experimental model to validated accuracy.
"""
import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from packages.models.protocol import atomic_write_json, resolve_relative
from packages.models.registry import catalog, storage_root
from packages.models.storage import reserve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New catalog JSON under models/')
    args = parser.parse_args()
    root = storage_root()
    target = resolve_relative(root, args.output, owner='models')
    snapshot = catalog()
    sources = {'schema_version': '1.0', 'manifests': []}
    for name in ('qwen3-0.6b', 'torchvision-pose', 'clip-vit-base-patch32'):
        manifest = root / 'models/weights' / name / 'weights-manifest.json'
        sources['manifests'].append(json.loads(manifest.read_text(encoding='utf-8')))
    with reserve(root, 1_000_000):
        atomic_write_json(target, snapshot)
    # These are intentionally updated, reviewable repository snapshots.
    for name, payload in [('catalog.json', snapshot), ('weights-lock.json', sources)]:
        (REPO / 'configs/models' / name).write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'catalog': args.output, 'statuses': {m['model_id']: m['status'] for m in snapshot['models']}}))


if __name__ == '__main__':
    main()
