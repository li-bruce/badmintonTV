"""Temporary HTTP/SQLite engineering tests; mocked probe is not real media QA."""
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from packages.contracts import AssetManifest
from packages.library.probe import ProbeError
from packages.library.storage import QuotaManager
from scripts.library import acquire_classic_matches as acquisition


class ClassicAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=0)
        self.payload = b"synthetic small media bytes; engineering fixture only"
        self.requests = []
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                fixture.requests.append(dict(self.headers.items()))
                self.send_response(200)
                self.send_header("Content-Length", str(len(fixture.payload)))
                self.send_header("Content-Type", "video/mp4")
                self.send_header("ETag", '"fixed-fixture-version"')
                self.end_headers()
                self.wfile.write(fixture.payload)
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def config(self, version="classic-test", maximum=None):
        return {"dataset_version": version, "sources": [{
            "source_id": "match-one", "source_page_url": self.origin + "/public/source-one",
            "provider": "Synthetic public provider", "match_id": "unverified-match-one",
            "match_title": "Synthetic fixture, no real identity", "event_date": "2012-08-05",
            "rights_statement": "No copyright permission established",
            "resolved_url": self.origin + "/file?token=DO_NOT_PERSIST",
            "max_bytes": len(self.payload) if maximum is None else maximum,
            "source_metadata": {"bvid": "BVfixture", "cid": 123, "owner": {"mid": 12, "name": "Fixture"},
                                "rights": {"download": 1, "pay": 0, "no_reprint": 1}}}]}

    def fake_probe(self, path, **kwargs):
        self.assertEqual(7200, kwargs["timeout_seconds"])
        self.assertEqual(128_000_000, kwargs["max_pts_bytes"])
        pts = kwargs["pts_index_path"]
        pts.parent.mkdir(parents=True, exist_ok=True)
        raw = b'{"frame_index":0,"pts":0}\n{"frame_index":1,"pts":1}\n{"frame_index":2,"pts":2}\n'
        pts.write_bytes(raw)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"duration_ms": 120, "width": 16, "height": 16, "fps_num": 25, "fps_den": 1,
                "time_base": "1/25", "probe": {"source_sha256": digest, "source_size_bytes": path.stat().st_size,
                "decode": {"status": "passed", "scope": "full_video_stream", "device": "cpu", "exit_code": 0, "frames": 3},
                "pts_index": {"relative_path": pts.relative_to(self.root).as_posix(), "size_bytes": len(raw),
                              "sha256": hashlib.sha256(raw).hexdigest(), "format": "jsonl", "frame_count": 3,
                              "time_base": "1/25", "complete": True}, "vfr_status": "cfr_observed"}}

    def assert_no_secret_or_central_writes(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"DO_NOT_PERSIST", path.read_bytes(), str(path))
        self.assertFalse((self.root / "data/training/handoff").exists())
        self.assertEqual([], self.quota.active_reservations())

    def test_real_bounded_download_sanitized_review_handoff_and_idempotent_source_reuse(self):
        config = self.config()
        with patch.object(acquisition, "probe_video", side_effect=self.fake_probe):
            result = acquisition.acquire(config, quota=self.quota, ffmpeg="mock-ffmpeg", ffprobe="mock-ffprobe")
        self.assertEqual("complete", result["status"])
        self.assertEqual(1, result["succeeded"])
        self.assertEqual("review_only", result["handoff_status"])
        self.assertFalse(result["central_registry_published"])
        self.assertEqual(0, result["human_confirmed_annotations"])
        base = self.root / "data/training/classic-test"
        manifest = json.loads((base / "handoff/assets.v1.json").read_bytes())
        AssetManifest.model_validate(manifest)
        asset = manifest["assets"][0]
        self.assertEqual("training_only", asset["usage_scope"])
        self.assertEqual("training_only", asset["provenance"]["usage_scope"])
        self.assertEqual("unknown", asset["rights"]["status"])
        self.assertEqual([], asset["rights"]["allowed_uses"])
        self.assertEqual("unassigned", asset["split"])
        self.assertEqual(config["sources"][0]["source_metadata"], asset["provenance"]["publisher_metadata"])
        self.assertEqual(config["sources"][0]["source_page_url"], self.requests[0]["Referer"])
        self.assertEqual("badmintonTV-library/0.1", self.requests[0]["User-Agent"])
        self.assertNotIn("Cookie", self.requests[0])
        original = base / "raw/match-one.mp4"
        before = (original.read_bytes(), original.stat().st_mtime_ns)
        # Reproduce a process ending between durable success receipt and entry publication.
        (base / "handoff/assets.v1.json").unlink()
        config["sources"][0]["resolved_url"] = self.origin + "/file?token=NEW_EPHEMERAL_URL"
        with patch.object(acquisition, "probe_video", side_effect=AssertionError("Must reuse verified original")):
            again = acquisition.acquire(config, quota=self.quota, ffmpeg="unused", ffprobe="unused")
        self.assertEqual(1, again["succeeded"])
        self.assertEqual("complete", again["status"])
        self.assertEqual(1, len(json.loads((base / "handoff/assets.v1.json").read_bytes())["assets"]))
        self.assertEqual(1, len(self.requests))
        self.assertEqual(before, (original.read_bytes(), original.stat().st_mtime_ns))
        audit = [json.loads(line) for line in (base / "handoff/metadata-audit.jsonl").read_bytes().splitlines()]
        self.assertTrue(any(row["state"] == "started" for row in audit))
        self.assertTrue(all(row.get("old_sha256") and row.get("new_sha256") and row.get("at") for row in audit))
        manifest_path, record_path = base / "handoff/assets.v1.json", base / "handoff/match-one.json"
        published = (manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns)
        record_bytes = record_path.read_bytes()
        for mutation in ("missing", "malformed", "downgraded", "mismatched"):
            record_path.write_bytes(record_bytes)
            if mutation == "missing":
                record_path.unlink()
            elif mutation == "malformed":
                record_path.write_bytes(b"{broken-json")
            else:
                record = json.loads(record_bytes)
                if mutation == "downgraded":
                    record["state"] = "failed"
                else:
                    record["asset"]["match_id"] = "different-source-match"
                record_path.write_text(json.dumps(record), encoding="utf-8")
            with self.subTest(mutation=mutation), patch.object(acquisition, "probe_video") as probe, \
                 self.assertRaises((ValueError, OSError)):
                acquisition.acquire(config, quota=self.quota, ffmpeg="unused", ffprobe="unused")
            probe.assert_not_called()
            self.assertEqual(published, (manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns))
            self.assertEqual(1, len(self.requests))
            self.assertEqual(before, (original.read_bytes(), original.stat().st_mtime_ns))
        record_path.write_bytes(record_bytes)
        self.assert_no_secret_or_central_writes()

    def test_oversize_and_probe_failure_never_count_success_or_leak_transport_secret(self):
        for kind in ("oversize", "probe-failure"):
            config = self.config(version="classic-" + kind,
                                 maximum=len(self.payload) - 1 if kind == "oversize" else len(self.payload))
            error = ProbeError("diagnostic accidentally contains " + config["sources"][0]["resolved_url"])
            with self.subTest(kind=kind), patch.object(acquisition, "probe_video", side_effect=error) as probe:
                result = acquisition.acquire(config, quota=self.quota, ffmpeg="unused", ffprobe="unused")
            self.assertEqual("failed", result["status"])
            self.assertEqual(0, result["succeeded"])
            self.assertEqual("failed", result["records"][0]["state"])
            self.assertNotIn("asset", result["records"][0])
            base = self.root / ("data/training/classic-" + kind)
            self.assertEqual([], json.loads((base / "handoff/assets.v1.json").read_bytes())["assets"])
            if kind == "oversize":
                probe.assert_not_called()
                self.assertFalse((base / "raw/match-one.mp4").exists())
                self.assertEqual("size_limit", result["records"][0]["error"]["code"])
            else:
                self.assertEqual(self.payload, (base / "raw/match-one.mp4").read_bytes())
                self.assertEqual("ProbeError", result["records"][0]["error"]["code"])
            self.assert_no_secret_or_central_writes()
        # A one-of-two published subset is a legitimate interrupted batch.
        config = self.config(version="classic-partial")
        second = copy.deepcopy(config["sources"][0])
        second.update(source_id="match-two", match_id="unverified-match-two")
        config["sources"].append(second)
        def partial_probe(path, **kwargs):
            if path.name == "match-one.mp4":
                return self.fake_probe(path, **kwargs)
            raise ProbeError("fixture second source remains unverified")
        with patch.object(acquisition, "probe_video", side_effect=partial_probe):
            partial = acquisition.acquire(config, quota=self.quota, ffmpeg="unused", ffprobe="unused")
        self.assertEqual(("partial", 1), (partial["status"], partial["succeeded"]))
        manifest = self.root / "data/training/classic-partial/handoff/assets.v1.json"
        published = (manifest.read_bytes(), manifest.stat().st_mtime_ns)
        with patch.object(acquisition, "probe_video", side_effect=ProbeError("fixture pending failure")):
            retry = acquisition.acquire(config, quota=self.quota, ffmpeg="unused", ffprobe="unused")
        self.assertEqual(("partial", 1), (retry["status"], retry["succeeded"]))
        self.assertEqual(published, (manifest.read_bytes(), manifest.stat().st_mtime_ns))
        self.assert_no_secret_or_central_writes()


if __name__ == "__main__":
    unittest.main()
