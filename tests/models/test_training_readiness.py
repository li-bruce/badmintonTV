"""Synthetic contract/CPU gate tests; no real human labels or model quality."""

import copy
import hashlib
import importlib
import json
import unittest

from packages.models.training_readiness import audit_snapshot


STAMP = "2026-10-02T12:00:00Z"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def inputs():
    """Three declared independent synthetic matches, one per required split."""
    assets, bundles, splits = [], [], []
    for suffix, split in zip("abc", ("train", "validation", "test")):
        asset_id = "asset-" + suffix
        asset = {"asset_id": asset_id, "sha256": digest(asset_id), "relative_path": "data/" + suffix + ".mp4",
                 "size_bytes": 100, "duration_ms": 1000, "match_id": "match-" + suffix,
                 "group_id": "group-" + suffix, "group_status": "confirmed",
                 "provenance": {"group_evidence": {"verified": True, "source": "synthetic fixture",
                                                    "reference": "synthetic-engineering-test-only"}}}
        assets.append(asset)
        person = {"person_id": "person-self", "display_name": "Synthetic self", "team_id": "team-self",
                  "identity_status": "confirmed"}
        record = {"record_id": "record-" + suffix, "project_id": "project-synthetic", "asset_id": asset_id,
                  "kind": "contact", "at_ms": 100, "person_id": person["person_id"], "visibility": "clear",
                  "review": {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-reviewer-claim",
                             "reviewed_at": STAMP},
                  "provenance": {"revision_audit": {"actor_type": "human", "reviewer": "synthetic-reviewer-claim", "at": STAMP}},
                  "evidence": [{"source_frame_index": 2, "at_ms": 100, "source": "synthetic metadata only"}],
                  "judgements": [{"label_id": "label-one", "value": "present"}]}
        bundles.append({"project_id": "project-synthetic", "asset": asset, "people": [person], "records": [record]})
        splits.append({"group_id": asset["group_id"], "split": split})
    return {"snapshot_id": "snapshot-synthetic", "created_at": STAMP,
            "project": {"project_id": "project-synthetic", "name": "Synthetic CPU test", "catalog_version": "fixture-1",
                        "taxonomy_id": "taxonomy-synthetic", "taxonomy_version": "fixture-1",
                        "asset_ids": [asset["asset_id"] for asset in assets], "created_at": STAMP, "updated_at": STAMP},
            "taxonomy": {"taxonomy_id": "taxonomy-synthetic", "version": "fixture-1", "status": "reviewed",
                         "labels": [{"label_id": "label-one", "name": "Synthetic label", "dimension": "fixture",
                                     "description": "No expert or real-media claim", "kinds": ["contact"],
                                     "status": "defined", "requires_person": True}]},
            "assets": assets, "bundles": bundles, "splits": splits}


def exclusion(report, asset_id="asset-a", label_id="label-one", role="self"):
    return next(item for item in report["exclusions"] if item["asset_id"] == asset_id
                and item["label_id"] == label_id and item.get("subject_role", "self") == role)


class TrainingReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.contract = importlib.import_module("packages.contracts.training")
        except ModuleNotFoundError as exc:
            if exc.name != "packages.contracts.training":
                raise
            raise unittest.SkipTest("Public training contract not integrated; run with the platform contract package") from exc

    def snapshot(self, values=None):
        return self.contract.build_training_snapshot(**(values if values is not None else inputs()))

    def audit(self, values=None, **kwargs):
        return audit_snapshot(self.snapshot(values), **kwargs)

    def test_declared_ready_is_deterministic_json_safe_and_does_not_mutate(self):
        snapshot = self.snapshot()
        before = snapshot.model_dump(mode="json")
        first = audit_snapshot(snapshot)
        self.assertEqual(first, audit_snapshot(copy.deepcopy(before)))
        self.assertEqual(snapshot.model_dump(mode="json"), before)
        self.assertEqual(json.loads(json.dumps(first, allow_nan=False)), first)
        self.assertTrue(first["trainable"])
        self.assertEqual(first["blockers"], [])
        self.assertEqual(len(first["strict_training_view"]), 3)
        self.assertEqual(first["coverage"]["strict_by_split"], {"train": 1, "validation": 1, "test": 1})
        self.assertEqual(first["coverage"]["records"]["missing_state"], 3)
        self.assertIn("not authenticated human truth", " ".join(first["limitations"]))

    def test_draft_taxonomy_has_no_formal_samples_and_retains_public_exclusions(self):
        values = inputs()
        values["taxonomy"]["status"] = "provisional"
        snapshot = self.snapshot(values)
        report = audit_snapshot(snapshot)
        self.assertFalse(report["trainable"])
        self.assertEqual(report["strict_training_view"], [])
        for public in snapshot.model_dump(mode="json")["exclusions"]:
            retained = exclusion(report, public["asset_id"])
            self.assertTrue(set(public["reasons"]) <= set(retained["reasons"]))
        self.assertIn("taxonomy_not_reviewed", report["blockers"])

    def test_visibility_and_review_audit_evidence_gates_are_independent(self):
        cases = [
            (lambda r: r.update(visibility="partial"), "visibility_not_clear"),
            (lambda r: r.update(visibility="unobservable"), "visibility_not_clear"),
            (lambda r: r.update(visibility="unknown"), "visibility_not_clear"),
            (lambda r: r["review"].update(status="pending"), "not_confirmed"),
            (lambda r: r["review"].update(reviewed_at=None), "reviewed_at_missing"),
            (lambda r: r.update(provenance={}), "revision_audit_missing_or_invalid"),
            (lambda r: r["provenance"].update(revision_audit="invalid"), "revision_audit_missing_or_invalid"),
            (lambda r: r["provenance"]["revision_audit"].update(actor_type="agent"), "revision_audit_actor_mismatch"),
            (lambda r: r["provenance"]["revision_audit"].update(reviewer="different-claim"), "revision_audit_reviewer_mismatch"),
            (lambda r: r.update(evidence=[]), "evidence_missing"),
            (lambda r: r.update(evidence=[{}]), "evidence_missing"),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                values = inputs()
                mutate(values["bundles"][0]["records"][0])
                report = self.audit(values)
                self.assertIn(code, exclusion(report)["reasons"])
                self.assertFalse(report["trainable"])
                self.assertEqual({item["asset_id"] for item in report["strict_training_view"]}, {"asset-b", "asset-c"})

    def test_agent_model_import_confirmed_claims_never_become_human_truth(self):
        for actor in ("agent", "model", "import"):
            with self.subTest(actor=actor):
                values = inputs()
                record = values["bundles"][0]["records"][0]
                record["review"]["reviewer_type"] = actor
                record["provenance"]["revision_audit"]["actor_type"] = actor
                report = self.audit(values)
                self.assertIn("not_human_review", exclusion(report)["reasons"])
                self.assertEqual(report["coverage"]["records"]["by_reviewer_type"][actor], 1)

    def test_absent_requires_explicit_observation_reason(self):
        for reason, accepted in ((None, False), ("  ", False), ("unknown", False), ("Explicit synthetic observed absence", True)):
            with self.subTest(reason=reason):
                values = inputs()
                values["bundles"][0]["records"][0]["judgements"][0].update(value="absent", reason=reason)
                report = self.audit(values)
                self.assertEqual(report["trainable"], accepted)
                if accepted:
                    self.assertEqual(next(item for item in report["strict_training_view"] if item["asset_id"] == "asset-a")["value"], "absent")

    def test_explicit_unlabeled_and_implicit_missing_are_separate_not_negatives(self):
        values = inputs()
        values["taxonomy"]["labels"].append({**values["taxonomy"]["labels"][0], "label_id": "label-two"})
        values["bundles"][0]["records"][0]["judgements"][0]["value"] = "unlabeled"
        report = self.audit(values)
        self.assertEqual(report["coverage"]["judgements"]["explicit_unlabeled"], 1)
        self.assertEqual(report["coverage"]["judgements"]["implicit_unlabeled"], 3)
        self.assertEqual(report["coverage"]["judgements"]["by_value"]["absent"], 0)
        missing = next(item for item in report["coverage"]["by_label"] if item["label_id"] == "label-two")
        self.assertEqual(missing["explicit_judgement_count"], 0)
        self.assertEqual(missing["implicit_unlabeled_count"], 3)
        self.assertIn("unlabeled", exclusion(report)["reasons"])

    def test_missing_bundle_and_missing_required_split_block_even_with_good_rows(self):
        values = inputs()
        values["bundles"] = values["bundles"][:2]
        report = self.audit(values)
        self.assertIn("annotation_bundle_missing", report["blockers"])
        self.assertIn("missing_test_examples", report["blockers"])
        self.assertEqual(report["coverage"]["assets"]["missing_bundle_ids"], ["asset-c"])
        self.assertEqual(len(report["group_audit"]["eligible_asset_ids"]), 3)

    def test_group_confirmation_cannot_substitute_for_match_evidence(self):
        values = inputs()
        values["assets"][0]["provenance"] = {"match_confirmed": True, "match_status": "confirmed"}
        report = self.audit(values)
        self.assertFalse(report["trainable"])
        self.assertIn("match_unconfirmed", {item["code"] for item in report["group_audit"]["issues"]})
        self.assertIn("group_ineligible", exclusion(report)["reasons"])

    def test_all_typed_relationships_join_without_fake_asset_namespace(self):
        for kind in ("root_asset_ids", "source_sha256s", "source_group_ids", "recording_session_id"):
            with self.subTest(kind=kind):
                values = inputs()
                values["splits"][1]["split"] = "train"
                a, b, _ = values["assets"]
                if kind == "root_asset_ids":
                    b[kind] = [a["asset_id"]]
                elif kind == "source_sha256s":
                    b[kind] = [a["sha256"]]
                elif kind == "source_group_ids":
                    b[kind] = [a["group_id"]]
                else:
                    a[kind] = b[kind] = "asset-c"  # Must not collide with that actual asset ID.
                report = self.audit(values)
                self.assertEqual(report["group_audit"]["eligible_asset_ids"], ["asset-c"])
                component = next(item for item in report["group_audit"]["components"] if "asset-a" in item["asset_ids"])
                self.assertEqual(component["asset_ids"], ["asset-a", "asset-b"])
                self.assertIn("conflicting_groups", component["issue_codes"])

    def test_external_history_edges_close_transitively_and_reject_whole_group(self):
        values = inputs()
        sources = {asset["asset_id"]: copy.deepcopy(asset) for asset in values["assets"]}
        sources["asset-a"]["provenance_history"] = [{"source_sha256": digest("shared-original")}]
        sources["asset-b"]["provenance"]["provenance_history"] = [{"source_asset_id": "asset-a"}]
        sources["asset-c"]["provenance"]["source_sha256s"] = [digest("shared-original")]
        before = copy.deepcopy(sources)
        report = self.audit(values, source_assets=sources)
        self.assertEqual(sources, before)
        self.assertEqual(report["strict_training_view"], [])
        self.assertEqual(report["group_audit"]["components"][0]["asset_ids"], ["asset-a", "asset-b", "asset-c"])
        self.assertIn("split_leakage", report["group_audit"]["components"][0]["issue_codes"])

    def test_snapshot_history_and_plural_edges_are_not_dropped(self):
        values = inputs()
        values["assets"][0]["provenance"]["provenance_history"] = [{"source_asset_id": "outside"}]
        values["assets"][1]["provenance"]["source_asset_ids"] = ["outside"]
        report = self.audit(values)
        self.assertEqual(report["group_audit"]["eligible_asset_ids"], ["asset-c"])
        self.assertIn("split_leakage", {item["code"] for item in report["group_audit"]["issues"]})

    def test_invalid_source_metadata_is_rejected_not_ignored(self):
        for field, value in (("source_asset_id", 123), ("source_sha256", "bad"), ("source_asset_ids", "a"),
                             ("provenance_history", [{} , 4]), ("source_sha256s", [None])):
            with self.subTest(field=field):
                values = inputs()
                values["assets"][0]["provenance"][field] = value
                with self.assertRaises((TypeError, ValueError)):
                    self.audit(values)

    def test_source_identity_must_match_all_five_fields_and_cannot_elevate_review(self):
        for field, changed in (("asset_id", "other"), ("sha256", "f" * 64), ("relative_path", "data/other.mp4"),
                               ("size_bytes", 101), ("duration_ms", 1001)):
            with self.subTest(field=field):
                values = inputs()
                sources = {asset["asset_id"]: copy.deepcopy(asset) for asset in values["assets"]}
                sources["asset-a"][field] = changed
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    self.audit(values, source_assets=sources)
        values = inputs()
        sources = {asset["asset_id"]: copy.deepcopy(asset) for asset in values["assets"]}
        values["assets"][0]["provenance"] = {}
        report = self.audit(values, source_assets=sources)
        self.assertIn("group_ineligible", exclusion(report)["reasons"])

    def test_same_label_preserves_four_resolved_subjects_and_separate_exclusions(self):
        values = inputs()
        bundle = values["bundles"][0]
        record = bundle["records"][0]
        record["state"] = {}
        record["judgements"] = []
        for role in ("self", "opponent", "partner", "opponent_partner"):
            person_id = "person-" + role
            team_id = "team-self" if role in ("self", "partner") else "team-opponent"
            if role != "self":
                bundle["people"].append({"person_id": person_id, "display_name": "Synthetic " + role,
                                         "team_id": team_id, "identity_status": "confirmed"})
            record["state"][role] = {"person_id": person_id, "team_id": team_id}
            # Omit subject_person_id; public rules resolve it from each role.
            record["judgements"].append({"label_id": "label-one", "subject_role": role, "value": "present"})
        report = self.audit(values)
        examples = [item for item in report["strict_training_view"] if item["asset_id"] == "asset-a"]
        self.assertEqual({(item["subject_role"], item["subject_person_id"]) for item in examples},
                         {(role, "person-" + role) for role in record["state"]})
        self.assertEqual(len(examples), 4)
        record["judgements"][1].update(value="unknown", reason="Synthetic occlusion")
        report = self.audit(values)
        self.assertEqual(len([item for item in report["strict_training_view"] if item["asset_id"] == "asset-a"]), 3)
        self.assertEqual(exclusion(report, role="opponent")["subject_person_id"], "person-opponent")
        self.assertIn("unknown", exclusion(report, role="opponent")["reasons"])

    def test_navigation_groups_are_not_missing_supervision(self):
        values = inputs()
        values["taxonomy"]["labels"].append({**values["taxonomy"]["labels"][0], "label_id": "navigation", "selectable": False})
        report = self.audit(values)
        self.assertEqual(report["coverage"]["navigation_group_count"], 1)
        self.assertEqual([item["label_id"] for item in report["coverage"]["by_label"]], ["label-one"])
        self.assertEqual(report["coverage"]["judgements"]["implicit_unlabeled"], 0)

    def test_resolved_duplicate_subject_cannot_double_count_or_overwrite_truth(self):
        values = inputs()
        record = values["bundles"][0]["records"][0]
        record["judgements"].append({"label_id": "label-one", "subject_role": "self",
                                     "subject_person_id": "person-self", "value": "absent",
                                     "reason": "Conflicting synthetic duplicate"})
        # Public contract 2128568 now rejects this before snapshot creation.
        # The consumer retains its duplicate-key guard as defence in depth.
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.audit(values)

    def test_missing_identity_is_reported_without_discarding_record(self):
        values = inputs()
        values["bundles"][0]["records"][0]["person_id"] = None
        report = self.audit(values)
        self.assertEqual(report["coverage"]["records"]["missing_person_or_confirmed_identity"], 1)
        self.assertEqual(len(report["records"]), 3)
        self.assertIn("identity_unknown", exclusion(report)["reasons"])

    def test_empty_snapshot_is_not_training_ready(self):
        values = inputs()
        values.update(assets=[], bundles=[], splits=[])
        values["project"]["asset_ids"] = []
        report = self.audit(values)
        self.assertFalse(report["trainable"])
        self.assertEqual(report["strict_training_view"], [])
        self.assertIn("no_strict_training_examples", report["blockers"])
        self.assertEqual(report["coverage"]["records"]["total"], 0)

    def test_public_validation_and_hash_are_not_bypassed_by_model_instance(self):
        snapshot = self.snapshot()
        forged = snapshot.model_copy(update={"content_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "hash"):
            audit_snapshot(forged)
        changed = snapshot.model_dump(mode="json")
        changed["bundles"][0]["records"][0]["at_ms"] = 1001
        with self.assertRaises(ValueError):
            audit_snapshot(changed)

    def test_deleted_record_stays_visible_in_audit_and_is_never_eligible(self):
        values = inputs()
        values["bundles"][0]["records"][0]["deleted"] = True
        report = self.audit(values)
        self.assertEqual(report["coverage"]["records"]["deleted"], 1)
        self.assertTrue(next(item for item in report["records"] if item["asset_id"] == "asset-a")["deleted"])
        self.assertIn("deleted", exclusion(report)["reasons"])


if __name__ == "__main__":
    unittest.main()
