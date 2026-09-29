"""CPU-only transfer/protection guards; no downloads, installs, GPU or D: writes."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.models import acquire_vl_wheelhouse as wheels
from scripts.models import range_transfer


def entry(data=b"complete wheel fixture", name="fixture-1.0-cp311-cp311-manylinux_2_28_x86_64.whl"):
    return {"filename": name, "url": "https://files.pythonhosted.org/packages/fixed/"+name,
            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def manifest(*entries):
    return {"schema_version": "1.0", "platform": "linux_x86_64", "python": "cp311", "files": list(entries or [entry()])}


class WheelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="vl-wheelhouse-cpu-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root/"wheelhouse"
        self.destination.mkdir()

    def write_json(self, name, value):
        path = self.root/name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_actual_reviewed_core_manifest_is_accepted_without_network(self):
        path = Path(__file__).resolve().parents[2]/"docs/models/vl-linux-cp311-wheels.json"
        data, _ = wheels.read_json(path)
        with patch.object(wheels.urllib.request, "urlopen") as network:
            entries = wheels.validate_manifest(data)
        network.assert_not_called()
        self.assertEqual(len(entries), 17)
        self.assertEqual(sum(e["size_bytes"] for e in entries), 3_916_256_631)

    def test_linux_and_pure_python_tags_only(self):
        for name in ("a-1-cp311-cp311-linux_x86_64.whl", "a-1-py3-none-any.whl",
                     "a-1-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"):
            wheels.validate_manifest(manifest(entry(name=name)))
        for name in ("a-1-cp310-cp310-linux_x86_64.whl", "a-1-cp311-cp311-win_amd64.whl",
                     "a-1-py3-none-manylinux_2_17_aarch64.whl", "a-1-py3-none-macosx_11_0_x86_64.whl",
                     "../a-1-py3-none-any.whl", "a:1-py3-none-any.whl"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                wheels.validate_manifest(manifest(entry(name=name)))

    def test_domain_filename_size_sha_and_duplicate_guards(self):
        good = entry()
        for update in ({"url": "http://files.pythonhosted.org/"+good["filename"]},
                       {"url": "https://files.pythonhosted.org.evil.invalid/"+good["filename"]},
                       {"url": "https://user@download.pytorch.org/"+good["filename"]},
                       {"url": "https://download.pytorch.org/other.whl"},
                       {"size_bytes": True}, {"size_bytes": 0}, {"sha256": "0"*63}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                wheels.validate_manifest(manifest({**good, **update}))
        with self.assertRaises(ValueError):
            wheels.validate_manifest(manifest(good, good.copy()))
        altered = manifest(good)
        altered["platform"] = "win_amd64"
        with self.assertRaises(ValueError):
            wheels.validate_manifest(altered)

    def test_redirect_cannot_escape_the_official_hosts(self):
        handler = wheels.TrustedRedirects()
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, "", {}, "https://example.invalid/other.whl")

    def test_existing_complete_skips_network_and_wrong_file_is_preserved(self):
        e = entry()
        target = self.destination/e["filename"]
        target.write_bytes(b"complete wheel fixture")
        with patch.object(wheels, "append_ranges") as network:
            result = wheels.acquire_one(e, self.destination, 4)
        network.assert_not_called()
        self.assertEqual(result["sha256"], e["sha256"])
        target.write_bytes(b"wrong")
        with self.assertRaises(ValueError):
            wheels.acquire_one(e, self.destination, 4)
        self.assertEqual(target.read_bytes(), b"wrong")

    def test_unknown_or_different_source_partial_is_never_replaced(self):
        e = entry()
        target = self.destination/e["filename"]
        partial = target.with_name(target.name+".partial")
        partial.write_bytes(b"prefix")
        with self.assertRaises(ValueError):
            wheels.acquire_one(e, self.destination, 4)
        self.assertEqual(partial.read_bytes(), b"prefix")
        marker = partial.with_name(partial.name+".source.json")
        marker.write_text(json.dumps({**wheels.identity(e), "sha256": "0"*64}))
        with self.assertRaises(ValueError):
            wheels.acquire_one(e, self.destination, 4)
        self.assertEqual(partial.read_bytes(), b"prefix")
        self.assertFalse(target.exists())

    def test_real_range_helper_and_final_sha_publication(self):
        data = bytes(range(39))
        e = entry(data)
        requests = []
        class Response(io.BytesIO):
            status = 206
            def __init__(self, start, end):
                super().__init__(data[start:end+1])
                self.headers = {"Content-Range": f"bytes {start}-{end}/{len(data)}", "Content-Length": str(end-start+1)}
        def server(request, timeout):
            start, end = map(int, request.get_header("Range")[6:].split("-"))
            requests.append((start, end))
            return Response(start, end)
        real_append = range_transfer.append_ranges
        def small_chunks(*args, **kwargs):
            self.assertEqual(kwargs.pop("chunk_bytes"), 8_388_608)
            return real_append(*args, chunk_bytes=4, **kwargs)
        with patch.object(wheels, "append_ranges", side_effect=small_chunks), \
             patch.object(range_transfer.urllib.request, "urlopen", side_effect=server), redirect_stdout(io.StringIO()):
            result = wheels.acquire_one(e, self.destination, 4)
        self.assertEqual((self.destination/e["filename"]).read_bytes(), data)
        self.assertEqual(result["sha256"], e["sha256"])
        self.assertEqual(sorted(requests), [(i, min(i+3, 38)) for i in range(0, 39, 4)])

    def test_full_size_wrong_sha_partial_is_not_published(self):
        e = entry(b"wanted")
        target = self.destination/e["filename"]
        partial = target.with_name(target.name+".partial")
        partial.write_bytes(b"broken")
        partial.with_name(partial.name+".source.json").write_text(json.dumps(wheels.identity(e)))
        with redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            wheels.acquire_one(e, self.destination, 4)
        self.assertFalse(target.exists())
        self.assertEqual(partial.read_bytes(), b"broken")

    def test_pause_does_not_publish_a_partial(self):
        e = entry()
        (self.destination/"PAUSE").touch()
        with patch.object(wheels.urllib.request, "urlopen") as network, redirect_stdout(io.StringIO()):
            result = wheels.acquire_one(e, self.destination, 4)
        network.assert_not_called()
        self.assertEqual(result["status"], "paused")
        self.assertFalse((self.destination/e["filename"]).exists())

    def test_preservation_scan_is_read_only_and_partial_names_are_ignored(self):
        source = self.root/"vl-tmp"
        source.mkdir()
        e = entry()
        nested = source/"pip-unpack-existing"
        nested.mkdir()
        complete = nested/e["filename"]
        complete.write_bytes(b"complete wheel fixture")
        (source/(e["filename"]+".partial")).write_bytes(b"complete wheel fixture")
        wrong = source/e["filename"]
        wrong.write_bytes(b"incomplete")
        empty_target = self.root/"not-created"
        overview, verified = wheels.plan([e], empty_target, source)
        self.assertFalse(empty_target.exists())
        self.assertEqual(len(overview["candidates"]), 2)
        self.assertEqual(verified[e["filename"]], complete)
        self.assertEqual(overview["additional_download_bytes"], 0)
        self.assertEqual(wrong.read_bytes(), b"incomplete")

    def test_complete_hardlink_survives_source_cleanup_and_never_overwrites(self):
        e = entry()
        source = self.root/e["filename"]
        source.write_bytes(b"complete wheel fixture")
        target = self.destination/e["filename"]
        wheels.protect_complete(source, target, e)
        self.assertTrue(os.path.samefile(source, target))
        source.unlink()  # simulate pip cleaning up its own link, only in this temp fixture
        self.assertEqual(target.read_bytes(), b"complete wheel fixture")
        target.write_bytes(b"existing preserved")
        with self.assertRaises(ValueError):
            wheels.protect_complete(source, target, e)
        self.assertEqual(target.read_bytes(), b"existing preserved")

    def test_preflight_is_required_and_is_only_recorded_external_evidence(self):
        record = {"passed": True, "checks": {k: True for k in wheels.PREFLIGHT_CHECKS}, "additional_models_peak_bytes": 500}
        path = self.write_json("preflight.json", record)
        with self.assertRaises(ValueError):
            wheels.approved_preflight(None, 1)
        with self.assertRaises(ValueError):
            wheels.approved_preflight(path, 501)
        result = wheels.approved_preflight(path, 500)
        self.assertIn("did not measure", result["scope"])
        record["checks"]["models_35GB"] = False
        self.write_json("preflight.json", record)
        with self.assertRaises(ValueError):
            wheels.approved_preflight(path, 1)

    def test_existing_lock_is_preserved_and_owned_lock_is_released(self):
        lock = self.destination/".wheelhouse-writer.json"
        lock.write_text('{"token":"someone-else"}')
        with self.assertRaises(FileExistsError), wheels.writer_lock(self.destination):
            self.fail("an existing lock was acquired")
        self.assertEqual(json.loads(lock.read_text())["token"], "someone-else")
        lock.unlink()
        with self.assertRaises(RuntimeError):
            with wheels.writer_lock(self.destination):
                raise RuntimeError("fixture failure")
        self.assertFalse(lock.exists())

    @unittest.skipUnless(os.name == "nt", "CLI is native Windows only")
    def test_cli_default_dry_run_and_missing_approval_make_no_directory(self):
        path = self.write_json("manifest.json", manifest())
        target = self.root/"absent-target"
        with patch.object(wheels, "DESTINATION", target), patch.object(wheels.urllib.request, "urlopen") as network, redirect_stdout(io.StringIO()):
            self.assertEqual(wheels.main(["--manifest", str(path)]), 0)
            with self.assertRaises(ValueError):
                wheels.main(["--manifest", str(path), "--execute"])
        self.assertFalse(target.exists())
        network.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "CLI is native Windows only")
    def test_execute_existing_complete_records_external_preflight_and_unlocks(self):
        e = entry()
        (self.destination/e["filename"]).write_bytes(b"complete wheel fixture")
        path = self.write_json("manifest.json", manifest(e))
        budget = self.write_json("preflight.json", {"passed": True, "checks": {k: True for k in wheels.PREFLIGHT_CHECKS},
                                                   "additional_models_peak_bytes": wheels.METADATA_ALLOWANCE})
        with patch.object(wheels, "DESTINATION", self.destination), patch.object(wheels.urllib.request, "urlopen") as network, \
             patch.object(wheels.shutil, "disk_usage", return_value=type("Usage", (), {"free": 10_000_000_000})()), redirect_stdout(io.StringIO()):
            self.assertEqual(wheels.main(["--manifest", str(path), "--execute", "--approved-runtime-manifest", str(budget)]), 0)
        network.assert_not_called()
        self.assertFalse((self.destination/".wheelhouse-writer.json").exists())
        receipts = list(self.destination.glob("acquisition-*.json"))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        self.assertEqual(receipt["files"][0]["sha256"], e["sha256"])
        self.assertIn("did not measure", receipt["runtime_preflight"]["scope"])


if __name__ == "__main__":
    unittest.main()
