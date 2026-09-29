"""R-04b renderer integration: production-use denial precedes editing and media I/O."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from packages.render.engine import RenderConfig, render
from packages.render.storage import sha256
from packages.render.timeline import RenderError, normalize_timeline


REGISTRY_PATH = "data/training/handoff/training-registry.v1.json"
PROGRESS_FIELDS = {"schema_version", "job_id", "seq", "event", "stage", "current", "total", "unit", "message"}


def asset(asset_id="ordinary", **changes):
    value = {
        "schema_version": "1.0", "asset_id": asset_id,
        "relative_path": f"data/raw/{asset_id}.mp4", "sha256": "a" * 64,
        "size_bytes": 10, "duration_ms": 1000, "width": 640, "height": 360,
        "fps_num": 25, "fps_den": 1, "source_type": "synthetic",
        "match_id": "usage-test", "rights": {"status": "owned"}, "split": "unassigned",
    }
    value.update(changes)
    return value


def request_fixture(*assets, **parameters):
    assets = list(assets or [asset()])
    return {
        "schema_version": "1.0", "job_id": "usage-test-job", "attempt_id": "attempt-1",
        "operation": "render", "output_dir": "render/jobs/usage-test-job/attempt-1",
        "assets": assets,
        "parameters": {
            "timeline": {"schema_version": "1.0", "timeline_id": "usage-test-timeline", "segments": [
                {"segment_id": f"segment-{index}", "asset_id": source["asset_id"],
                 "in_ms": 0, "out_ms": 1000, "review_status": "confirmed"}
                for index, source in enumerate(assets)
            ]},
            **parameters,
        },
    }


class UsageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = RenderConfig(storage_root=self.root,
                                   ffmpeg=str(self.root / "not-installed-ffmpeg.exe"),
                                   ffprobe=str(self.root / "not-installed-ffprobe.exe"))

    def publish_registry(self, entries=()):
        path = self.root / REGISTRY_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": "1.0", "assets": list(entries)}), encoding="utf-8")
        return path

    def training_entry(self, **changes):
        return {"asset_id": "registered-training", "relative_path": "data/training/set/source.mp4",
                "sha256": "b" * 64, "usage_scope": "training_only", **changes}

    def small_file(self, asset_id, contents, **changes):
        source = asset(asset_id, size_bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest(), **changes)
        path = self.root / source["relative_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return source

    def files(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def reject_before_editing(self, request, code="TRAINING_ONLY", *, status="blocked", discover_tools=False):
        events, before = [], self.files()
        with ExitStack() as stack:
            hooks = [stack.enter_context(patch(target)) for target in (
                "packages.render.engine.normalize_timeline", "packages.render.engine.Runner.capture",
                "packages.render.engine.Runner.probe", "packages.render.engine.Runner.ffmpeg",
                "packages.render.engine.reservation", "packages.render.engine.subprocess.Popen",
            )]
            which = stack.enter_context(patch("packages.render.engine.shutil.which",
                                              return_value="mock-available-tool" if discover_tools else None))
            result = render(request, self.config, emit=events.append)
        for hook in hooks:
            hook.assert_not_called()
        if discover_tools:
            self.assertEqual(which.call_count, 2)
        else:
            which.assert_not_called()
        self.assertEqual(result["status"], status)
        self.assertEqual(result["error"]["code"], code)
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(result["job_id"], request["job_id"])
        self.assertEqual(result["attempt_id"], request["attempt_id"])
        self.assertEqual([event["event"] for event in events], ["error"])
        self.assertEqual(set(events[0]), PROGRESS_FIELDS)
        self.assertEqual(events[0]["message"], result["error"]["message"])
        self.assertEqual(self.files(), before)
        self.assertFalse((self.root / "render").exists())
        return result

    def test_typed_and_provenance_training_signals_reject_conflicting_general_claims(self):
        for metadata in (
            {"usage_scope": "training_only"},
            {"usage_scope": "training_only", "provenance": {"usage_scope": "general"}},
            {"usage_scope": "general", "provenance": {"usage_scope": "training_only"}},
            {"provenance": {"usage_scope": "training_only"}},
        ):
            with self.subTest(metadata=metadata):
                self.reject_before_editing(request_fixture(asset(**metadata)))

    def test_logical_training_path_is_restricted_including_case_aliases(self):
        for relative in ("data/training/set/source.mp4", "DATA/TRAINING/set/source.mp4"):
            with self.subTest(path=relative):
                self.reject_before_editing(request_fixture(asset(relative_path=relative, usage_scope="general")))

    def test_research_preview_and_small_preview_never_exempt_training_use(self):
        for preview, research in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(preview=preview, research_preview=research):
                request = request_fixture(asset(usage_scope="training_only"), preview=preview, research_preview=research)
                request["parameters"]["timeline"]["segments"][0]["review_status"] = "unreviewed" if research else "confirmed"
                self.reject_before_editing(request)

    def test_rights_and_split_do_not_override_training_scope(self):
        for rights in ("owned", "permitted", "research_only"):
            for split in ("train", "validation", "test", "unassigned"):
                with self.subTest(rights=rights, split=split):
                    self.reject_before_editing(request_fixture(asset(usage_scope="training_only", rights={"status": rights}, split=split)))

    def test_raw_training_replay_is_rejected_in_both_orders_before_dedup_or_merge(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                sources = [asset("general"), asset("training", usage_scope="training_only")]
                if reverse:
                    sources.reverse()
                request = request_fixture(*sources, deduplicate_replays=True, merge_overlaps=True, research_preview=True)
                for segment in request["parameters"]["timeline"]["segments"]:
                    segment["replay_group_id"] = "same-shot"
                self.reject_before_editing(request)

    def test_registry_matches_renamed_copy_with_new_asset_id_and_path(self):
        source = self.small_file("renamed-copy", b"tiny registered training fixture")
        self.publish_registry([self.training_entry(sha256=source["sha256"])])
        source["sha256"] = source["sha256"].upper()
        self.reject_before_editing(request_fixture(source))

    def test_forged_hash_is_rechecked_against_real_bytes_before_replay_discard_in_both_orders(self):
        general = self.small_file("general", b"ordinary bytes")
        copied = self.small_file("copied-training", b"training copy bytes")
        self.publish_registry([self.training_entry(sha256=copied["sha256"])])
        copied["sha256"] = "c" * 64
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                sources = [deepcopy(general), deepcopy(copied)]
                if reverse:
                    sources.reverse()
                request = request_fixture(*sources, deduplicate_replays=True, research_preview=True)
                for segment in request["parameters"]["timeline"]["segments"]:
                    segment["replay_group_id"] = "same-shot"
                # TRAINING_ONLY must take precedence over an innocent hash mismatch.
                self.reject_before_editing(request, discover_tools=True)

    def test_derived_asset_inherits_training_restriction_through_source_metadata(self):
        parent = asset("training-parent", usage_scope="training_only", sha256="b" * 64)
        derived = asset("derived", provenance={"source_asset_id": parent["asset_id"], "source_sha256": parent["sha256"]})
        request = request_fixture(derived)
        request["assets"].append(parent)  # Parent is lineage metadata, not a timeline segment.
        self.reject_before_editing(request)

    def test_unselected_training_parent_with_consistently_forged_hash_is_checked_by_actual_bytes(self):
        for include_source_id in (True, False):
            with self.subTest(include_source_id=include_source_id):
                parent = self.small_file(f"renamed-parent-{include_source_id}", b"registered training parent bytes")
                self.publish_registry([self.training_entry(sha256=parent["sha256"])])
                parent["sha256"] = "c" * 64
                provenance = {"source_sha256": parent["sha256"].upper()}
                if include_source_id:
                    provenance["source_asset_id"] = parent["asset_id"]
                derived = self.small_file(f"derived-{include_source_id}", b"valid distinct derivative bytes",
                                          provenance=provenance)
                request = request_fixture(derived)
                request["assets"].append(parent)
                with patch("packages.render.usage.sha256", wraps=sha256) as hash_file:
                    result = self.reject_before_editing(request, discover_tools=True)
                self.assertIn("sha256 is in the trusted training registry", result["error"]["message"])
                self.assertEqual({call.args[0] for call in hash_file.call_args_list},
                                 {self.root / source["relative_path"] for source in (derived, parent)})

    def test_multihop_training_grandparent_actual_bytes_are_checked_before_editing(self):
        grandparent = self.small_file("renamed-grandparent", b"registered training grandparent bytes")
        self.publish_registry([self.training_entry(sha256=grandparent["sha256"])])
        grandparent["sha256"] = "d" * 64
        parent = self.small_file("intermediate", b"valid intermediate bytes", provenance={
            "source_asset_id": grandparent["asset_id"], "source_sha256": grandparent["sha256"],
        })
        derived = self.small_file("selected-derivative", b"valid selected derivative bytes", provenance={
            "source_asset_id": parent["asset_id"], "source_sha256": parent["sha256"],
        })
        request = request_fixture(derived)
        request["assets"].extend([grandparent, parent])
        with patch("packages.render.usage.sha256", wraps=sha256) as hash_file:
            self.reject_before_editing(request, discover_tools=True)
        self.assertEqual({call.args[0] for call in hash_file.call_args_list},
                         {self.root / source["relative_path"] for source in (derived, parent, grandparent)})

    def test_general_ancestor_chain_is_fully_hashed_and_reaches_media_preflight(self):
        self.publish_registry()
        grandparent = self.small_file("general-grandparent", b"general original bytes")
        parent = self.small_file("general-parent", b"general intermediate bytes", provenance={
            "source_asset_id": grandparent["asset_id"], "source_sha256": grandparent["sha256"],
        })
        derived = self.small_file("general-derived", b"general selected bytes", provenance={
            "source_asset_id": parent["asset_id"], "source_sha256": parent["sha256"],
        })
        request = request_fixture(derived)
        request["assets"].extend([grandparent, parent, asset("unreferenced-missing-file")])
        before = self.files()
        with ExitStack() as stack:
            hash_file = stack.enter_context(patch("packages.render.usage.sha256", wraps=sha256))
            which = stack.enter_context(patch("packages.render.engine.shutil.which", return_value="mock-available-tool"))
            normalize = stack.enter_context(patch("packages.render.engine.normalize_timeline", wraps=normalize_timeline))
            capture = stack.enter_context(patch("packages.render.engine.Runner.capture", side_effect=
                RenderError("test_source_validation_complete", "Stop before media subprocesses")))
            hooks = [stack.enter_context(patch(target)) for target in (
                "packages.render.engine.Runner.probe", "packages.render.engine.Runner.ffmpeg",
                "packages.render.engine.reservation", "packages.render.engine.subprocess.Popen",
            )]
            result = render(request, self.config)
        self.assertEqual((result["status"], result["error"]["code"]), ("failed", "test_source_validation_complete"))
        self.assertEqual(which.call_count, 2)
        normalize.assert_called_once()
        capture.assert_called_once()
        for hook in hooks:
            hook.assert_not_called()
        expected_paths = {self.root / source["relative_path"] for source in (derived, parent, grandparent)}
        self.assertEqual({call.args[0] for call in hash_file.call_args_list}, expected_paths)
        self.assertEqual(hash_file.call_count, len(expected_paths), "Repeated ID/hash references must hash each ancestor once")
        self.assertEqual(self.files(), before)
        self.assertFalse((self.root / "render").exists())

    def test_missing_or_tampered_unselected_ancestor_fails_closed_before_editing(self):
        for condition in ("missing", "same-size-tamper", "size-mismatch"):
            with self.subTest(condition=condition):
                parent = self.small_file("ancestor-" + condition, b"ordinary ancestor bytes")
                derived = self.small_file("derived-" + condition, b"valid derivative", provenance={
                    "source_asset_id": parent["asset_id"], "source_sha256": parent["sha256"],
                })
                parent_path = self.root / parent["relative_path"]
                if condition == "missing":
                    parent_path.unlink()
                elif condition == "same-size-tamper":
                    parent_path.write_bytes(b"X" + b"ordinary ancestor bytes"[1:])
                else:
                    parent_path.write_bytes(b"ordinary ancestor bytes!")
                request = request_fixture(derived)
                request["assets"].append(parent)
                result = self.reject_before_editing(request,
                    "missing_asset" if condition == "missing" else "asset_mismatch",
                    status="failed", discover_tools=True)
                self.assertIn(parent["asset_id"], result["error"]["message"])

    def test_present_training_directory_without_registry_fails_closed(self):
        (self.root / "data/training").mkdir(parents=True)
        self.reject_before_editing(request_fixture(), "TRAINING_REGISTRY_PENDING")

    def test_malformed_registry_is_not_treated_as_an_empty_allowlist(self):
        registry = self.publish_registry()
        for malformed in (
            "not JSON", '{"schema_version":"1.0","assets":{}}',
            '{"schema_version":"1.0","assets":[],"assets":[]}',
            json.dumps({"schema_version": "1.0", "assets": [self.training_entry(sha256="invalid")]}),
        ):
            with self.subTest(registry=malformed):
                registry.write_text(malformed, encoding="utf-8")
                self.reject_before_editing(request_fixture(), "TRAINING_REGISTRY_INVALID")

    def test_request_metadata_cannot_replace_the_fixed_trusted_registry(self):
        registered = self.training_entry()
        self.publish_registry([registered])
        request = request_fixture(asset(sha256=registered["sha256"]), training_registry={"schema_version": "1.0", "assets": []})
        self.reject_before_editing(request)

    def test_bad_usage_values_fail_closed_before_media_or_editorial_work(self):
        for metadata in ({"usage_scope": None}, {"usage_scope": "public"},
                         {"provenance": {"usage_scope": "public"}}, {"provenance": {"source_sha256": "invalid"}}):
            with self.subTest(metadata=metadata):
                self.reject_before_editing(request_fixture(asset(**metadata)), "USAGE_METADATA_INVALID")

    def test_default_general_and_training_lookalike_paths_reach_missing_tool_detection(self):
        for source in (asset(), asset(relative_path="data/training-other/source.mp4"), asset(split="train")):
            with self.subTest(source=source):
                with patch("packages.render.engine.shutil.which", return_value=None) as which, \
                     patch("packages.render.engine.Runner.capture") as capture, \
                     patch("packages.render.engine.reservation") as reserve:
                    result = render(request_fixture(source), self.config)
                self.assertEqual((result["status"], result["error"]["code"]), ("blocked", "not_installed"))
                which.assert_called_once()
                capture.assert_not_called()
                reserve.assert_not_called()

    def test_malformed_raw_timeline_cannot_reach_usage_dependent_editorial_work(self):
        for segments, code in ((None, "invalid_request"), ([], "invalid_request"),
                               ([None], "invalid_request"), ([{"asset_id": "unknown"}], "unknown_asset")):
            with self.subTest(segments=segments):
                request = request_fixture()
                request["parameters"]["timeline"]["segments"] = segments
                self.reject_before_editing(request, code, status="failed")

    def directory_alias(self, target, link):
        """Create only test-root links; remove the link before TemporaryDirectory."""
        root = self.root.resolve()
        self.assertTrue(target.resolve().is_relative_to(root))
        self.assertTrue(link.parent.resolve().is_relative_to(root))
        self.assertFalse(link.exists())
        link.parent.mkdir(parents=True, exist_ok=True)
        junction_result = None
        try:
            link.symlink_to(target, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            if os.name != "nt":
                self.skipTest(f"Creating directory symlinks unavailable: {exc}")
            # Junctions do not need Windows symbolic-link privileges. Paths are
            # passed as environment values, never interpolated into shell code.
            junction_result = subprocess.run([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
                "-Path $env:BTV_RENDER_TEST_LINK -Target $env:BTV_RENDER_TEST_TARGET | Out-Null",
            ], env={**os.environ, "BTV_RENDER_TEST_LINK": str(link),
                    "BTV_RENDER_TEST_TARGET": str(target)},
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW)

        def remove_alias():
            self.assertTrue(link.parent.resolve().is_relative_to(root))
            self.assertEqual(link.resolve(), target.resolve())
            if os.name == "nt":
                os.rmdir(link)  # Removes the directory reparse entry, not its target.
            else:
                link.unlink()
            self.assertTrue(target.is_dir(), "Alias cleanup must preserve its target")

        # Cleanup is LIFO: remove this entry before recursive temp-root cleanup.
        if link.exists():
            self.addCleanup(remove_alias)
        if junction_result is not None:
            self.assertEqual(junction_result.returncode, 0, junction_result.stderr)
        self.assertEqual(link.resolve(), target.resolve())

    def test_general_logical_alias_to_physical_training_directory_is_rejected(self):
        self.publish_registry()
        target = self.root / "data/training/set"
        target.mkdir()
        (target / "source.mp4").write_bytes(b"tiny bytes")
        self.directory_alias(target, self.root / "data/raw/alias")
        self.reject_before_editing(request_fixture(asset(relative_path="data/raw/alias/source.mp4")))

    def test_logical_training_alias_to_general_physical_directory_is_still_rejected(self):
        self.publish_registry()
        target = self.root / "data/raw/set"
        target.mkdir(parents=True)
        (target / "source.mp4").write_bytes(b"tiny bytes")
        self.directory_alias(target, self.root / "data/training/alias")
        self.reject_before_editing(request_fixture(asset(relative_path="data/training/alias/source.mp4")))

    def test_real_cli_returns_exit_two_and_blocked_result_without_ffmpeg(self):
        request = request_fixture(asset(usage_scope="training_only"), research_preview=True)
        request_path, result_path = self.root / "cli-request.json", self.root / "cli-result.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        completed = subprocess.run([
            sys.executable, "-B", "-m", "packages.render", "run", "--request", str(request_path),
            "--result", str(result_path), "--storage-root", str(self.root), "--backend", "cpu",
            "--ffmpeg", str(self.root / "not-installed-ffmpeg.exe"),
            "--ffprobe", str(self.root / "not-installed-ffprobe.exe"),
        ], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(completed.returncode, 2, completed.stderr + completed.stdout)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual((result["status"], result["error"]["code"]), ("blocked", "TRAINING_ONLY"))
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(result["attempt_id"], request["attempt_id"])
        progress = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([event["event"] for event in progress], ["error"])
        self.assertEqual(set(progress[0]), PROGRESS_FIELDS)
        self.assertFalse((self.root / "render").exists())


if __name__ == "__main__":
    unittest.main()
