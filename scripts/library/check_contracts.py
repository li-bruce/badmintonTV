"""Check real library assets against the shared contract implementation, read-only."""

import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts-root", help="Optional checkout containing packages/contracts")
    parser.add_argument("--manifest", default="D:/video/data/handoff/assets.v1.json")
    parser.add_argument("--storage-root", default="D:/video")
    args = parser.parse_args()
    if args.contracts_root:
        sys.path.insert(0, str(Path(args.contracts_root).resolve()))
    from packages.contracts import AssetManifest
    from packages.library.manifest import validate_asset

    raw = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    canonical = AssetManifest.model_validate(raw)
    for asset in raw["assets"]:
        validate_asset(asset, storage_root=args.storage_root, verify_file=True)
    if args.contracts_root:
        fixture_path = Path(args.contracts_root) / "packages/contracts/fixtures/asset-manifest.json"
    else:
        import packages.contracts
        fixture_path = Path(packages.contracts.__file__).parent / "fixtures/asset-manifest.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for asset in fixture["assets"]:
        validate_asset(asset, storage_root=args.storage_root, verify_file=False)
    print(json.dumps({
        "schema_version": "1.0", "status": "passed",
        "real_assets_accepted_by_canonical_contract": len(canonical.assets),
        "real_original_and_pts_hashes_verified": len(raw["assets"]),
        "canonical_fixture_assets_accepted_by_library": len(fixture["assets"]),
        "fixture_file_verification": False,
        "fixture_note": "Synthetic structure only; no media existence or recognition claims."
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
