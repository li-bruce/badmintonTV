"""Build an explicitly non-trainable agent demo through the PUBLIC snapshot API.

This creates no human annotation, model prediction or match/identity confirmation.
The chosen range is a review window, not a verified action or rally boundary.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.training import TrainingTaxonomy, build_training_snapshot
from packages.models.protocol import resolve_relative, storage_root
from packages.models.storage import reserve
from packages.models.training_prepare import load_assets
from packages.models.training_sources import canonical_bytes, read_json, require


def source_usage_scope(source):
    """Retain the canonical source scope; only legacy assets use provenance."""
    if "usage_scope" in source:
        scope = source["usage_scope"]
    else:
        provenance = source.get("provenance", {})
        require(isinstance(provenance, dict), "source provenance must be an object")
        scope = provenance.get("usage_scope", "training_only")
    require(scope in ("general", "training_only"), "invalid source usage_scope")
    return scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--taxonomy", required=True, type=Path, help="Public TrainingTaxonomy JSON exported by platform")
    parser.add_argument("--start-ms", required=True, type=int)
    parser.add_argument("--end-ms", required=True, type=int)
    parser.add_argument("--label", action="append", required=True)
    parser.add_argument("--root", type=Path, default=storage_root())
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    assets, manifest_sha = load_assets(args.manifest)
    require(args.asset_id in assets, "asset missing from source manifest")
    source = assets[args.asset_id]
    require(0 <= args.start_ms < args.end_ms <= source["duration_ms"] and
            args.end_ms-args.start_ms <= 30_000, "bounded review range required")
    taxonomy_raw, taxonomy_sha = read_json(args.taxonomy, limit=2_000_000)
    taxonomy = TrainingTaxonomy.model_validate(taxonomy_raw)
    labels = {label.label_id: label for label in taxonomy.labels}
    require(len(args.label) == len(set(args.label)), "duplicate demo label")
    require(all(key in labels and "segment" in labels[key].kinds for key in args.label),
            "demo labels must be public segment labels")
    now = datetime.now(timezone.utc).isoformat()
    project_id = "models-agent-preparation-demo-v1"
    provenance = {**source.get("provenance", {}), "demo": True, "actor_type": "agent",
                  "source_manifest_file_sha256": manifest_sha,
                  "source_rights": source.get("rights", {}),
                  "note": "Software preparation demonstration only; match and identities not confirmed."}
    reference = {name: source[name] for name in ("asset_id", "relative_path", "sha256", "size_bytes", "duration_ms")}
    reference.update(title=source.get("title", ""), usage_scope="training_only",
        source_usage_scope=source_usage_scope(source),
        match_id=source.get("match_id"), group_id=None, group_status="unknown",
        pts_reference={**source["probe"]["pts_index"], "source_sha256":source["sha256"]},
        provenance=provenance)
    record = {"record_id":"agent-review-window-1", "project_id":project_id, "asset_id":source["asset_id"],
        "kind":"segment", "segment_type":"other", "start_ms":args.start_ms, "end_ms":args.end_ms,
        "person_id":"unconfirmed-target", "visibility":"unknown",
        "unknown_reasons":["Agent demo has no expert label or independent visibility/identity adjudication."],
        "judgements":[{"label_id":key,"value":"unknown", "reason":"Definition/evidence not human adjudicated; no positive or negative claim."} for key in args.label],
        "evidence":[{"type":"source_review_range", "source_sha256":source["sha256"],
                     "start_ms":args.start_ms, "end_ms":args.end_ms, "actor_type":"agent"}],
        "review":{"status":"draft","reviewer_type":"agent","reviewer":"models-agent-demo", "reviewed_at":now},
        "provenance":{"demo":True,"actor_type":"agent", "revision_audit":{"actor_type":"agent","reviewer":"models-agent-demo","at":now}}}
    bundle = {"project_id":project_id,"asset":reference,
              "people":[{"person_id":"unconfirmed-target","display_name":"Unconfirmed review target","identity_status":"unknown"}],
              "records":[record]}
    project = {"project_id":project_id,"name":"Explicit agent CPU preparation demo",
               "catalog_version":"source-manifest-sha256:"+manifest_sha,
               "taxonomy_id":taxonomy.taxonomy_id,"taxonomy_version":taxonomy.version,
               "asset_ids":[source["asset_id"]],"created_at":now,"updated_at":now,
               "provenance":{"demo":True,"actor_type":"agent","public_taxonomy_file_sha256":taxonomy_sha}}
    snapshot = build_training_snapshot(snapshot_id="models-agent-demo-snapshot-v1", project=project,
        taxonomy=taxonomy, assets=[reference], bundles=[bundle], created_at=now)
    require(not snapshot.quality_summary.trainable and not snapshot.training_view,
            "agent demo must never create human training targets")
    output = resolve_relative(args.root, args.output_dir, owner="models")
    require(not output.exists(), "demo output already exists; never overwrite snapshots")
    raw = canonical_bytes(snapshot.model_dump(mode="json"))
    require(len(raw) <= 10_000_000, "demo exceeds reservation")
    with reserve(args.root, 10_000_000):
        output.mkdir(parents=True, exist_ok=False)
        with (output/"snapshot.json").open("xb") as stream:
            stream.write(raw)
    print(snapshot.content_sha256)


if __name__ == "__main__":
    main()
