"""R-04b real-manifest negative checks; never opens training media or launches compute.

Run from the repository with the existing platform Python. Every mutable object
lives in a newly created private evidence directory; historical rows are fixtures.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import url2pathname


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True
PEAK_BYTES = 16_000_000
MANIFEST = "data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json"
REGISTRY = "data/training/handoff/training-registry.v1.json"
FIRST_ASSET = "asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def metadata_snapshot(path):
    before = path.stat()
    if before.st_size > 2_000_000:
        raise ValueError("Unexpected metadata size; this verification has a 16 MB budget")
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("Metadata changed while being read; rerun against a stable publication")
    body = json.loads(raw)
    return body, {"path": str(path), "captured_at": timestamp(), "sha256": hashlib.sha256(raw).hexdigest(),
                  "size_bytes": len(raw), "mtime_ns": after.st_mtime_ns,
                  "asset_count": len(body["assets"]), "asset_ids": [a["asset_id"] for a in body["assets"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", default="D:/video")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    root, output = Path(args.storage_root).resolve(), Path(args.output_dir).resolve()
    parent = root / "platform/research-20260929"
    if output.parent != parent or not output.name.startswith("r04b-real-negative-") or output.exists():
        raise ValueError("Choose a new r04b-real-negative-* directory under platform/research-20260929")
    free_before = shutil.disk_usage(root).free
    if free_before < PEAK_BYTES:
        raise RuntimeError("Insufficient physical space for the 16 MB private reservation")
    output.mkdir(parents=True, exist_ok=False)
    db_path = output / "private-platform.sqlite3"
    os.environ.update(BTV_STORAGE_ROOT=str(root), BTV_DB_PATH=str(db_path),
                      PYTHONDONTWRITEBYTECODE="1", BTV_RENDER_BACKEND="cpu")
    os.environ["BTV_RENDER_COMMAND_JSON"] = json.dumps([sys.executable, "-c", "raise SystemExit('R04b execution sentinel reached')"])

    forbidden = []
    metadata_paths = {root / MANIFEST, root / REGISTRY}
    def audit(event, values):
        if event == "subprocess.Popen":
            forbidden.append("subprocess.Popen")
            raise AssertionError("R04b negative verification must never launch a subprocess")
        if event == "sqlite3.connect":
            value = str(values[0])
            if value.startswith("file:"):
                uri = urlsplit(value)
                if uri.netloc not in {"", "localhost"}:
                    raise AssertionError("Remote SQLite URIs are not allowed")
                value = url2pathname(uri.path)
            path = Path(value).resolve()
            if not path.is_relative_to(output):
                forbidden.append("sqlite_outside_private_directory")
                raise AssertionError("Only private verification databases may be opened")
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink"}:
            paths = values[:2] if event in {"os.rename", "os.link", "os.symlink"} else values[:1]
            for value in paths:
                path = Path(value).resolve()
                if path.is_relative_to(root) and not path.is_relative_to(output):
                    forbidden.append("filesystem_mutation_outside_private_directory")
                    raise AssertionError("Shared directories must not be changed")
        if event == "open" and not isinstance(values[0], int):
            path = Path(values[0]).resolve()
            mode, flags = values[1], values[2]
            writing = any(c in (mode or "") for c in "wax+") or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and path.is_relative_to(root) and not path.is_relative_to(output):
                forbidden.append("write_outside_private_directory")
                raise AssertionError("Shared storage is read-only for this verification")
            if path.is_relative_to(root / "data/training") and path not in metadata_paths:
                forbidden.append("training_media_open")
                raise AssertionError("Training media bytes must not be read or hashed")
    sys.addaudithook(audit)

    report = {"case_id": "R-04b", "started_at": timestamp(), "output_dir": str(output),
              "reservation_peak_bytes": PEAK_BYTES, "free_bytes_before": free_before,
              "private_business_db": str(db_path), "checks": [], "status": "RUNNING",
              "scope": "Real library metadata and source stat; no source-byte read, copy, decode, model or render CLI execution. Historical business rows/jobs below are manually seeded fixtures."}
    ledger = reservation = None
    try:
        from fastapi.testclient import TestClient
        from packages.contracts import AssetManifest, TrainingRegistry
        from packages.runtime.storage import CapacityLedger, directory_bytes
        from packages.runtime import worker
        from apps.platform.main import app

        store, queue = app.state.store, app.state.queue
        assert store.path.resolve() == db_path
        assert Path(queue.db_path).parent.resolve() == output
        ledger = CapacityLedger(queue.db_path, root)
        reservation = ledger.reserve("platform", PEAK_BYTES)
        report["reservation_id"] = reservation
        manifest, report["manifest_before"] = metadata_snapshot(root / MANIFEST)
        registry, report["registry_before"] = metadata_snapshot(root / REGISTRY)
        AssetManifest.model_validate(manifest)
        TrainingRegistry.model_validate(registry)
        real_asset = next(a for a in manifest["assets"] if a["asset_id"] == FIRST_ASSET)
        registered = {(a["asset_id"], a["sha256"], a["relative_path"]) for a in registry["assets"]}
        report["manifest_assets_stat_only"] = []
        for asset in manifest["assets"]:
            source = root / asset["relative_path"]
            stat = source.stat()
            assert stat.st_size == asset["size_bytes"]
            assert (asset["asset_id"], asset["sha256"], asset["relative_path"]) in registered
            report["manifest_assets_stat_only"].append({"asset_id": asset["asset_id"], "relative_path": asset["relative_path"],
                "library_declared_sha256_not_rehashed_here": asset["sha256"], "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "usage_scope": asset.get("usage_scope"), "registry_match": True})

        def check_response(name, response, *, seeded=False):
            entry = {"name": name, "historical_fixture": seeded, "http_status": response.status_code,
                     "response": response.json(), "expected": "HTTP 422 with TRAINING_ONLY"}
            entry["status"] = "PASS" if response.status_code == 422 and "TRAINING_ONLY" in response.text else "FAIL"
            report["checks"].append(entry)
            assert entry["status"] == "PASS", entry

        with TestClient(app) as client:
            response = client.post("/api/v1/libraries", json={"name": "R04b private real-training negative verification"})
            assert response.status_code == 201
            library_id = response.json()["library_id"]
            check_response("real_manifest_import", client.post("/api/v1/assets/import", json={"library_id": library_id, "manifest": manifest}))
            check_response("real_path_import", client.post("/api/v1/assets/import-path", json={"library_id": library_id, "relative_path": real_asset["relative_path"], "metadata": {}}))
            conflict = copy.deepcopy(real_asset)
            conflict["usage_scope"] = "general"
            conflict["provenance"] = {"usage_scope": "general"}
            check_response("general_metadata_cannot_override_training_path", client.post("/api/v1/assets/import", json={"library_id": library_id, "manifest": {"assets": [conflict]}}))
            alias = {k: v for k, v in real_asset.items() if k not in {"usage_scope", "provenance"}}
            alias.update(asset_id="real-sha-metadata-alias", relative_path="data/r04b-metadata-only-no-copy.mp4")
            check_response("real_registered_sha_metadata_alias_no_file_copy", client.post("/api/v1/assets/import", json={"library_id": library_id, "manifest": {"assets": [alias]}}))
            assert store._raw_assets() == [] and queue.list() == []
            assert client.get("/api/v1/assets").json() == []
            report["empty_library_after_import_attempts"] = True

            timeline = {"schema_version": "1.0", "timeline_id": "real-training-history", "title": "Manually seeded historical fixture",
                "segments": [{"segment_id": "history-segment", "asset_id": real_asset["asset_id"], "in_ms": 0, "out_ms": 500,
                    "speed": 1.0, "event_ids": [], "fit": "contain", "audio": "source", "review_status": "confirmed"}],
                "output": {"width": 1080, "height": 1920, "fps": 30, "video_codec": "h264", "audio_codec": "aac"}}
            executed = []
            def no_adapter(*_args, **_kwargs):
                executed.append("adapter")
                raise AssertionError("Restricted source reached the adapter")
            for preview in (False, True):
                payload = {"assets": [real_asset], "timeline": timeline, "parameters": {"research_preview": preview}, "render_backend": "cpu"}
                queued = queue.enqueue("render", payload)
                with patch.object(worker, "adapter", no_adapter):
                    done = worker.run_once(queue, root, worker_id="r04b-private-negative-worker")
                good = done["job_id"] == queued["job_id"] and done["status"] == "blocked" and done["error"]["code"] == "TRAINING_ONLY"
                report["checks"].append({"name": "worker_research_preview" if preview else "worker_render", "status": "PASS" if good else "FAIL",
                    "expected": "blocked/TRAINING_ONLY before adapter", "job_id": done["job_id"], "worker_status": done["status"], "error": done["error"]})
                assert good and not executed
                assert not (root / "platform/jobs" / done["job_id"]).exists()
            report["adapter_execution_count"] = len(executed)

            # Deliberate historical fixture: not an accepted import or verified production asset.
            # Simulate old confirmed review solely to reach the later usage gate;
            # this is not a human review and is confined to the disposable DB.
            event_id = "simulated-historical-review-not-a-real-annotation"
            timeline["segments"][0]["event_ids"] = [event_id]
            simulated_event = {"schema_version": "1.0", "event_id": event_id, "asset_id": real_asset["asset_id"],
                "match_id": real_asset["match_id"], "kind": "stroke", "start_ms": 0, "end_ms": 500,
                "labels": {"stroke": "unknown"}, "visibility": "unknown", "review_status": "confirmed", "revision": 1,
                "reviewer_type": "human", "provenance": {"source": "manual", "note": "SIMULATED legacy review fixture; no human reviewed this event"}, "evidence": []}
            with store.connect() as db:
                db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?)", (real_asset["asset_id"], real_asset["sha256"], library_id,
                    real_asset["match_id"], real_asset["split"], json.dumps(real_asset)))
                db.execute("INSERT INTO events VALUES(?,?,?,?)", (event_id, real_asset["asset_id"], 1, json.dumps(simulated_event)))
            candidate = {"candidate_id": "real-training-candidate", "asset_id": real_asset["asset_id"], "start_ms": 0, "end_ms": 500,
                         "event_ids": [], "review_status": "confirmed", "reviewer": "R04b fixture", "reviewer_type": "agent"}
            store.put("candidate", candidate["candidate_id"], candidate)
            store.put("timeline", timeline["timeline_id"], timeline)
            store.put("timeline_review", timeline["timeline_id"], {
                "timeline_sha256": hashlib.sha256(json.dumps(timeline, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                "reviewer_type": "human", "reviewers": [{"reviewer": "SIMULATED fixture; no real human review", "reviewer_type": "human"}],
                "event_revisions": {event_id: 1}, "candidates": []})
            report["historical_seed"] = {"method": "private SQL INSERT and Store.put; production import did not succeed",
                "asset_id": real_asset["asset_id"], "candidate_id": candidate["candidate_id"], "timeline_id": timeline["timeline_id"],
                "simulated_human_review": "Negative fixture only, to pass the earlier editorial gate; no genuine human review or annotation was performed"}
            endpoints = [
                ("historical_raw_media", "GET", f"/api/v1/assets/{real_asset['asset_id']}/media", None),
                ("historical_candidate_review", "POST", f"/api/v1/candidates/{candidate['candidate_id']}/confirm", {"review_status": "confirmed", "reviewer": "R04b fixture", "reviewer_type": "agent"}),
                ("historical_candidate_to_timeline", "POST", "/api/v1/timelines/from-candidates", {"candidate_ids": [candidate["candidate_id"]]}),
                ("historical_save_timeline", "POST", "/api/v1/timelines", timeline),
                ("historical_render_api", "POST", f"/api/v1/timelines/{timeline['timeline_id']}/render", {"research_preview": False}),
                ("historical_research_preview_api", "POST", f"/api/v1/timelines/{timeline['timeline_id']}/render", {"research_preview": True}),
            ]
            for name, method, url, body in endpoints:
                check_response(name, client.request(method, url, **({"json": body} if body is not None else {})), seeded=True)

            def historical_job(operation, payload, *, result=None, status="succeeded"):
                queued = queue.enqueue(operation, payload)
                claimed = queue.claim("r04b-historical-fixture-writer")
                assert claimed["job_id"] == queued["job_id"]
                return queue.finish(queued["job_id"], "r04b-historical-fixture-writer", status, result=result,
                                    error={"code": "MANUALLY_SEEDED_HISTORY"} if status == "failed" else None)
            for kind in ("retry", "apply_probe", "apply_manifest", "artifact"):
                operation = {"apply_probe": "probe", "apply_manifest": "verify_manifest"}.get(kind, "render")
                payload = {"assets": [real_asset], "library_id": library_id, "relative_path": real_asset["relative_path"]}
                result = {"asset": real_asset} if kind == "apply_probe" else {"assets": [real_asset]}
                if kind == "artifact":
                    result = {"artifacts": [{"artifact_id": "fixture-no-output", "kind": "video", "relative_path": output.relative_to(root).as_posix() + "/never-created.mp4", "sha256": "f" * 64}]}
                job = historical_job(operation, payload, result=result, status="failed" if kind == "retry" else "succeeded")
                url = f"/api/v1/jobs/{job['job_id']}"
                response = client.get(url + "/artifacts/fixture-no-output") if kind == "artifact" else client.post(url + ("/retry" if kind == "retry" else "/apply"))
                check_response("historical_" + kind, response, seeded=True)
                assert queue.get(job["job_id"])["status"] == job["status"]
            assert store.get("candidate", candidate["candidate_id"]) == candidate
            assert store.get("timeline", timeline["timeline_id"]) == timeline
            assert client.get("/api/v1/assets").json() == []
            report["historical_raw_row_count"] = len(store._raw_assets())
            report["historical_visible_asset_count"] = 0

        _, report["manifest_after"] = metadata_snapshot(root / MANIFEST)
        _, report["registry_after"] = metadata_snapshot(root / REGISTRY)
        report["metadata_stable_during_run"] = all(report[name + "_before"]["sha256"] == report[name + "_after"]["sha256"] for name in ("manifest", "registry"))
        report["source_media_open_count"] = 0
        report["forbidden_actions"] = forbidden
        assert not forbidden
        report["private_bytes_before_report"] = directory_bytes(output)
        assert report["private_bytes_before_report"] < PEAK_BYTES - 1_000_000
        report["status"] = "PASS"
    except BaseException as exc:
        report["status"] = "FAIL"
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if ledger is not None and reservation is not None:
            ledger.release(reservation)
            report["reservation_released"] = True
        report["finished_at"] = timestamp()
        report["forbidden_actions"] = forbidden
        evidence = output / "evidence.json"
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "checks": len(report["checks"]), "evidence": str(evidence)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
