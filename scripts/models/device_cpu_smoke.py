"""Read-only real-frame CPU smoke; prints evidence, never creates training labels."""
import argparse
import json
from pathlib import Path
import sys

# Run as a script from a source package, without installing it globally.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.models.training_prepare import load_snapshot, load_assets, prepare_windows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument("--samples", type=int, default=2)
    args = parser.parse_args(argv)
    snapshot, digest = load_snapshot(args.snapshot)
    assets, manifest_hash = load_assets(args.manifest)
    if not args.record:
        selected = [b.asset.asset_id + "/" + r.record_id for b in snapshot.bundles
                    for r in b.records if not r.deleted and r.kind == "segment"][:1]
    else:
        selected = args.record
    windows = prepare_windows(snapshot, assets, args.storage_root, selected=selected,
                              max_windows=2, sample_count=args.samples)
    evidence = {"schema_version": "1.0", "status": "verified_cpu_decode", "snapshot_file_sha256": digest,
                "source_manifest_file_sha256": manifest_hash, "python": sys.version.split()[0],
                "environment_prefix": sys.prefix, "base_prefix": sys.base_prefix,
                "gpu_used": False, "training_run": False, "model_imported": "torch" in sys.modules,
                "images_written": False, "windows": windows}
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
