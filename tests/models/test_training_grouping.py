"""Synthetic grouping boundaries only; no real labels, training or accuracy."""

import copy
import hashlib
import itertools
import unittest

from packages.models.training_grouping import audit_groups


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def row(asset_id, **changes):
    result = {"asset_id": asset_id, "sha256": digest(asset_id),
              "match_id": "match-" + asset_id, "match_confirmed": True,
              "group_id": "group-" + asset_id, "group_confirmed": True,
              "source_asset_ids": [], "source_sha256s": [], "split": "train"}
    result.update(changes)
    return result


def codes(result):
    return {issue["code"] for issue in result["issues"]}


class TrainingGroupingTests(unittest.TestCase):
    def test_confirmed_independent_groups_can_use_different_splits(self):
        result = audit_groups([row("a"), row("b", split="validation"), row("c", split="test")])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["eligible_asset_ids"], ["a", "b", "c"])
        self.assertEqual(len(result["components"]), 3)

    def test_each_relationship_connects_and_rejects_whole_leaking_group(self):
        cases = {
            "match": ({"match_id": "same"}, {"match_id": "same"}),
            "group": ({"group_id": "same"}, {"group_id": "same"}),
            "body_hash": ({"sha256": digest("same")}, {"sha256": digest("same").upper()}),
            "shared_external_id": ({"source_asset_ids": ["external"]}, {"source_asset_ids": ["external"]}),
            "shared_external_hash": ({"source_sha256s": [digest("external")]}, {"source_sha256s": [digest("external").upper()]}),
            "body_to_source_id": ({}, {"source_asset_ids": ["a"]}),
            "body_to_source_hash": ({}, {"source_sha256s": [digest("a")]}),
        }
        for name, (first, second) in cases.items():
            with self.subTest(relation=name):
                result = audit_groups([row("a", **first), row("b", **second, split="test"), row("safe")])
                leakage = next(item for item in result["issues"] if item["code"] == "split_leakage")
                self.assertEqual(leakage["asset_ids"], ["a", "b"])
                self.assertEqual(leakage["component_asset_ids"], ["a", "b"])
                self.assertEqual(leakage["details"]["splits"], ["test", "train"])
                self.assertEqual(result["eligible_asset_ids"], ["safe"])

    def test_transitive_mixed_relations_include_all_rows_before_rejection(self):
        rows = [row("a"), row("b", source_asset_ids=["a"]),
                row("c", source_sha256s=[digest("b")], source_asset_ids=["outside"], split="validation"),
                row("d", source_asset_ids=["outside"], split="test")]
        result = audit_groups(rows)
        self.assertEqual(len(result["components"]), 1)
        self.assertEqual(result["components"][0]["asset_ids"], ["a", "b", "c", "d"])
        self.assertEqual(result["components"][0]["row_count"], 4)
        self.assertEqual(result["eligible_asset_ids"], [])
        self.assertIn("split_leakage", codes(result))

    def test_multiple_parent_ids_and_hashes_are_relationships_not_paired_arrays(self):
        result = audit_groups([
            row("a", source_asset_ids=["parent-a", "parent-b"], source_sha256s=[digest("shared")]),
            row("parent-b"), row("c", source_sha256s=[digest("shared")], split="test")])
        self.assertEqual(result["components"][0]["asset_ids"], ["a", "c", "parent-b"])
        self.assertIn("split_leakage", codes(result))

    def test_unconfirmed_bridge_is_not_dropped_before_leakage_detection(self):
        result = audit_groups([
            row("a"),
            row("bridge", match_id=None, match_confirmed=False, split="unassigned",
                source_asset_ids=["a"], source_sha256s=[digest("c")]),
            row("c", split="test"), row("safe")])
        leak = next(item for item in result["issues"] if item["code"] == "split_leakage")
        self.assertEqual(leak["component_asset_ids"], ["a", "bridge", "c"])
        self.assertEqual(result["eligible_asset_ids"], ["safe"])

    def test_one_related_source_cannot_declare_multiple_groups_even_in_same_split(self):
        result = audit_groups([row("a"), row("b", source_sha256s=[digest("a")])])
        self.assertIn("conflicting_groups", codes(result))
        self.assertNotIn("split_leakage", codes(result))
        self.assertEqual(result["eligible_asset_ids"], [])

    def test_confirmed_matches_can_share_one_conservative_group(self):
        result = audit_groups([row("a", group_id="combined"), row("b", group_id="combined")])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["components"][0]["match_ids"], ["match-a", "match-b"])
        self.assertEqual(result["eligible_asset_ids"], ["a", "b"])

    def test_duplicate_asset_keeps_both_hashes_and_all_connected_assets(self):
        result = audit_groups([row("a"), row("a", sha256=digest("second"), split="test"),
                               row("related", source_sha256s=[digest("second")]), row("safe")])
        component = next(item for item in result["components"] if "a" in item["asset_ids"])
        self.assertEqual(component["asset_ids"], ["a", "related"])
        self.assertEqual(component["row_count"], 3)
        self.assertTrue({"duplicate_asset_id", "conflicting_asset_hashes", "split_leakage"} <= codes(result))
        self.assertEqual(result["eligible_asset_ids"], ["safe"])

    def test_identical_duplicate_rows_still_rejected(self):
        result = audit_groups([row("a"), row("a")])
        self.assertEqual(codes(result), {"duplicate_asset_id"})
        self.assertEqual(result["components"][0]["row_count"], 2)
        self.assertEqual(result["eligible_asset_ids"], [])

    def test_unknown_match_is_not_an_independent_training_match(self):
        for value in (None, "", " UNKNOWN ", "null", "n/a", "unconfirmed"):
            with self.subTest(value=value):
                result = audit_groups([row("a", match_id=value), row("safe")])
                self.assertIn("missing_match_id", codes(result))
                component = next(item for item in result["components"] if "a" in item["asset_ids"])
                self.assertEqual(component["match_ids"], [])
                self.assertFalse(component["eligible"])
                self.assertEqual(result["eligible_asset_ids"], ["safe"])

    def test_insufficient_member_rejects_complete_connected_group(self):
        changes = [({"sha256": None}, "missing_sha256"),
                   ({"match_id": None}, "missing_match_id"),
                   ({"match_confirmed": False}, "match_unconfirmed"),
                   ({"group_id": None}, "missing_group_id"),
                   ({"group_confirmed": False}, "group_unconfirmed"),
                   ({"split": "unassigned"}, "unassigned_split"),
                   ({"source_asset_ids": ["unknown"]}, "unknown_source_asset_id"),
                   ({"source_sha256s": [""]}, "unknown_source_sha256")]
        for change, code in changes:
            with self.subTest(code=code):
                first, second = row("a", group_id="same"), row("b", group_id="same", source_asset_ids=["a"])
                second.update(change)
                result = audit_groups([first, second])
                self.assertIn(code, codes(result))
                self.assertEqual(result["eligible_asset_ids"], [])
                self.assertEqual(result["components"][0]["asset_ids"], ["a", "b"])

    def test_missing_split_is_reported_without_inventing_cross_split_leakage(self):
        for value in (None, "unknown", "unassigned", ""):
            with self.subTest(value=value):
                result = audit_groups([row("a", group_id="same"), row("b", group_id="same", split=value)])
                self.assertIn("unassigned_split", codes(result))
                self.assertNotIn("split_leakage", codes(result))
                self.assertEqual(result["eligible_asset_ids"], [])

    def test_empty_input_is_a_readable_insufficiency(self):
        result = audit_groups([])
        self.assertEqual(codes(result), {"empty_input"})
        self.assertEqual(result["components"], [])
        self.assertEqual(result["eligible_asset_ids"], [])

    def test_token_namespaces_do_not_confuse_id_with_hash_or_match_with_group(self):
        result = audit_groups([row("f"*64, match_id="cross-name"),
                               row("b", sha256="f"*64, group_id="cross-name")])
        self.assertEqual(len(result["components"]), 2)
        self.assertEqual(result["issues"], [])

    def test_deterministic_under_permutation_and_reference_order_without_mutation(self):
        rows = [row("a", source_asset_ids=["outside-2", "outside-1", "outside-2"]),
                row("b", source_asset_ids=["outside-1"], split="test"),
                row("c", sha256=None, match_confirmed=False)]
        original = copy.deepcopy(rows)
        expected = audit_groups(rows)
        for order in itertools.permutations(rows):
            alternate = copy.deepcopy(order)
            for item in alternate:
                item["source_asset_ids"].reverse()
            self.assertEqual(audit_groups(item for item in alternate), expected)
        self.assertEqual(rows, original)

    def test_malformed_structures_and_types_raise(self):
        invalid = [None, {}, "rows", [None], [{**row("a"), "extra": True}],
                   [{key: value for key, value in row("a").items() if key != "group_confirmed"}]]
        for field, value in (("asset_id", None), ("asset_id", " a "), ("sha256", "not-a-hash"),
                             ("match_confirmed", 1), ("group_confirmed", "true"),
                             ("source_asset_ids", "a"), ("source_asset_ids", [None]),
                             ("source_sha256s", [1]), ("source_sha256s", ["invalid"]),
                             ("split", "evaluation"), ("split", False), ("match_id", "m\n1")):
            invalid.append([{**row("a"), field: value}])
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises((TypeError, ValueError)):
                audit_groups(rows)


if __name__ == "__main__":
    unittest.main()
