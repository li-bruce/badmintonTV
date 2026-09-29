"""Trusted quality inputs: real temporary queue records, no media subprocesses."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts/render"
with patch.object(sys, "path", [str(SCRIPT_DIR), *sys.path]):
    import quality_compare as quality

from packages.contracts import Asset, JobRequest, JobResult
from packages.render.engine import RenderConfig, write_ass
from packages.render.presets import resolve_preset
from packages.render.timeline import RenderError, normalize_timeline
from packages.runtime import Queue


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class QualityInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.fixture_count = 0

    def fixture(self, preview=False, root=None):
        self.fixture_count += 1
        root = root or self.base / f"case-{self.fixture_count}"
        source_path = root / "data/raw/source.mp4"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"ordinary original fixture")
        source = Asset.model_validate({
            "schema_version": "1.0", "asset_id": "source", "relative_path": "data/raw/source.mp4",
            "sha256": digest(source_path.read_bytes()), "size_bytes": source_path.stat().st_size,
            "duration_ms": 1000, "width": 640, "height": 360, "fps_num": 30, "fps_den": 1,
            "match_id": "quality-input-test", "source_type": "synthetic", "usage_scope": "general",
        }).model_dump(mode="json")
        parameters = {"preview": preview, "timeline": {
            "schema_version": "1.0", "timeline_id": "quality-input-test", "title": "Fixture",
            "segments": [{"segment_id": "segment-1", "asset_id": "source", "in_ms": 0,
                          "out_ms": 1000, "review_status": "confirmed"}],
        }}
        payload = {"assets": [source], "parameters": parameters, "render_backend": "cpu", "gpu_required": False}
        queue = Queue(root / "platform/runtime.sqlite3")
        queued = queue.enqueue("render", payload)
        claimed = queue.claim("fixture-worker", 60)
        self.assertEqual(claimed["job_id"], queued["job_id"])
        job_id = queued["job_id"]
        output = root / f"render/jobs/{job_id}/attempt-1"
        output.mkdir(parents=True)
        request = JobRequest.model_validate({
            "schema_version": "1.0", "job_id": job_id, "attempt_id": "attempt-1", "operation": "render",
            "assets": [source], "parameters": parameters, "output_dir": output.relative_to(root).as_posix(),
        }).model_dump(mode="json")
        write_json(output / "request.json", request)
        exchange = root / f"platform/jobs/{job_id}/attempt-1"
        write_json(exchange / "request.json", request)
        media = output / ("preview.mp4" if preview else "export.mp4")
        media.write_bytes(b"ordinary output fixture")
        write_json(output / "timeline.json", parameters["timeline"])
        write_json(output / "source_map.json", {"schema_version": "1.0", "segments": []})
        write_json(output / "qa.json", {"schema_version": "1.0", "preview": preview, "technical_pass": True})
        artifacts = []
        for kind, path in (("video/mp4", media), ("timeline", output / "timeline.json"),
                           ("source_map", output / "source_map.json"), ("qa_report", output / "qa.json")):
            artifacts.append({"schema_version": "1.0", "artifact_id": "artifact-" + kind.replace("/", "-"),
                "kind": kind, "relative_path": path.relative_to(root).as_posix(), "sha256": digest(path.read_bytes()),
                "size_bytes": path.stat().st_size, "created_at": "2026-09-29T00:00:00+00:00",
                "producer": "badmintonTV.render/0.1.0"})
        result = JobResult.model_validate({"schema_version": "1.0", "job_id": job_id, "attempt_id": "attempt-1",
            "status": "succeeded", "artifacts": artifacts, "events": [], "error": None}).model_dump(mode="json")
        result["exit_code"] = 0
        write_json(exchange / "result.json", result)
        queue.finish(job_id, "fixture-worker", "succeeded", result=result, expected_attempt=1)
        return SimpleNamespace(root=root, output=output, media=media, source_path=source_path,
                               queue=queue, job_id=job_id, request=request, result=result, payload=payload)

    def set_row(self, fixture, **changes):
        allowed = {"operation", "status", "attempt", "payload", "result"}
        self.assertTrue(set(changes) <= allowed)
        with fixture.queue.connection(write=True) as db:
            for column, value in changes.items():
                encoded = json.dumps(value) if column in {"payload", "result"} and value is not None else value
                db.execute(f"UPDATE jobs SET {column}=? WHERE job_id=?", (encoded, fixture.job_id))

    def registry(self, fixture, contents=b"registered training original"):
        entry = {"asset_id": "registered-training", "relative_path": "data/training/set/original.mp4",
                 "sha256": digest(contents), "usage_scope": "training_only"}
        write_json(fixture.root / "data/training/handoff/training-registry.v1.json",
                   {"schema_version": "1.0", "assets": [entry]})
        return entry

    def invoke(self, fixture, expected_code=None):
        row_before = fixture.queue.get(fixture.job_id)
        files_before = {path: path.read_bytes() for path in fixture.output.iterdir() if path.is_file()}
        with patch.object(quality.subprocess, "run") as run, \
                patch.object(quality.subprocess, "Popen") as popen, patch.object(quality, "reservation") as reserve:
            if expected_code is None:
                result = quality.verify_job_artifacts(fixture.output, fixture.root)
            else:
                with self.assertRaises(RenderError) as error:
                    quality.verify_job_artifacts(fixture.output, fixture.root)
                self.assertEqual(error.exception.code, expected_code)
                result = None
        run.assert_not_called()
        popen.assert_not_called()
        reserve.assert_not_called()
        self.assertEqual(fixture.queue.get(fixture.job_id), row_before)
        self.assertEqual({path: path.read_bytes() for path in fixture.output.iterdir() if path.is_file()}, files_before)
        return result

    def reference_sidecars(self, fixture):
        """Produce ASS with the real pure renderer and one accepted command fixture."""
        params = fixture.request["parameters"]
        preset = resolve_preset(params, params["timeline"].get("output"))
        timeline = deepcopy(params["timeline"])
        timeline["output"] = preset["output"]
        assets = {source["asset_id"]: source for source in fixture.request["assets"]}
        normalized = normalize_timeline(timeline, assets, preview=params["preview"])
        normalized["render_metadata"]["preset"] = preset
        sidecar = fixture.output / "segment-000.ass"
        write_ass(sidecar, normalized, normalized["segments"][0], 0, 1, RenderConfig().font_name)
        vf = ("bwdif=mode=send_frame:parity=auto:deint=interlaced,setpts=PTS/1,"
              "scale=trunc(iw*sar/2)*2:ih,setsar=1,"
              "scale=1080:1112:force_original_aspect_ratio=decrease:force_divisible_by=2,"
              "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x121a26,setsar=1,"
              "fps=30:start_time=0,tpad=stop_mode=clone:stop_duration=1,"
              "trim=end_frame=30,setpts=N/(30*TB),subtitles=segment-000.ass,format=yuv420p,setfield=prog")
        timings = [{"stage": "segment:1", "returncode": 0, "elapsed_seconds": 0.1,
                    "argv": ["mock-ffmpeg", "-ss", "0", "-t", "1", "-i", str(fixture.source_path),
                             "-map", "0:0", "-vf", vf, "-t", "1", "segment-000.partial.mov"]}]
        write_json(fixture.output / "stage_timings.json", timings)
        qa = json.loads((fixture.output / "qa.json").read_text(encoding="utf-8"))
        qa.update(preset=preset, stage_timings=timings)
        write_json(fixture.output / "qa.json", qa)
        # The fixture's trusted result must bind this newly prepared QA before
        # any test mutates unregistered sidecars.
        qa_artifact = next(a for a in fixture.result["artifacts"] if a["kind"] == "qa_report")
        qa_artifact.update(sha256=digest((fixture.output / "qa.json").read_bytes()),
                           size_bytes=(fixture.output / "qa.json").stat().st_size)
        self.set_row(fixture, result=fixture.result)
        bound = self.invoke(fixture)
        return SimpleNamespace(bound=bound, qa=qa, timings=timings, sidecar=sidecar)

    def test_general_completed_job_binds_sources_artifacts_and_preview_filename(self):
        for preview in (False, True):
            with self.subTest(preview=preview):
                fixture = self.fixture(preview=preview)
                verified = self.invoke(fixture)
                self.assertEqual(verified["request"], fixture.request)
                self.assertEqual(verified["verified_sources"]["source"], fixture.source_path)
                self.assertEqual(verified["media"], fixture.media)
                self.assertEqual(set(verified["artifacts"]), {"video/mp4", "timeline", "source_map", "qa_report"})
                self.assertEqual(verified["trusted_job"]["job_id"], fixture.job_id)
                self.assertEqual(verified["trusted_job"]["attempt_id"], "attempt-1")
                self.assertEqual(verified["trusted_job"]["ledger_relative_path"], "platform/runtime.sqlite3")
                self.assertEqual(verified["trusted_job"]["verified_artifact_sha256"]["video/mp4"], digest(fixture.media.read_bytes()))

    def test_replaced_registered_training_bytes_are_rejected_before_hash_or_size_mismatch(self):
        for same_size in (True, False):
            with self.subTest(same_size=same_size):
                fixture = self.fixture()
                replacement = b"T" * (fixture.media.stat().st_size + (0 if same_size else 7))
                self.registry(fixture, replacement)
                fixture.media.write_bytes(replacement)
                self.invoke(fixture, "TRAINING_ONLY")

    def test_ordinary_same_size_media_replacement_is_an_artifact_mismatch(self):
        fixture = self.fixture()
        fixture.media.write_bytes(b"X" * fixture.media.stat().st_size)
        self.invoke(fixture, "artifact_mismatch")

    def test_worker_identity_operation_status_and_attempt_are_authoritative(self):
        for change in ({"status": "cancelled"}, {"status": "failed"}, {"attempt": 2}, {"operation": "model"}):
            with self.subTest(change=change):
                fixture = self.fixture()
                self.set_row(fixture, **change)
                self.invoke(fixture, "quality_job_mismatch")

    def test_local_request_cannot_change_job_attempt_output_assets_or_parameters(self):
        for field in ("job_id", "attempt_id", "output_dir", "assets", "parameters"):
            with self.subTest(field=field):
                fixture = self.fixture()
                request = deepcopy(fixture.request)
                if field == "assets":
                    request[field][0]["title"] = "request metadata changed"
                elif field == "parameters":
                    request[field]["timeline"]["title"] = "request parameters changed"
                else:
                    request[field] = {"job_id": "wrong-job", "attempt_id": "attempt-2",
                                      "output_dir": "render/jobs/other/attempt-1"}[field]
                write_json(fixture.output / "request.json", request)
                self.invoke(fixture, "quality_job_mismatch")

    def test_trusted_result_must_match_job_attempt_success_and_exit_zero(self):
        for field, value in (("job_id", "wrong-job"), ("attempt_id", "attempt-2"),
                             ("status", "cancelled"), ("exit_code", 1)):
            with self.subTest(field=field):
                fixture = self.fixture()
                result = deepcopy(fixture.result)
                result[field] = value
                self.set_row(fixture, result=result)
                self.invoke(fixture, "quality_job_mismatch")

    def test_missing_or_duplicate_required_artifact_kinds_are_rejected(self):
        for mode in ("missing", "duplicate"):
            with self.subTest(mode=mode):
                fixture = self.fixture()
                result = deepcopy(fixture.result)
                if mode == "missing":
                    result["artifacts"].pop()
                else:
                    result["artifacts"][1]["kind"] = "video/mp4"
                self.set_row(fixture, result=result)
                self.invoke(fixture, "artifact_mismatch")

    def test_artifact_size_hash_and_filename_are_bound_to_the_completed_output(self):
        for field in ("size_bytes", "sha256", "relative_path"):
            with self.subTest(field=field):
                fixture = self.fixture()
                result = deepcopy(fixture.result)
                video = result["artifacts"][0]
                if field == "size_bytes":
                    video[field] += 1
                elif field == "sha256":
                    video[field] = "0" * 64
                else:
                    other = fixture.root / "render/jobs/other/attempt-1/export.mp4"
                    other.parent.mkdir(parents=True)
                    other.write_bytes(fixture.media.read_bytes())
                    video[field] = other.relative_to(fixture.root).as_posix()
                self.set_row(fixture, result=result)
                self.invoke(fixture, "artifact_mismatch")

    def test_producer_scope_and_source_lineage_cannot_downgrade_training_restrictions(self):
        for mode in ("scope", "provenance", "source-id", "source-hash"):
            with self.subTest(mode=mode):
                fixture = self.fixture()
                entry = self.registry(fixture)
                producer = {"name": "test-renderer"}
                if mode == "scope":
                    producer["usage_scope"] = "training_only"
                elif mode == "provenance":
                    producer["provenance"] = {"usage_scope": "training_only"}
                elif mode == "source-id":
                    producer["source_asset_id"] = entry["asset_id"]
                else:
                    producer["source_sha256"] = entry["sha256"]
                result = deepcopy(fixture.result)
                result["artifacts"][0]["producer"] = producer
                self.set_row(fixture, result=result)
                self.invoke(fixture, "TRAINING_ONLY")

    def test_registered_stage_commands_and_reconstructed_ass_are_accepted(self):
        fixture = self.fixture()
        reference = self.reference_sidecars(fixture)
        commands = quality.segment_commands(fixture.output, 1, reference.qa["stage_timings"])
        self.assertEqual(commands[0]["input"], str(fixture.source_path))
        self.assertEqual(commands[0]["ass_sha256"], digest(reference.sidecar.read_bytes()))
        quality.verify_reference_sidecars(fixture.output, reference.bound, reference.qa)

    def test_local_stage_timings_cannot_change_registered_commands_or_outcomes(self):
        fixture = self.fixture()
        reference = self.reference_sidecars(fixture)
        for field in ("argv", "returncode", "elapsed_seconds"):
            with self.subTest(field=field):
                changed = deepcopy(reference.timings)
                if field == "argv":
                    changed[0][field][2] = "0.25"  # Different source seek.
                else:
                    changed[0][field] = 1
                write_json(fixture.output / "stage_timings.json", changed)
                with self.assertRaises(RenderError) as error:
                    quality.segment_commands(fixture.output, 1, reference.qa["stage_timings"])
                self.assertEqual(error.exception.code, "artifact_mismatch")

    def test_identical_ass_tampering_on_both_sides_still_fails_request_reconstruction(self):
        cpu = self.fixture()
        nvenc = self.fixture(root=cpu.root)
        references = [self.reference_sidecars(fixture) for fixture in (cpu, nvenc)]
        self.assertEqual(references[0].sidecar.read_bytes(), references[1].sidecar.read_bytes())
        for reference in references:
            original = reference.sidecar.read_text(encoding="utf-8")
            self.assertIn("Fixture", original)
            reference.sidecar.write_text(original.replace("Fixture", "Untrusted title"), encoding="utf-8")
        self.assertEqual(references[0].sidecar.read_bytes(), references[1].sidecar.read_bytes())
        for fixture, reference in zip((cpu, nvenc), references):
            with self.subTest(job=fixture.job_id), self.assertRaises(RenderError) as error:
                quality.verify_reference_sidecars(fixture.output, reference.bound, reference.qa)
            self.assertEqual(error.exception.code, "artifact_mismatch")

    def test_missing_ass_sidecar_is_rejected(self):
        fixture = self.fixture()
        reference = self.reference_sidecars(fixture)
        reference.sidecar.unlink()
        with self.assertRaises(RenderError) as error:
            quality.verify_reference_sidecars(fixture.output, reference.bound, reference.qa)
        self.assertEqual(error.exception.code, "artifact_mismatch")

    def test_ass_reached_through_real_directory_alias_is_rejected(self):
        fixture = self.fixture()
        reference = self.reference_sidecars(fixture)
        alias = fixture.root / "render/reference-alias"
        self.assertTrue(alias.parent.resolve().is_relative_to(self.base))
        self.assertTrue(fixture.output.resolve().is_relative_to(self.base))
        try:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(fixture.output), str(alias))
            else:
                alias.symlink_to(fixture.output, target_is_directory=True)
        except (AttributeError, NotImplementedError, OSError) as exc:
            self.skipTest(f"Creating directory junctions/links unavailable: {exc}")
        try:
            self.assertEqual((alias / reference.sidecar.name).read_bytes(), reference.sidecar.read_bytes())
            with self.assertRaises(RenderError) as error:
                quality.verify_reference_sidecars(alias, reference.bound, reference.qa)
            self.assertEqual(error.exception.code, "artifact_mismatch")
        finally:
            if os.name == "nt":
                os.rmdir(alias)
            else:
                alias.unlink()
        self.assertTrue(reference.sidecar.is_file())

    def test_preflight_rejects_sidecar_tampering_before_version_processes_or_reservation(self):
        cpu = self.fixture()
        nvenc = self.fixture(root=cpu.root)
        reference = self.reference_sidecars(cpu)
        self.reference_sidecars(nvenc)
        reference.sidecar.write_text("untrusted ASS replacement", encoding="utf-8")
        args = SimpleNamespace(storage_root=cpu.root, cpu_output=cpu.output, nvenc_output=nvenc.output,
                               environment=cpu.root / "must-not-read-environment.json")
        configured_root = "D:/video" if os.name == "nt" else "/mnt/d/video"

        def local_path(value):
            # Substitute only the fixed deployment root. Real path resolution,
            # SQLite binding, artifact hashing and sidecar checking remain live.
            return cpu.root if str(value) == configured_root else Path(value)

        with patch.object(quality, "Path", side_effect=local_path), \
                patch.object(quality, "verify_job_artifacts", wraps=quality.verify_job_artifacts) as bind, \
                patch.object(quality, "verify_reference_sidecars", wraps=quality.verify_reference_sidecars) as sidecars, \
                patch.object(quality.subprocess, "run") as run, patch.object(quality.subprocess, "Popen") as popen, \
                patch.object(quality, "reservation") as reserve, self.assertRaises(RenderError) as error:
            quality.preflight(args)
        self.assertEqual(error.exception.code, "artifact_mismatch")
        self.assertIn("ASS differs", str(error.exception))
        self.assertEqual(bind.call_count, 2)
        sidecars.assert_called_once()
        run.assert_not_called()
        popen.assert_not_called()
        reserve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
