import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from packages.models import training_sources as sources


class FakeFrame:
    """Only exercises decoder guards; never stands for real video evidence."""
    def __init__(self, pts, *, width=64, height=32, shape=(32, 64, 3)):
        self.pts, self.width, self.height = pts, width, height
        self.time_base = Fraction(1, 1000)
        self.to_ndarray = Mock(return_value=SimpleNamespace(
            shape=shape, dtype="uint8", nbytes=64 * 32 * 3,
            tobytes=lambda: b"\x00" * (64 * 32 * 3)))


class FakeContainer:
    def __init__(self, frames):
        self.streams = SimpleNamespace(video=[SimpleNamespace(time_base=Fraction(1, 1000), start_time=900)])
        self.frames = frames

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def seek(self, *args, **kwargs):
        pass

    def decode(self, stream):
        return iter(self.frames)


class TrainingSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        folder = self.root / "data/training"
        folder.mkdir(parents=True)
        media = folder / "fixture.bin"
        media.write_bytes(b"synthetic source identity test, not decoded video")
        index = folder / "fixture.pts.jsonl"
        index.write_text("".join(json.dumps({"frame_index": i, "pts": n})+'\n'
                                 for i, n in enumerate([900, 933, 985, 1035])), encoding="utf-8")
        def ref(path):
            raw = path.read_bytes()
            return {"relative_path": path.relative_to(self.root).as_posix(), "size_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest()}
        self.asset = {"asset_id": "synthetic-fixture", **ref(media), "duration_ms": 180,
                      "time_base": "1/1000", "width": 64, "height": 32,
                      "probe": {"start_pts": 900, "source_sha256": ref(media)["sha256"],
                                "source_size_bytes": media.stat().st_size,
                                "pts_index": {**ref(index), "format": "jsonl", "complete": True,
                                              "time_base": "1/1000", "frame_count": 4}}}

    def test_vfr_origin_and_half_open_window_use_pts_not_fps(self):
        v = sources.verify_asset(self.root, self.asset)
        self.assertEqual(v["times"], [Fraction(x, 1000) for x in [0, 33, 85, 135]])
        p = sources.plan_window(v, 33, 135, sample_count=2)
        self.assertEqual(p["source_frame_count"], 2)
        self.assertEqual([r["pts"] for r in p["frames"]], [933, 985])
        self.assertEqual(p["frames"][1]["source_ms_rational"], "85")

    def test_source_tampering_rejected(self):
        path = self.root / self.asset["relative_path"]
        path.write_bytes(b"x"*path.stat().st_size)
        with self.assertRaisesRegex(sources.SourceError, "SHA256 mismatch"):
            sources.verify_asset(self.root, self.asset)

    def test_missing_origin_and_unbound_probe_rejected(self):
        self.asset["probe"]["start_pts"] = None
        with self.assertRaisesRegex(sources.SourceError, "start_pts"):
            sources.verify_asset(self.root, self.asset)
        self.asset["probe"]["start_pts"] = 900
        self.asset["probe"]["source_sha256"] = "0"*64
        with self.assertRaisesRegex(sources.SourceError, "bound"):
            sources.verify_asset(self.root, self.asset)

    def test_index_count_and_completeness_rejected(self):
        self.asset["probe"]["pts_index"]["frame_count"] = 5
        with self.assertRaisesRegex(sources.SourceError, "count"):
            sources.verify_asset(self.root, self.asset)
        self.asset["probe"]["pts_index"]["complete"] = False
        with self.assertRaisesRegex(sources.SourceError, "complete"):
            sources.verify_asset(self.root, self.asset)

    def test_excess_size_and_root_escape_rejected(self):
        with self.assertRaisesRegex(sources.SourceError, "excessive"):
            sources.verify_asset(self.root, self.asset, max_source_bytes=1)
        self.asset["relative_path"] = "../outside.bin"
        with self.assertRaises(ValueError):
            sources.verify_asset(self.root, self.asset)

    def test_sparse_sampling_never_duplicates_or_synthesizes_frames(self):
        v = sources.verify_asset(self.root, self.asset)
        p = sources.plan_window(v, 0, 180, sample_count=8)
        self.assertTrue(p["missing_or_duplicate_target_indices"])
        self.assertEqual(len({r["pts"] for r in p["frames"]}), len(p["frames"]))
        with self.assertRaisesRegex(sources.SourceError, "no source frames"):
            sources.plan_window(v, 140, 170)

    def test_nonfinite_duplicate_keys_and_json_size_rejected(self):
        for value in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e9999}'):
            with self.assertRaises(ValueError):
                sources.parse_json(value)
        with self.assertRaisesRegex(sources.SourceError, "byte limit"):
            sources.read_json(self.root/self.asset["relative_path"], limit=1)

    def test_canonical_output_is_deterministic(self):
        self.assertEqual(sources.canonical_bytes({"b":2,"a":1}), sources.canonical_bytes({"a":1,"b":2}))

    def replace_index(self, raw, count=1):
        reference = self.asset["probe"]["pts_index"]
        (self.root / reference["relative_path"]).write_bytes(raw)
        reference.update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), frame_count=count)

    def test_index_lines_are_bounded_before_allocation(self):
        self.replace_index(b" " * 20_000)
        index_path = self.root / self.asset["probe"]["pts_index"]["relative_path"]
        original_open, sizes = Path.open, []

        class GuardedReader:
            def __init__(self, stream):
                self.stream = stream

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def __iter__(self):
                raise AssertionError("Unbounded JSONL iteration")

            def readline(self, size=-1):
                if not 0 < size <= 4097:
                    raise AssertionError("Unbounded readline")
                sizes.append(size)
                return self.stream.readline(size)

        def guarded_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return GuardedReader(stream) if path == index_path else stream

        with patch.object(Path, "open", guarded_open), self.assertRaisesRegex(sources.SourceError, "line bound"):
            sources.verify_asset(self.root, self.asset)
        self.assertEqual(sizes, [4097])

    def test_nonobject_index_rows_and_invalid_dimensions_rejected(self):
        original = copy.deepcopy(self.asset)
        for row in ([], None, True):
            self.replace_index(json.dumps(row).encode() + b"\n")
            with self.subTest(row=row), self.assertRaisesRegex(sources.SourceError, "row must be an object"):
                sources.verify_asset(self.root, self.asset)
        for width, height in ((-64, -32), (True, 32), (1, 0), (3840, 2161)):
            self.asset = copy.deepcopy(original)
            self.asset.update(width=width, height=height)
            with self.subTest(dimensions=(width, height)), self.assertRaisesRegex(sources.SourceError, "dimensions"):
                sources.verify_asset(self.root, self.asset)

    def test_decode_rehashes_source_before_opening_av(self):
        verified = sources.verify_asset(self.root, self.asset)
        plan = sources.plan_window(verified, 0, 180, sample_count=2)
        path = verified["source_path"]
        path.write_bytes(b"x" * path.stat().st_size)
        fake_av = SimpleNamespace(open=Mock())
        with patch.dict(sys.modules, {"av": fake_av}), self.assertRaisesRegex(sources.SourceError, "SHA256 mismatch"):
            sources.decode_window(verified, plan)
        fake_av.open.assert_not_called()

    def test_decode_uses_verified_handle_and_rejects_plan_tampering(self):
        verified = sources.verify_asset(self.root, self.asset)
        plan = sources.plan_window(verified, 0, 180, sample_count=2)
        received = []

        def open_av(source, **kwargs):
            self.assertTrue(hasattr(source, "fileno"))
            self.assertEqual(source.tell(), 0)
            self.assertEqual(hashlib.sha256(source.read()).hexdigest(), self.asset["sha256"])
            source.seek(0)
            received.append(source)
            return FakeContainer([FakeFrame(n) for n in [900, 933, 985, 1035]])

        fake_av = SimpleNamespace(open=Mock(side_effect=open_av), __version__="CPU-test-double")
        with patch.dict(sys.modules, {"av": fake_av}):
            result = sources.decode_window(verified, plan)
            self.assertEqual([row["pts"] for row in result["frames"]], [900, 1035])
            self.assertFalse(result["images_written"])
            self.assertTrue(received[0].closed)
            plan["frames"][0]["frame_index"] = 3
            with self.assertRaisesRegex(sources.SourceError, "plan differs"):
                sources.decode_window(verified, plan)
        self.assertEqual(fake_av.open.call_count, 1)

    def test_decode_checks_unselected_pts_dimensions_and_rgb(self):
        verified = sources.verify_asset(self.root, self.asset)
        plan = sources.plan_window(verified, 0, 180, sample_count=2)
        cases = [
            ([FakeFrame(900), FakeFrame(934), FakeFrame(1035)], "absent"),
            ([FakeFrame(900), FakeFrame(985), FakeFrame(1035)], "consecutive"),
            ([FakeFrame(900), FakeFrame(933, width=128), FakeFrame(1035)], "dimensions"),
            ([FakeFrame(900, shape=(32, 64, 4))], "RGB shape"),
        ]
        for frames, message in cases:
            fake_av = SimpleNamespace(open=Mock(return_value=FakeContainer(frames)), __version__="CPU-test-double")
            with self.subTest(message=message), patch.dict(sys.modules, {"av": fake_av}), \
                    self.assertRaisesRegex(sources.SourceError, message):
                sources.decode_window(verified, plan)

    def test_source_mutation_during_decode_rejected(self):
        verified = sources.verify_asset(self.root, self.asset)
        plan = sources.plan_window(verified, 0, 180, sample_count=2)

        def changing_frames():
            yield FakeFrame(900)
            with verified["source_path"].open("r+b") as stream:
                stream.write(b"changed")
            for pts in (933, 985, 1035):
                yield FakeFrame(pts)

        fake_av = SimpleNamespace(open=Mock(return_value=FakeContainer(changing_frames())), __version__="CPU-test-double")
        with patch.dict(sys.modules, {"av": fake_av}), self.assertRaisesRegex(sources.SourceError, "changed during CPU"):
            sources.decode_window(verified, plan)


if __name__ == "__main__":
    unittest.main()
