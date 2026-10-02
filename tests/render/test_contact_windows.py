"""A-07/A-08 contact ranges: pure logic and production-use rejection, no media."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.render.contact_windows import (
    SourceClock, WindowError, derive_contact_windows, read_verified_clock,
)
from packages.render.engine import RenderConfig, render
from packages.render.timeline import RenderError, assets_by_id, normalize_timeline


def source(**changes):
    value = {
        "schema_version": "1.0", "asset_id": "court-a",
        "relative_path": "data/raw/court-a.mp4", "sha256": "a" * 64,
        "size_bytes": 128, "duration_ms": 12000, "width": 640, "height": 360,
        "fps_num": 25, "fps_den": 1, "time_base": "1/1000",
        "source_type": "synthetic", "usage_scope": "general", "match_id": "fixture-match",
        "rights": {"status": "owned", "license_url": None, "evidence": [], "allowed_uses": ["local_test"]},
    }
    value.update(changes)
    return value


def record(record_id, kind, *, rally_id="rally-1", **changes):
    value = {
        "record_id": record_id, "revision": 1, "asset_id": "court-a",
        "rally_id": rally_id, "kind": kind,
    }
    value.update(changes)
    return value


def rally(record_id="rally-1", start_ms=1000, end_ms=9000):
    return record(record_id, "rally", rally_id=record_id, start_ms=start_ms, end_ms=end_ms)


def contact(record_id="contact-2", time_ms=3500, player_id="B", **changes):
    return record(record_id, changes.pop("kind", "contact"), time_ms=time_ms,
                  player_id=player_id, **changes)


def phase_records(anchor_id="contact-3", player_id="A"):
    return [
        record(f"phase-{phase}", "movement", start_ms=start, end_ms=end,
               anchor_id=anchor_id, phase=phase, player_id=player_id)
        for phase, start, end in (
            ("preparation", 4500, 4800), ("initiation", 4800, 5100),
            ("arrival", 5100, 5700), ("stroke_support", 5700, 6100),
            ("landing", 6100, 6500), ("recovery", 6500, 7000),
        )
    ]


def records():
    return [
        rally(), contact("serve-1", 1500, "A", kind="serve"), contact(),
        contact("contact-3", 6000, "A"), record("dead-1", "dead_ball", time_ms=8500),
        *phase_records(),
    ]


def derive(items=None, asset=None, **options):
    return derive_contact_windows(source() if asset is None else asset,
                                  records() if items is None else items,
                                  project_id="training-project", vocabulary_version="v1", **options)


def window(result, strategy, anchor_id):
    identity = "rally_id" if strategy == "rally" else "anchor_id"
    matches = [item for item in result["windows"]
               if item["strategy"] == strategy and item[identity] == anchor_id]
    if len(matches) != 1:
        raise AssertionError(f"Expected one {strategy}/{anchor_id} window, got {len(matches)}")
    return matches[0]


class ContactWindowTests(unittest.TestCase):
    def assert_range(self, item, start, end, status="ready"):
        self.assertEqual(item["range"], {"start_ms": start, "end_ms": end})
        self.assertEqual(item["status"], status)

    def test_four_strategies_have_distinct_source_ranges(self):
        result = derive()
        self.assertEqual(len(result["windows"]), 10)
        self.assert_range(window(result, "ball_flight", "contact-3"), 6000, 8500)
        self.assert_range(window(result, "hand_technique", "contact-3"), 5500, 6500)
        self.assert_range(window(result, "footwork", "contact-3"), 4500, 7000)
        self.assert_range(window(result, "rally", "rally-1"), 1500, 8500)
        self.assert_range(window(result, "ball_flight", "serve-1"), 1500, 3500)

    def test_four_players_and_shuffled_rows_use_next_contact_not_next_same_player(self):
        items = [rally(end_ms=7000), record("dead-1", "dead_ball", time_ms=6500)]
        items += [contact(f"hit-{index}", time, player)
                  for index, time, player in ((1, 2000, "A"), (2, 3000, "B"),
                                              (3, 4000, "C"), (4, 5000, "D"))]
        result = derive(list(reversed(items)))
        for index, start, end in ((1, 2000, 3000), (2, 3000, 4000),
                                  (3, 4000, 5000), (4, 5000, 6500)):
            with self.subTest(contact=index):
                self.assert_range(window(result, "ball_flight", f"hit-{index}"), start, end)

    def test_adjacent_rally_does_not_supply_a_missing_next_contact_or_dead_ball(self):
        items = [rally(end_ms=3000), contact("last-1", 2500, "A"),
                 rally("rally-2", 3000, 7000),
                 contact("first-2", 3000, "B", rally_id="rally-2"),
                 record("dead-2", "dead_ball", rally_id="rally-2", time_ms=7000)]
        result = derive(items)
        missing = window(result, "ball_flight", "last-1")
        self.assertEqual(missing["status"], "unavailable")
        self.assertIsNone(missing["range"])
        self.assertTrue(missing["reasons"])
        self.assert_range(window(result, "ball_flight", "first-2"), 3000, 7000)

    def test_dead_ball_at_media_end_is_valid_but_contact_at_rally_end_is_not(self):
        items = [rally(end_ms=12000), contact(), record("dead-1", "dead_ball", time_ms=12000)]
        self.assert_range(window(derive(items), "ball_flight", "contact-2"), 3500, 12000)
        for kind in ("contact", "serve"):
            with self.subTest(kind=kind), self.assertRaises(WindowError):
                derive([rally(end_ms=3000), contact("outside", 3000, kind=kind)])

    def test_unknown_rally_end_does_not_infer_end_from_final_contact(self):
        result = derive([rally(end_ms=None), contact("first", 2000, "A"), contact("last", 4000, "B")])
        self.assert_range(window(result, "ball_flight", "first"), 2000, 4000)
        for strategy, anchor in (("ball_flight", "last"), ("hand_technique", "first"),
                                  ("footwork", "first"), ("rally", "rally-1")):
            with self.subTest(strategy=strategy):
                item = window(result, strategy, anchor)
                self.assertEqual(item["status"], "unavailable")
                self.assertIsNone(item["range"])
                self.assertTrue(item["reasons"])
        items = records()
        items[0]["end_ms"] = None
        explicit_phases = window(derive(items), "footwork", "contact-3")
        self.assertEqual(explicit_phases["status"], "unavailable")
        self.assertIsNone(explicit_phases["range"])

    def test_rally_requires_independent_serve_and_dead_ball(self):
        for omitted in ("serve", "dead_ball"):
            with self.subTest(omitted=omitted):
                items = [item for item in records() if item["kind"] != omitted]
                item = window(derive(items), "rally", "rally-1")
                self.assertEqual(item["status"], "unavailable")
                self.assertIsNone(item["range"])
                self.assertTrue(item["reasons"])

    def test_ambiguous_rally_terminals_are_candidates_not_precise_ranges(self):
        for extra in (contact("serve-2", 1700, "A", kind="serve"),
                      record("dead-2", "dead_ball", time_ms=8700)):
            with self.subTest(kind=extra["kind"]):
                item = window(derive([*records(), extra]), "rally", "rally-1")
                self.assertEqual(item["status"], "candidate")
                self.assertTrue(item["reasons"])

    def test_rally_serve_must_precede_other_contact_uncertainty_envelopes(self):
        cases = (
            ("earlier_contact", {}, contact("other", 1500, "B"), "serve_not_first_contact"),
            ("same_time", {}, contact("other", 3500, "B"), "ambiguous_serve_order"),
            ("later_nominal_overlaps", {},
             contact("other", 4000, "B", uncertainty={"start_ms": 3000, "end_ms": 4200}),
             "ambiguous_serve_order"),
            ("uncertain_serve", {"uncertainty": {"start_ms": 3000, "end_ms": 4000}},
             contact("other", 3750, "B"), "ambiguous_serve_order"),
            ("later_envelope_touches", {"uncertainty": {"start_ms": 3000, "end_ms": 4000}},
             contact("other", 4500, "B", uncertainty={"start_ms": 4000, "end_ms": 4600}),
             "ambiguous_serve_order"),
            ("earlier_envelope_touches", {"uncertainty": {"start_ms": 3000, "end_ms": 4000}},
             contact("other", 2500, "B", uncertainty={"start_ms": 2400, "end_ms": 3000}),
             "ambiguous_serve_order"),
        )
        for name, serve_changes, other, reason in cases:
            with self.subTest(case=name):
                items = [rally(), contact("serve-1", 3500, "A", kind="serve", **serve_changes),
                         other, record("dead-1", "dead_ball", time_ms=8500)]
                before = deepcopy(items)
                result = derive(items)
                item = window(result, "rally", "rally-1")
                self.assertEqual(item["status"], "candidate")
                self.assertIsNone(item["range"])
                self.assertIn(reason, item["reasons"])
                self.assertEqual({ref["record_id"] for ref in item["annotation_refs"]},
                                 {"rally-1", "serve-1", "other", "dead-1"})
                self.assertEqual(items, before)

    def test_rally_retains_all_conflicting_revisions_regardless_of_input_order(self):
        items = [
            {**rally(), "revision": 7},
            contact("serve-1", 3500, "A", kind="serve", revision=4),
            contact("earlier", 1500, "B", revision=2),
            contact("simultaneous", 3500, "C", revision=5),
            contact("overlapping-later", 4000, "D", revision=6,
                    uncertainty={"start_ms": 3400, "end_ms": 4200}),
            contact("separated-later", 7000, "B", revision=8),
            record("dead-1", "dead_ball", time_ms=8500, revision=9),
        ]
        expected_refs = {("rally-1", 7), ("serve-1", 4), ("earlier", 2),
                         ("simultaneous", 5), ("overlapping-later", 6), ("dead-1", 9)}
        baseline = None
        for order in (items, list(reversed(items)), items[3:] + items[:3]):
            with self.subTest(order=[item["record_id"] for item in order]):
                before = deepcopy(order)
                item = window(derive(order), "rally", "rally-1")
                self.assertEqual(item["status"], "candidate")
                self.assertIsNone(item["range"])
                self.assertTrue({"serve_not_first_contact", "ambiguous_serve_order"} <= set(item["reasons"]))
                refs = {(ref["record_id"], ref["revision"]) for ref in item["annotation_refs"]}
                self.assertTrue(expected_refs <= refs)
                self.assertEqual(len(refs), len(item["annotation_refs"]))
                self.assertEqual(order, before)
                if baseline is not None:
                    self.assertEqual(item, baseline)
                baseline = item

    def test_strictly_separated_serve_and_later_contact_keep_ready_rally(self):
        for other in (contact("later", 4500, "B"),
                      contact("later", 4500, "B", uncertainty={"start_ms": 3501, "end_ms": 5000})):
            with self.subTest(other=other):
                result = derive([rally(), contact("serve-1", 3500, "A", kind="serve"),
                                 other, record("dead-1", "dead_ball", time_ms=8500)])
                item = window(result, "rally", "rally-1")
                self.assert_range(item, 3500, 8500)
                self.assertFalse({"serve_not_first_contact", "ambiguous_serve_order"} & set(item["reasons"]))

    def test_serve_order_conflict_does_not_suppress_other_window_strategies(self):
        result = derive([rally(), contact("earlier", 1500, "B"),
                         contact("serve-1", 3500, "A", kind="serve"),
                         record("dead-1", "dead_ball", time_ms=8500)])
        self.assert_range(window(result, "ball_flight", "earlier"), 1500, 3500)
        self.assert_range(window(result, "ball_flight", "serve-1"), 3500, 8500)
        self.assert_range(window(result, "hand_technique", "serve-1"), 3000, 4000)
        self.assert_range(window(result, "footwork", "serve-1"), 1500, 5500, "candidate")
        for item in result["windows"]:
            if item["strategy"] != "rally":
                self.assertFalse({"serve_not_first_contact", "ambiguous_serve_order"} & set(item["reasons"]))

    def test_context_rules_clip_with_explicit_candidate_status(self):
        result = derive(rules={"hand_before_ms": 2000, "hand_after_ms": 300,
                               "rally_before_ms": 1000, "rally_after_ms": 1000})
        self.assert_range(window(result, "hand_technique", "serve-1"), 1000, 1800, "candidate")
        self.assert_range(window(result, "rally", "rally-1"), 1000, 9000, "candidate")
        self.assertTrue(window(result, "hand_technique", "serve-1")["reasons"])

    def test_hand_and_explicit_footwork_stop_at_dead_ball_before_rally_end(self):
        items = records()
        next(item for item in items if item["kind"] == "dead_ball")["time_ms"] = 6200
        before = deepcopy(items)
        result = derive(items)
        self.assert_range(window(result, "hand_technique", "contact-3"), 5500, 6200, "candidate")
        self.assert_range(window(result, "footwork", "contact-3"), 4500, 6200, "candidate")
        for strategy in ("hand_technique", "footwork"):
            item = window(result, strategy, "contact-3")
            self.assertTrue(item["reasons"])
            self.assertIn({"record_id": "dead-1", "revision": 1}, item["annotation_refs"])
        self.assertEqual(items, before)

    def test_uncertainty_expands_hand_context_without_moving_the_anchor(self):
        items = records()
        mark = next(item for item in items if item["record_id"] == "contact-3")
        mark.update(uncertainty={"start_ms": 5900, "end_ms": 6100},
                    visibility="occluded", unknown_reason="contact hidden", labels={"technique": "unknown"})
        before = deepcopy(items)
        result = derive(items)
        self.assert_range(window(result, "hand_technique", "contact-3"), 5400, 6600, "candidate")
        self.assertTrue(window(result, "hand_technique", "contact-3")["reasons"])
        self.assertEqual(items, before)

    def test_simultaneous_or_overlapping_uncertain_contacts_are_not_precise(self):
        for following in (
            [contact("next-a", 3500, "B"), contact("next-b", 3500, "C")],
            [contact("next-a", 3500, "B", uncertainty={"start_ms": 2500, "end_ms": 3600})],
        ):
            with self.subTest(following=following):
                first = contact("first", 2500, "A", uncertainty={"start_ms": 2400, "end_ms": 2600})
                result = derive([rally(), first, *following, record("dead-1", "dead_ball", time_ms=8500)])
                item = window(result, "ball_flight", "first")
                self.assertEqual(item["status"], "candidate")
                self.assertTrue(item["reasons"])

    def test_ball_retains_competing_dead_marks_and_later_nominal_uncertain_contact(self):
        cases = (
            ([record("dead-a", "dead_ball", time_ms=8500),
              record("dead-b", "dead_ball", time_ms=8700)], {"dead-a", "dead-b"}),
            ([contact("next", 3000, "B"),
              contact("possible-next", 4000, "C", uncertainty={"start_ms": 2500, "end_ms": 4500}),
              record("dead-1", "dead_ball", time_ms=8500)], {"next", "possible-next"}),
        )
        for terminals, expected_refs in cases:
            with self.subTest(terminals=expected_refs):
                result = derive([rally(), contact("first", 2000, "A"), *terminals])
                item = window(result, "ball_flight", "first")
                self.assertEqual(item["status"], "candidate")
                self.assertTrue(item["reasons"])
                self.assertLessEqual(item["range"]["end_ms"], 8500)
                self.assertTrue(expected_refs <= {ref["record_id"] for ref in item["annotation_refs"]})

    def test_missing_footwork_phase_and_no_phases_remain_candidates(self):
        items = [item for item in records() if item["record_id"] != "phase-landing"]
        incomplete = window(derive(items), "footwork", "contact-3")
        self.assert_range(incomplete, 4500, 7000, "candidate")
        self.assertTrue(incomplete["reasons"])
        absent = window(derive(), "footwork", "contact-2")
        self.assert_range(absent, 1500, 5500, "candidate")
        self.assertTrue(absent["reasons"])

    def test_complete_but_reversed_footwork_stage_order_is_only_candidate(self):
        items = records()
        stages = [item for item in items if item["kind"] == "movement"]
        times = [(item["start_ms"], item["end_ms"]) for item in stages]
        for item, (start, end) in zip(stages, reversed(times)):
            item.update(start_ms=start, end_ms=end)
        item = window(derive(items), "footwork", "contact-3")
        self.assert_range(item, 4500, 7000, "candidate")
        self.assertIn("phase_order_conflict", item["reasons"])

    def test_explicit_not_applicable_phase_can_be_absent_but_cannot_also_be_annotated(self):
        items = [item for item in records() if item["record_id"] != "phase-landing"]
        next(item for item in items if item["record_id"] == "contact-3")["phase_not_applicable"] = ["landing"]
        result = derive(items)
        self.assert_range(window(result, "footwork", "contact-3"), 4500, 7000)
        mark = next(item for item in result["annotations"] if item["record_id"] == "contact-3")
        self.assertEqual(mark["phase_not_applicable"], ["landing"])
        items.extend(item for item in phase_records() if item["phase"] == "landing")
        with self.assertRaises(WindowError) as raised:
            derive(items)
        self.assertEqual(raised.exception.code, "relation_mismatch")

    def test_duplicate_phase_intervals_do_not_appear_fully_resolved(self):
        items = records()
        items.append(record("second-recovery", "movement", start_ms=6800, end_ms=7200,
                            anchor_id="contact-3", phase="recovery", player_id="A"))
        item = window(derive(items), "footwork", "contact-3")
        self.assertEqual(item["status"], "candidate")
        self.assertIn("repeated_phase_intervals", item["reasons"])

    def test_movement_never_infers_a_player_or_borrows_another_anchor(self):
        for changes in ({"player_id": "B"}, {"anchor_id": "contact-2"},
                        {"anchor_id": "missing"}, {"rally_id": "rally-2"}):
            with self.subTest(changes=changes), self.assertRaises(WindowError):
                items = records()
                items[-1].update(changes)
                derive(items)
        result = derive()
        # Both A and B occur before A's six explicitly linked phases.
        self.assertEqual(window(result, "footwork", "serve-1")["status"], "candidate")
        self.assertEqual(window(result, "footwork", "contact-2")["status"], "candidate")

    def test_invalid_bounds_relations_and_point_interval_shapes_reject_the_batch(self):
        malformed = [
            [rally(start_ms=-1)], [rally(start_ms=9000, end_ms=9000)],
            [rally(end_ms=12001)], [rally(), rally("rally-2", 8000, 11000)],
            [rally(), contact(time_ms=-1)], [rally(), contact(time_ms=12001)],
            [rally(), contact(time_ms=9000)], [rally(), contact(asset_id="other")],
            [rally(), contact(rally_id="missing")], [rally(), contact(revision=0)],
            [rally(), contact(uncertainty={"start_ms": 3501, "end_ms": 3600})],
            [rally(), contact(uncertainty={"start_ms": 900, "end_ms": 3600})],
            [rally(), record("not-a-point", "contact", start_ms=2000, end_ms=3000)],
            [rally(), record("not-an-interval", "movement", time_ms=2000,
                             anchor_id="contact-2", phase="arrival", player_id="B"), contact()],
        ]
        for index, items in enumerate(malformed):
            with self.subTest(case=index):
                with self.assertRaises(WindowError) as raised:
                    derive(items)
                self.assertTrue(raised.exception.code)

    def test_duplicate_record_ids_do_not_silently_select_a_revision(self):
        items = records()
        items.append({**items[2], "revision": 2, "time_ms": 4000})
        with self.assertRaises(WindowError):
            derive(items)

    def test_bad_future_record_is_not_hidden_by_online_cutoff(self):
        for value in (12001, True, 3500.5, float("nan"), float("inf"), "3500"):
            with self.subTest(time_ms=value), self.assertRaises(WindowError):
                derive([rally(), contact(time_ms=value)], available_until_ms=2000)

    def test_invalid_rule_values_are_not_coerced_or_silently_clamped(self):
        for value in (-1, 10001, True, float("nan"), float("inf"), "500"):
            with self.subTest(value=value), self.assertRaises(WindowError):
                derive(rules={"hand_before_ms": value})

    def test_online_cutoff_hides_future_anchors_and_pending_ranges(self):
        result = derive(available_until_ms=3000)
        self.assertFalse(any(item["anchor_id"] in ("contact-2", "contact-3")
                             for item in result["windows"]))
        for strategy, anchor in (("ball_flight", "serve-1"), ("rally", "rally-1"),
                                  ("hand_technique", "serve-1")):
            with self.subTest(strategy=strategy):
                item = window(result, strategy, anchor)
                self.assertEqual(item["status"], "pending")
                self.assertIsNone(item["range"])
                self.assertTrue(item["reasons"])
        self.assertEqual({item["record_id"] for item in result["annotations"]}, {"rally-1", "serve-1"})
        self.assertTrue(all(item["latest_source_time_ms"] <= 3000 for item in result["windows"]))

    def test_offline_future_context_is_explicit(self):
        item = window(derive(), "ball_flight", "contact-3")
        self.assertTrue(item["future_context_used"])
        self.assertEqual(item["latest_source_time_ms"], 8500)
        self.assertEqual(item["lookahead_ms"], 2500)

    def test_evidence_interval_delays_contact_visibility_and_contributes_offline_lookahead(self):
        delayed = contact("delayed", 2500, "B", evidence=[{
            "kind": "source_interval", "asset_id": "court-a", "start_ms": 2000, "end_ms": 8500,
        }])
        items = [rally(), contact("first", 1500, "A", kind="serve"), delayed,
                 record("dead-1", "dead_ball", time_ms=8500)]
        online = derive(items, available_until_ms=3000)
        self.assertNotIn("delayed", {item["record_id"] for item in online["annotations"]})
        self.assertFalse(any(item["anchor_id"] == "delayed" for item in online["windows"]))
        waiting = window(online, "ball_flight", "first")
        self.assertEqual(waiting["status"], "pending")
        self.assertIsNone(waiting["range"])
        self.assertIsNone(waiting["wait_ms"])
        self.assertNotIn("delayed", {ref["record_id"] for ref in waiting["annotation_refs"]})
        offline = window(derive(items), "hand_technique", "delayed")
        self.assertGreaterEqual(offline["latest_source_time_ms"], 8500)
        self.assertGreaterEqual(offline["lookahead_ms"], 6000)
        self.assertTrue(offline["future_context_used"])

    def test_conflicting_evidence_time_aliases_reject_without_pts_even_before_online_filtering(self):
        items = [rally(), contact("first", 2000, "A", evidence=[{"at_ms": 8500, "time_ms": 1500}])]
        for cutoff in (None, 2500):
            with self.subTest(cutoff=cutoff):
                with self.assertRaises(WindowError) as raised:
                    derive(items, available_until_ms=cutoff)
                self.assertEqual(raised.exception.code, "invalid_boundary")

    def test_evidence_intervals_are_paired_half_open_and_contain_all_declared_points(self):
        invalid = (
            {"start_ms": 1500}, {"end_ms": 2500},
            {"start_ms": 2500, "end_ms": 1500}, {"start_ms": 1500, "end_ms": 1500},
            {"start_ms": 1500, "end_ms": 2500, "at_ms": 1499},
            {"start_ms": 1500, "end_ms": 2500, "at_ms": 2500},
            {"start_ms": 1500, "end_ms": 2500, "time_ms": 2500},
            {"start_ms": 1500, "end_ms": 2500, "at_ms": 2501, "time_ms": 2501},
        )
        for evidence in invalid:
            with self.subTest(evidence=evidence):
                items = [rally(), contact("first", 2000, "A", evidence=[evidence])]
                with self.assertRaises(WindowError) as raised:
                    derive(items)
                self.assertEqual(raised.exception.code, "invalid_boundary")

    def test_consistent_evidence_preserves_image_region_and_uses_latest_interval_end(self):
        cases = (
            {"at_ms": 8500}, {"time_ms": 8500}, {"at_ms": 8500, "time_ms": 8500},
            {"start_ms": 1900, "end_ms": 8500},
            {"kind": "image_region", "at_ms": 2000, "time_ms": 2000,
             "start_ms": 1900, "end_ms": 8500,
             "region": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                items = [rally(), contact("first", 2000, "A", evidence=[deepcopy(evidence)])]
                before = deepcopy(items)
                offline = derive(items)
                item = window(offline, "hand_technique", "first")
                self.assertEqual(item["latest_source_time_ms"], 8500)
                self.assertEqual(item["lookahead_ms"], 6500)
                self.assertTrue(item["future_context_used"])
                mapped = next(row for row in offline["annotations"] if row["record_id"] == "first")
                self.assertEqual(mapped["evidence"], [evidence])
                online = derive(items, available_until_ms=2500)
                self.assertFalse(any(row["anchor_id"] == "first" for row in online["windows"]))
                self.assertNotIn("first", {row["record_id"] for row in online["annotations"]})
                self.assertEqual(items, before)

    def test_untimed_evidence_requires_explicit_latest_evidence_watermark(self):
        delayed = contact("delayed", 2500, "B", evidence=[{"kind": "review_note", "note": "occlusion review"}])
        items = [rally(), delayed]
        with self.assertRaises(WindowError) as raised:
            derive(items, available_until_ms=3000)
        self.assertEqual(raised.exception.code, "unknown_evidence_time")
        delayed["latest_evidence_ms"] = 8500
        online = derive(items, available_until_ms=3000)
        self.assertFalse(any(item["anchor_id"] == "delayed" for item in online["windows"]))
        offline = window(derive(items), "hand_technique", "delayed")
        self.assertEqual(offline["latest_source_time_ms"], 8500)
        self.assertEqual(offline["lookahead_ms"], 6000)

    def test_manifest_is_training_only_even_when_source_is_general(self):
        items, asset = records(), source()
        before = deepcopy((items, asset))
        result = derive(items, asset)
        self.assertEqual(result["format"], "badmintonTV.training-contact-windows")
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["usage_scope"], "training_only")
        self.assertIs(result["production_eligible"], False)
        self.assertNotIn("segments", result)
        self.assertEqual((items, asset), before)
        self.assertEqual(result, derive(items, asset))

    def test_annotations_source_rights_revisions_and_unknown_are_preserved(self):
        items = records()
        mark = next(item for item in items if item["record_id"] == "contact-3")
        mark.update(revision=4, labels={"technique": "unknown", "footwork": ["landing"]},
                    visibility="occluded", unknown_reason="contact hidden",
                    review_status="unreviewed", provenance={"reviewer_type": "agent"})
        for scope in ("general", "training_only"):
            with self.subTest(scope=scope):
                asset = source(usage_scope=scope, provenance={"usage_scope": scope})
                result = derive(items, asset)
                self.assertEqual(result["source"]["asset_id"], asset["asset_id"])
                self.assertEqual(result["source"]["sha256"], asset["sha256"])
                self.assertEqual(result["source"]["usage_scope"], scope)
                self.assertEqual(result["source"]["rights"], asset["rights"])
                self.assertEqual(result["source"]["provenance"], asset["provenance"])
                self.assertEqual({item["record_id"]: item for item in result["annotations"]},
                                 {item["record_id"]: item for item in items})
                for strategy in ("ball_flight", "hand_technique", "footwork"):
                    item = window(result, strategy, "contact-3")
                    self.assertEqual(item["labels"], mark["labels"])
                    self.assertIn({"record_id": "contact-3", "revision": 4}, item["annotation_refs"])
                    self.assertEqual(item["rule_version"], result["rule_version"])
                    self.assertEqual(item["usage_scope"], "training_only")
                    self.assertFalse(item["production_eligible"])
                    self.assertEqual(item["pts"]["status"], "not_provided")
                next(item for item in result["annotations"] if item["record_id"] == "contact-3")["revision"] = 900
                self.assertEqual(mark["revision"], 4)


class SourceClockTests(unittest.TestCase):
    def test_millisecond_rounding_that_excludes_anchor_pts_is_explicit_candidate(self):
        clock = SourceClock([0, 2000, 3999, 4000, 6000, 10000], "1/2000")
        items = [rally(), contact("first", 2000, "A", source_pts=3999),
                 contact("next", 3000, "B", source_pts=6000)]
        before = deepcopy(items)
        result = derive(items, source(time_base="1/2000"), clock=clock)
        item = window(result, "ball_flight", "first")
        self.assertEqual(item["range"], {"start_ms": 2000, "end_ms": 3000})
        self.assertEqual(item["status"], "candidate")
        self.assertIn("anchor_pts_outside_millisecond_range", item["reasons"])
        self.assertEqual(item["anchor_source_pts"], 3999)
        self.assertEqual(item["anchor_time_rounding_delta_ms"], "1/2")
        self.assertEqual(item["pts"]["first_pts"], 4000)
        self.assertEqual(items, before)
        mark = next(row for row in result["annotations"] if row["record_id"] == "first")
        self.assertEqual((mark["time_ms"], mark["source_pts"]), (2000, 3999))

    def test_nonzero_origin_and_vfr_use_actual_pts_with_half_open_end(self):
        for origin, start, end in ((None, 70, 200), (8970, 100, 230)):
            with self.subTest(origin=origin):
                reference = {"relative_path": "data/raw/fixture.pts.jsonl", "sha256": "b" * 64}
                clock = SourceClock([9000, 9033, 9070, 9137, 9200], "1/1000",
                                    origin_pts=origin, reference=reference)
                items = [rally(start_ms=0, end_ms=500),
                         contact("first", start, "A", source_pts=9070),
                         contact("next", end, "B", source_pts=9200)]
                item = window(derive(items, source(duration_ms=500), clock=clock), "ball_flight", "first")
                self.assertEqual(item["range"], {"start_ms": start, "end_ms": end})
                self.assertEqual(item["pts"]["status"], "mapped")
                self.assertEqual(item["pts"]["first_frame_index"], 2)
                self.assertEqual(item["pts"]["end_frame_index_exclusive"], 4)
                self.assertEqual(item["pts"]["frame_count"], 2)
                self.assertEqual(item["pts"]["first_pts"], 9070)
                self.assertEqual(item["pts"]["last_pts"], 9137)
                self.assertEqual(item["pts"]["next_pts"], 9200)
                self.assertEqual(item["pts"]["origin_pts"], 9000 if origin is None else origin)
                self.assertEqual(item["pts"]["reference"], reference)

    def test_rational_pts_threshold_does_not_round_a_frame_across_boundary(self):
        clock = SourceClock([450000, 450002, 450003, 450004, 450006], "1/3000")
        items = [rally(start_ms=0, end_ms=5), contact("first", 1, "A"), contact("next", 2, "B")]
        item = window(derive(items, source(duration_ms=5, time_base="1/3000"), clock=clock),
                      "ball_flight", "first")
        self.assertEqual(item["pts"]["first_pts"], 450003)
        self.assertEqual(item["pts"]["last_pts"], 450004)
        self.assertEqual(item["pts"]["next_pts"], 450006)
        self.assertEqual(item["pts"]["frame_count"], 2)

    def test_gap_without_source_frames_is_explicit_candidate(self):
        clock = SourceClock([9000, 9033, 9070], "1/1000")
        items = [rally(start_ms=0, end_ms=100), contact("first", 40, "A"), contact("next", 50, "B")]
        item = window(derive(items, source(duration_ms=100), clock=clock), "ball_flight", "first")
        self.assertEqual(item["status"], "candidate")
        self.assertEqual(item["pts"]["frame_count"], 0)
        self.assertIsNone(item["pts"]["first_pts"])
        self.assertIsNone(item["pts"]["last_pts"])
        self.assertTrue(item["reasons"])

    def test_bad_pts_sequences_time_bases_and_origins_fail_closed(self):
        for pts, time_base, origin in (([], "1/1000", None), ([1, 1], "1/1000", None),
                                      ([2, 1], "1/1000", None), ([1, True], "1/1000", None),
                                      ([1, 2], "0", None), ([1, 2], "1/0", None),
                                      ([1, 2], "-1/1000", None), ([1, 2], "1/1000", 2)):
            with self.subTest(pts=pts, time_base=time_base, origin=origin):
                with self.assertRaises(WindowError) as raised:
                    SourceClock(pts, time_base, origin_pts=origin)
                self.assertEqual(raised.exception.code, "invalid_pts")

    def test_mark_pts_must_exist_and_agree_with_source_clock(self):
        clock = SourceClock([9000, 9033, 9070], "1/1000")
        for time, pts in ((33, 9070), (33, 9034)):
            with self.subTest(time=time, pts=pts):
                with self.assertRaises(WindowError) as raised:
                    derive([rally(start_ms=0, end_ms=100), contact(time_ms=time, source_pts=pts)],
                           source(duration_ms=100), clock=clock)
                self.assertEqual(raised.exception.code, "invalid_pts")
        for asset in (source(duration_ms=100, time_base="1/90000"), source(duration_ms=70)):
            with self.subTest(asset=asset):
                with self.assertRaises(WindowError) as raised:
                    derive([rally(start_ms=0, end_ms=asset["duration_ms"])], asset, clock=clock)
                self.assertEqual(raised.exception.code, "invalid_pts")


class VerifiedClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index = self.root / "data" / "indexes" / "source.pts.jsonl"
        self.index.parent.mkdir(parents=True)
        payload = "".join(json.dumps({"frame_index": index, "pts": pts}) + "\n"
                          for index, pts in enumerate((10033, 10070, 10137))).encode("utf-8")
        self.index.write_bytes(payload)
        self.asset = source(duration_ms=500, probe={
            "source_sha256": "a" * 64, "source_size_bytes": 128,
            "start_pts": 10000, "start_time": "10.000",
            "pts_index": {
                "relative_path": "data/indexes/source.pts.jsonl", "format": "jsonl", "complete": True,
                "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload),
                "time_base": "1/1000", "frame_count": 3,
            },
        })

    def read(self, asset):
        before = deepcopy(asset)
        with patch("subprocess.run") as run, patch("subprocess.Popen") as popen, \
                patch("packages.render.storage.reservation") as reserve:
            try:
                return read_verified_clock(asset, self.root)
            finally:
                run.assert_not_called()
                popen.assert_not_called()
                reserve.assert_not_called()
                self.assertEqual(asset, before)

    def test_verified_index_uses_probe_origin_even_when_first_displayed_pts_is_later(self):
        before = self.index.read_bytes()
        clock = self.read(self.asset)
        self.assertEqual(clock.origin_pts, 10000)
        self.assertEqual(clock.pts[0], 10033)
        self.assertEqual(clock.time_ms(10033), 33)
        self.assertEqual(clock.select(0, 33)["frame_count"], 0)
        selected = clock.select(33, 70)
        self.assertEqual(selected["first_pts"], 10033)
        self.assertEqual(selected["last_pts"], 10033)
        self.assertEqual(selected["next_pts"], 10070)
        self.assertEqual(selected["frame_count"], 1)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertFalse((self.root / "render").exists())

    def test_incomplete_or_wrong_source_binding_is_rejected(self):
        for field, value in (("complete", False), ("source_sha256", "b" * 64),
                             ("source_size_bytes", 129)):
            with self.subTest(field=field):
                asset = deepcopy(self.asset)
                target = asset["probe"]["pts_index"] if field == "complete" else asset["probe"]
                target[field] = value
                with self.assertRaises(WindowError) as raised:
                    self.read(asset)
                self.assertEqual(raised.exception.code, "invalid_pts")

    def test_missing_origin_cannot_fall_back_to_first_pts(self):
        asset = deepcopy(self.asset)
        del asset["probe"]["start_pts"]
        with self.assertRaises(WindowError) as raised:
            self.read(asset)
        self.assertEqual(raised.exception.code, "invalid_pts")


class ContactProductionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def request(self, timeline, **parameters):
        return {
            "schema_version": "1.0", "job_id": "contact-test", "attempt_id": "attempt-1",
            "operation": "render", "output_dir": "render/jobs/contact-test/attempt-1",
            "assets": [source()], "parameters": {"timeline": timeline, **parameters},
        }

    def production_timeline(self, **changes):
        return {
            "schema_version": "1.0", "timeline_id": "general-edit",
            "segments": [{"segment_id": "general-clip", "asset_id": "court-a",
                          "in_ms": 1500, "out_ms": 3500, "review_status": "confirmed"}],
            **changes,
        }

    def training_timelines(self):
        manifest = derive()
        variants = [manifest, {**manifest, **self.production_timeline()},
                    self.production_timeline(usage_scope="training_only"),
                    self.production_timeline(provenance={"usage_scope": "training_only"})]
        for flag in ({"usage_scope": "training_only"}, {"provenance": {"usage_scope": "training_only"}}):
            timeline = self.production_timeline()
            timeline["segments"][0].update(flag)
            variants.append(timeline)
        return variants

    def test_training_manifest_and_deceptive_segments_reject_before_media_or_reservation(self):
        for index, timeline in enumerate(self.training_timelines()):
            for preview in (False, True):
                with self.subTest(variant=index, preview=preview):
                    with ExitStack() as stack:
                        hooks = [stack.enter_context(patch(target)) for target in (
                            "packages.render.engine.normalize_timeline", "packages.render.engine.shutil.which",
                            "packages.render.engine.Runner.capture", "packages.render.engine.Runner.probe",
                            "packages.render.engine.Runner.ffmpeg", "packages.render.engine.reservation",
                            "packages.render.engine.subprocess.Popen",
                        )]
                        result = render(self.request(timeline, preview=preview, research_preview=preview),
                                        RenderConfig(storage_root=self.root))
                    for hook in hooks:
                        hook.assert_not_called()
                    self.assertEqual(result["status"], "blocked")
                    self.assertEqual(result["error"]["code"], "TRAINING_ONLY")
                    self.assertEqual(result["artifacts"], [])
                    self.assertEqual(list(self.root.iterdir()), [])

    def test_direct_timeline_normalization_cannot_accept_training_manifest_or_scope(self):
        for index, timeline in enumerate(self.training_timelines()):
            with self.subTest(variant=index):
                with self.assertRaises(RenderError) as raised:
                    normalize_timeline(timeline, assets_by_id([source()]), preview=True, research_preview=True)
                self.assertEqual(raised.exception.code, "TRAINING_ONLY")

    def test_ordinary_general_timeline_retains_existing_path(self):
        timeline = self.production_timeline()
        result = normalize_timeline(timeline, assets_by_id([source()]))
        self.assertEqual(result["segments"][0]["asset_id"], "court-a")
        self.assertEqual(result["segments"][0]["in_ms"], 1500)
        with patch("packages.render.engine.shutil.which", return_value=None) as which, \
                patch("packages.render.engine.subprocess.Popen") as popen, \
                patch("packages.render.engine.reservation") as reserve:
            rendered = render(self.request(timeline), RenderConfig(storage_root=self.root))
        self.assertEqual(rendered["error"]["code"], "not_installed")
        which.assert_called_once()
        popen.assert_not_called()
        reserve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
