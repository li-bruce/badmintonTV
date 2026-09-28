"""Contract/security tests; dummy bytes are never presented as real video QA."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from packages.library.manifest import (
    ManifestError, SplitRegistry, build_asset, safe_asset_path,
    sha256_file, stable_asset_id, validate_asset, write_manifest,
)
from packages.library.probe import ProbeError, _pts_index, probe_video


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / "data" / "raw" / "original.bin"
        self.media.parent.mkdir(parents=True)
        self.media.write_bytes(b"synthetic unit-test fixture, not a video")
        self.metadata = {
            "title": "Contract fixture", "match_id": "canonical-match-01",
            "source_type": "synthetic", "source_url": None, "source_page": None,
            "acquired_at": "2026-09-28T00:00:00+00:00", "camera_type": "unknown",
            "discipline": "unknown", "players": [], "split": "unassigned",
            "rights": {"status": "owned", "license_url": None,
                       "evidence": "Locally created test bytes", "allowed_uses": ["testing"]},
            "provenance": {"annotation_rights": {"status": "unknown"}},
        }
        self.probe = {"duration_ms": 1000, "width": 640, "height": 360,
                      "fps_num": 30000, "fps_den": 1001, "time_base": "1/30000",
                      "probe": {"decode": {"status": "passed"}, "vfr_status": "unknown"}}
        self.asset = build_asset(self.media, self.metadata, self.probe, storage_root=self.root)

    def test_stable_sha_identity_and_independent_rights(self):
        digest = hashlib.sha256(self.media.read_bytes()).hexdigest()
        self.assertEqual(stable_asset_id(digest), self.asset["asset_id"])
        self.assertEqual("data/raw/original.bin", self.asset["relative_path"])
        self.assertEqual("owned", self.asset["rights"]["status"])
        self.assertEqual("unknown", self.asset["provenance"]["annotation_rights"]["status"])
        self.assertNotIn("schema_version", self.metadata)

    def test_rejects_unsafe_paths_even_without_file_verification(self):
        for path in ("../secret", "/secret", "C:/secret", "C:secret", "data/../secret",
                     "data\\secret", "//server/share", "data//raw", "data/./raw",
                     "data/raw:stream", "data/zero\x00"):
            with self.subTest(path=path), self.assertRaises(ManifestError):
                safe_asset_path(path, self.root)

    def test_root_outside_symlink_or_windows_junction_is_rejected(self):
        external = tempfile.TemporaryDirectory(prefix="library-manifest-outside-")
        self.addCleanup(external.cleanup)
        outside = Path(external.name)
        marker = outside / "preserve.txt"
        marker.write_bytes(b"target contents must survive link cleanup")
        link = self.root / "outside"
        try:
            if os.name == "nt":
                subprocess.run(
                    ["cmd", "/d", "/c", "mklink", "/J", str(link), str(outside)],
                    check=True, capture_output=True, text=True,
                )
                self.assertTrue(link.is_junction())
            else:
                link.symlink_to(outside, target_is_directory=True)
                self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), outside.resolve())
            with self.assertRaises(ManifestError):
                safe_asset_path("outside/a.mp4", self.root)
        finally:
            # rmdir removes the junction entry itself, not its target contents.
            if getattr(link, "is_junction", lambda: False)():
                link.rmdir()
            elif link.is_symlink():
                link.unlink()
        self.assertEqual(marker.read_bytes(), b"target contents must survive link cleanup")

    def test_checks_hash_size_and_presence(self):
        for field, value in (("sha256", "0" * 64), ("size_bytes", 999),
                             ("relative_path", "data/not-found.mp4")):
            asset = copy.deepcopy(self.asset)
            asset[field] = value
            with self.subTest(field=field), self.assertRaises(ManifestError):
                validate_asset(asset, storage_root=self.root)

    def test_rejects_missing_fields_wrong_types_and_naive_dates(self):
        for field in self.asset:
            asset = copy.deepcopy(self.asset)
            del asset[field]
            with self.subTest(field=field), self.assertRaises(ManifestError):
                validate_asset(asset, storage_root=self.root)
        for field, value in (("size_bytes", True), ("fps_den", 0), ("time_base", "0/1"),
                             ("time_base", "N/A"), ("acquired_at", "2026-09-28"),
                             ("split", "testing"), ("players", [{}]), ("match_id", " match ")):
            asset = copy.deepcopy(self.asset)
            asset[field] = value
            with self.subTest(field=field), self.assertRaises(ManifestError):
                validate_asset(asset, storage_root=self.root)

    def test_unknown_match_is_explicitly_unassigned(self):
        for match in ("", "unknown"):
            asset = dict(self.asset, match_id=match, split="unassigned")
            validate_asset(asset, storage_root=self.root)
            asset["split"] = "train"
            with self.assertRaises(ManifestError):
                validate_asset(asset, storage_root=self.root)

    def test_build_requires_decode_and_unchanged_probe_bytes(self):
        probe = copy.deepcopy(self.probe)
        probe["probe"]["decode"]["status"] = "failed"
        with self.assertRaises(ManifestError):
            build_asset(self.media, self.metadata, probe, storage_root=self.root)
        probe["probe"]["decode"]["status"] = "passed"
        probe["probe"]["source_sha256"] = "0" * 64
        with self.assertRaises(ManifestError):
            build_asset(self.media, self.metadata, probe, storage_root=self.root)

    def test_vfr_requires_verified_pts_index(self):
        asset = copy.deepcopy(self.asset)
        asset["probe"]["vfr_status"] = "vfr_observed"
        with self.assertRaises(ManifestError):
            validate_asset(asset, storage_root=self.root)
        pts = self.root / "data" / "pts.jsonl"
        pts.write_text('{"frame_index":0,"pts":0}\n', encoding="utf-8")
        asset["probe"]["pts_index"] = {"relative_path": "data/pts.jsonl",
            "size_bytes": pts.stat().st_size, "sha256": sha256_file(pts)}
        validate_asset(asset, storage_root=self.root)
        pts.write_bytes(b"changed")
        with self.assertRaises(ManifestError):
            validate_asset(asset, storage_root=self.root)

    def test_duplicate_hash_dedup_and_atomic_json(self):
        other = self.media.with_name("duplicate.bin")
        other.write_bytes(self.media.read_bytes())
        duplicate = build_asset(other, self.metadata, self.probe, storage_root=self.root)
        target = self.root / "handoff" / "assets.json"
        result = write_manifest(target, [self.asset, duplicate], storage_root=self.root)
        self.assertEqual(1, len(result["assets"]))
        self.assertEqual(result, json.loads(target.read_text(encoding="utf-8")))
        self.assertEqual([], list(target.parent.glob("*.tmp")))

    def test_conflicting_duplicate_preserves_previous_manifest(self):
        target = self.root / "assets.json"
        write_manifest(target, [self.asset], storage_root=self.root)
        before = target.read_bytes()
        bad = dict(self.asset, match_id="other-match")
        with self.assertRaises(ManifestError):
            write_manifest(target, [self.asset, bad], storage_root=self.root)
        self.assertEqual(before, target.read_bytes())

    def test_same_match_different_bytes_cannot_cross_splits(self):
        other = self.media.with_name("other.bin")
        other.write_bytes(b"another file from same match")
        asset = build_asset(other, dict(self.metadata, split="test"), self.probe, storage_root=self.root)
        with self.assertRaises(ManifestError):
            write_manifest(self.root / "assets.json", [self.asset, asset], storage_root=self.root)

    def test_registry_persists_match_and_hash_invariants(self):
        path = self.root / "registry.json"
        SplitRegistry(path).register(self.asset)
        original = path.read_bytes()
        fresh = SplitRegistry(path)
        for bad in (dict(self.asset, split="train"), dict(self.asset, match_id="other-match")):
            with self.assertRaises(ManifestError):
                fresh.register(bad)
            self.assertEqual(original, path.read_bytes())
        self.assertFalse(fresh.lock_path.exists())

    def test_registry_transaction_and_manifest_stay_unchanged_on_conflict(self):
        registry = SplitRegistry(self.root / "registry.json")
        target = self.root / "assets.json"
        write_manifest(target, [self.asset], storage_root=self.root, registry=registry)
        before = target.read_bytes()
        with self.assertRaises(ManifestError):
            write_manifest(target, [dict(self.asset, split="test")], storage_root=self.root, registry=registry)
        self.assertEqual(before, target.read_bytes())

    def test_registry_serializes_competing_splits(self):
        path = self.root / "registry.json"
        barrier, outcomes = threading.Barrier(2), []
        def run(split):
            barrier.wait()
            try:
                SplitRegistry(path).register(dict(self.asset, split=split))
                outcomes.append("passed")
            except ManifestError:
                outcomes.append("rejected")
        threads = [threading.Thread(target=run, args=(split,)) for split in ("train", "test")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertCountEqual(["passed", "rejected"], outcomes)

    def test_registry_lock_is_not_silently_removed(self):
        registry = SplitRegistry(self.root / "registry.json", lock_timeout_seconds=0.01)
        registry.lock_path.write_text("99999", encoding="ascii")
        with self.assertRaises(ManifestError):
            registry.register(self.asset)
        self.assertTrue(registry.lock_path.exists())

    def test_corrupted_registry_is_not_reset(self):
        path = self.root / "registry.json"
        path.write_text("broken", encoding="ascii")
        with self.assertRaises(ManifestError):
            SplitRegistry(path).register(self.asset)
        self.assertEqual("broken", path.read_text(encoding="ascii"))


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.bin"
        self.path.write_bytes(b"mocked tool input, not actual video")
        self.metadata = {"streams": [{"index": 0, "codec_type": "video", "width": 640,
             "height": 360, "codec_name": "h264", "avg_frame_rate": "30000/1001",
             "r_frame_rate": "30000/1001", "time_base": "1/30000", "duration": "1.001"}],
             "format": {"duration": "2.0"}}
        self.calls = []

    def run_tool(self, args, timeout):
        self.calls.append(args)
        if "-version" in args:
            output = "fftool unit-test mock version\n"
        elif "-show_streams" in args:
            output = json.dumps(self.metadata)
        else:
            output = "frame=30\nprogress=end\n"
        return subprocess.CompletedProcess(args, 0, output, "")

    def test_rational_metadata_and_cpu_decode_without_cfr_claim(self):
        with patch("packages.library.probe._run", side_effect=self.run_tool):
            result = probe_video(self.path, ffprobe="probe-bin", ffmpeg="decode-bin")
        self.assertEqual((30000, 1001, "1/30000"),
                         (result["fps_num"], result["fps_den"], result["time_base"]))
        self.assertEqual(1001, result["duration_ms"])
        self.assertEqual("unknown", result["probe"]["vfr_status"])
        self.assertEqual("passed", result["probe"]["decode"]["status"])
        self.assertEqual(sha256_file(self.path), result["probe"]["source_sha256"])
        decode = self.calls[-1]
        self.assertEqual("none", decode[decode.index("-hwaccel") + 1])
        self.assertIn("-xerror", decode)

    def test_no_video_is_failure(self):
        self.metadata["streams"] = [{"codec_type": "audio"}]
        with patch("packages.library.probe._run", side_effect=self.run_tool), self.assertRaises(ProbeError):
            probe_video(self.path)

    def test_decode_errors_are_failure_even_if_exit_zero(self):
        def fail_decode(args, timeout):
            result = self.run_tool(args, timeout)
            if "-progress" in args:
                result.stderr = "damaged macroblock"
            return result
        with patch("packages.library.probe._run", side_effect=fail_decode), self.assertRaises(ProbeError):
            probe_video(self.path)

    def test_zero_decoded_frames_is_failure(self):
        def zero_decode(args, timeout):
            result = self.run_tool(args, timeout)
            if "-progress" in args:
                result.stdout = "frame=0\nprogress=end\n"
            return result
        with patch("packages.library.probe._run", side_effect=zero_decode), self.assertRaises(ProbeError):
            probe_video(self.path)

    def test_attached_picture_not_a_video(self):
        self.metadata["streams"][0]["disposition"] = {"attached_pic": 1}
        with patch("packages.library.probe._run", side_effect=self.run_tool), self.assertRaises(ProbeError):
            probe_video(self.path)

    def pts_process(self, pts, returncode=0):
        class FakeProcess:
            stdout = io.BytesIO(pts)
            stderr = io.BytesIO(b"decode failure" if returncode else b"")
            def poll(self):
                return returncode
            def wait(self):
                return returncode
            def kill(self):
                pass
        return FakeProcess()

    def create_index(self, raw, **overrides):
        target = Path(self.temp.name) / "index.jsonl"
        params = dict(ffprobe="mock-probe", timeout_seconds=10, max_pts_frames=100,
                      max_pts_bytes=10000, time_base="1/30000", stream_index=1)
        params.update(overrides)
        with patch("packages.library.probe.subprocess.Popen", return_value=self.pts_process(raw)) as call:
            result = _pts_index(self.path, target, Path(self.temp.name), **params)
        self.assertEqual("1", call.call_args.args[0][4])
        return result, target

    def test_complete_pts_index_with_exact_ticks(self):
        result, target = self.create_index(b"0,H.26[45] User Data Unregistered SEI message\n\n1001\n2002\n")
        self.assertEqual("cfr_observed", result["vfr_status"])
        self.assertEqual(3, result["frame_count"])
        self.assertEqual(sha256_file(target), result["sha256"])
        self.assertEqual({"frame_index": 1, "pts": 1001}, json.loads(target.read_text().splitlines()[1]))

    def test_pts_variable_intervals_report_vfr(self):
        result, _ = self.create_index(b"0\n1001\n3003\n")
        self.assertEqual("vfr_observed", result["vfr_status"])

    def test_pts_one_tick_rounding_does_not_claim_vfr(self):
        result, _ = self.create_index(b"0\n33\n67\n")
        self.assertEqual("unknown", result["vfr_status"])

    def test_pts_limits_and_bad_timestamps_never_publish_partial_index(self):
        for raw, kwargs in ((b"0\n1001\n2002\n", {"max_pts_frames": 2}),
                            (b"0\n1001\n2002\n", {"max_pts_bytes": 1}),
                            (b"0\n0\n", {}), (b"0\nN/A\n", {}),
                            (b"0" * 4097, {})):
            with self.subTest(kwargs=kwargs, raw=raw[:30]), self.assertRaises(ProbeError):
                self.create_index(raw, **kwargs)
            self.assertFalse((Path(self.temp.name) / "index.jsonl").exists())
            self.assertEqual([], list(Path(self.temp.name).glob("*.tmp")))

    def test_pts_existing_index_preserved(self):
        target = Path(self.temp.name) / "index.jsonl"
        target.write_bytes(b"previous")
        with self.assertRaises(ProbeError):
            self.create_index(b"0\n1001\n2002\n")
        self.assertEqual(b"previous", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
