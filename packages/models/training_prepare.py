"""CPU preparation of the public TrainingSnapshot, with immutable audit outputs.

This module exports reports, not an alternative annotation/snapshot contract.
It never runs training or a model and never writes to original media.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from .protocol import resolve_relative, storage_root
from .storage import reserve
from .training_sources import canonical_bytes, read_json, require, verify_asset, plan_window, decode_window


MAX_OUTPUT_BYTES = 100_000_000


def load_snapshot(path):
    # Public semantic validation and content-hash recomputation are mandatory.
    from packages.contracts.training import TrainingSnapshot
    raw, digest = read_json(path)
    return TrainingSnapshot.model_validate(raw), digest


def load_assets(path):
    from packages.contracts import AssetManifest
    raw, digest = read_json(path)
    manifest = AssetManifest.model_validate(raw)
    return {a.asset_id: a.model_dump(mode="json") for a in manifest.assets}, digest


def bind_source(reference, asset):
    """Exact identity bridge to the library AssetManifest and its real PTS index."""
    for name in ("asset_id", "relative_path", "sha256", "size_bytes", "duration_ms"):
        require(reference[name] == asset[name], "snapshot/library source identity differs: " + name)
    index = asset.get("probe", {}).get("pts_index", {})
    frozen = reference.get("pts_reference")
    require(isinstance(frozen, dict) and frozen, "snapshot must freeze a PTS reference before preparation")
    for name in ("relative_path", "sha256", "size_bytes", "frame_count", "time_base"):
        require(name in frozen and frozen[name] == index.get(name), "snapshot/library PTS reference differs: " + name)
    if "source_sha256" in frozen:
        require(frozen["source_sha256"] == asset["sha256"], "snapshot PTS source differs")


def choose_records(snapshot, selected, max_windows):
    require(type(max_windows) is int and 1 <= max_windows <= 16, "max_windows must be 1..16")
    all_records = {(b.asset.asset_id, r.record_id): r.model_dump(mode="json")
                   for b in snapshot.bundles for r in b.records if not r.deleted}
    if selected:
        require(len(selected) == len(set(selected)), "duplicate requested record")
        rows = []
        for key in selected:
            parts = key.split("/", 1)
            require(len(parts) == 2 and tuple(parts) in all_records,
                    "--record must identify a live asset_id/record_id")
            rows.append(all_records[tuple(parts)])
    else:
        # Explicit intervals only. Do not invent contact or rally endpoints.
        rows = [r for r in all_records.values() if r["kind"] == "segment"]
    require(len(rows) <= max_windows, "selected windows exceed limit; select a smaller explicit set")
    require(rows, "no explicit segments; select a point record to request a review context")
    return sorted(rows, key=lambda r: (r["asset_id"], r["record_id"]))


def prepare_windows(snapshot, assets, root, *, selected=(), max_windows=8,
                    sample_count=6, before_ms=500, after_ms=1000, decode=True):
    require(type(before_ms) is int and type(after_ms) is int and
            0 <= before_ms <= 15000 and 1 <= after_ms <= 15000,
            "point context must be bounded integer milliseconds")
    # This callable is also used outside the CLI: never accept caller-supplied
    # supervision rows or infer global trainability from one eligible record.
    from .training_readiness import audit_snapshot
    audit = audit_snapshot(snapshot, source_assets=assets)
    strict_training_view = audit["strict_training_view"] if audit["trainable"] else ()
    records = choose_records(snapshot, selected, max_windows)
    refs = {a.asset_id: a.model_dump(mode="json") for a in snapshot.assets}
    rallies = {(bundle.asset.asset_id, record.record_id): record.model_dump(mode="json")
               for bundle in snapshot.bundles for record in bundle.records
               if record.kind == "rally" and not record.deleted}
    verified, outputs = {}, []
    for record in records:
        asset_id = record["asset_id"]
        require(asset_id in assets, "snapshot source absent from library manifest")
        if asset_id not in verified:
            bind_source(refs[asset_id], assets[asset_id])
            verified[asset_id] = verify_asset(root, assets[asset_id])
        source = verified[asset_id]
        rally_id = record.get("rally_id")
        rally = rallies.get((asset_id, rally_id)) if rally_id else None
        require(not rally_id or rally is not None, "record refers to a missing or deleted rally")
        point = record["at_ms"]
        if point is None:
            start, end = record["start_ms"], record["end_ms"]
            semantics = "explicit_annotation_interval_not_verified_action_boundary"
        else:
            lower = max(0, rally["start_ms"]) if rally else 0
            upper = min(source["duration_ms"], rally["end_ms"]) if rally else source["duration_ms"]
            start, end = max(lower, point-before_ms), min(upper, point+after_ms)
            require(start < end, "point context has no interval inside its rally/media")
            semantics = "requested_review_context_not_action_or_trajectory_boundary"
        plan = plan_window(source, start, end, sample_count=sample_count)
        targets = [row for row in strict_training_view
                   if row["asset_id"] == asset_id and row["record_id"] == record["record_id"]
                   and row["record_revision"] == record["revision"]]
        row = {"asset_id": asset_id, "record_id": record["record_id"],
               "record_revision": record["revision"], "kind": record["kind"],
               "source_relative_path": assets[asset_id]["relative_path"],
               "source_sha256": source["source_sha256"], "pts_index_sha256": source["index_sha256"],
               "window_semantics": semantics, "usage_scope": "training_only",
               "context_scope": "rally_bounded" if rally else "scope_unknown",
               "rally_id": rally_id,
               "rally_bounds_ms": [rally["start_ms"], rally["end_ms"]] if rally else None,
               "review_only": not bool(targets), "supervision_targets": targets,
               "review": record["review"], "visibility": record["visibility"],
               "plan": plan, "decode": decode_window(source, plan) if decode else {"status": "not_run"}}
        outputs.append(row)
    return outputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("audit", "prepare"))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--root", type=Path, default=storage_root())
    parser.add_argument("--output-dir", required=True, help="New relative directory within models/")
    parser.add_argument("--record", action="append", default=[], help="asset_id/record_id; repeat to select")
    parser.add_argument("--max-windows", type=int, default=8)
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--before-ms", type=int, default=500)
    parser.add_argument("--after-ms", type=int, default=1000)
    parser.add_argument("--index-only", action="store_true", help="Do not claim actual decoding")
    parser.add_argument("--require-trainable", action="store_true")
    args = parser.parse_args(argv)
    from .training_readiness import audit_snapshot
    snapshot, snapshot_file_sha = load_snapshot(args.snapshot)
    assets, manifest_sha = (load_assets(args.manifest) if args.manifest is not None else (None, None))
    report = audit_snapshot(snapshot, source_assets=assets)
    report.update(snapshot_file_sha256=snapshot_file_sha, operation=args.operation,
                  gpu_used=False, model_run=False, training_run=False)
    if manifest_sha is not None:
        report["source_manifest_file_sha256"] = manifest_sha
    output = resolve_relative(args.root, args.output_dir, owner="models")
    require(not output.exists(), "output directory already exists; use a new attempt")
    with reserve(args.root, MAX_OUTPUT_BYTES) as usage:
        capacity = {"owner_usage_bytes": usage, "peak_reserved_bytes": MAX_OUTPUT_BYTES,
                    "free_bytes_before": shutil.disk_usage(args.root).free}
        if args.operation == "prepare":
            require(args.manifest is not None, "prepare requires --manifest with the source AssetManifest")
            report["windows"] = prepare_windows(snapshot, assets, args.root, selected=args.record,
                max_windows=args.max_windows, sample_count=args.samples, before_ms=args.before_ms,
                after_ms=args.after_ms, decode=not args.index_only)
        raw = canonical_bytes(report)
        require(len(raw) < MAX_OUTPUT_BYTES - 1_000_000, "report exceeds output reservation")
        output.mkdir(parents=True, exist_ok=False)
        with (output / "readiness.json").open("xb") as stream:
            stream.write(raw)
        with (output / "capacity.json").open("xb") as stream:
            stream.write(canonical_bytes(capacity))
    print(json.dumps({"report": args.output_dir + "/readiness.json",
                      "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                      "trainable": report["trainable"], "windows": len(report.get("windows", [])),
                      "strict_judgements": len(report["strict_training_view"]),
                      "gpu_used": False, "training_run": False}, ensure_ascii=False))
    return 2 if args.require_trainable and not report["trainable"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, TypeError, KeyError, OSError, ImportError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "message": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
