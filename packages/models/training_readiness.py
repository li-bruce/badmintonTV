"""Read-only, deterministic readiness audit of the public training snapshot.

This module defines an internal audit report, not another snapshot format. It
does not authenticate reviewer claims, verify media bytes/PTS, or assess model
quality. No contract or ML package is imported until audit_snapshot is called.
"""

from collections import Counter
from collections.abc import Mapping
import json
import re

from .training_grouping import UNKNOWN, audit_groups


SUBJECT_FIELDS = ("subject_role", "subject_person_id")
VALUES = ("present", "absent", "unknown", "not_applicable", "unlabeled", "unobservable")
LIMITATIONS = [
    "Review, identity and provenance fields are declarations, not authenticated human truth.",
    "Match confirmation follows the public quality_summary.unconfirmed_match_asset_ids result; confirmed group evidence is still a metadata claim.",
    "Missing source references do not prove independent matches; history omitted from the snapshot cannot be recovered without separately supplied source metadata.",
    "Source metadata matching checks identity fields only; the caller must freeze its manifest hash and verify actual media/PTS separately.",
    "Implicit unlabeled coverage means an applicable label is absent from a record; it does not invent negative labels or unannotated participant slots.",
    "Readiness is a preparation gate, not expert semantics, accuracy, split balance or sufficient sample-size certification.",
]


def _ordered(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _key(item):
    return (item["asset_id"], item["record_id"], item.get("label_id"),
            *(item.get(field) for field in SUBJECT_FIELDS))


def _subject(item):
    return {field: item[field] for field in SUBJECT_FIELDS if field in item}


def _judgement_identity(record, judgement):
    role = (record.get("state") or {}).get(judgement.get("subject_role", "self"))
    subject = judgement.get("subject_person_id") or (role.get("person_id") if role else record.get("person_id"))
    return {"asset_id": record["asset_id"], "record_id": record["record_id"],
            "label_id": judgement["label_id"], **_subject(judgement), "subject_person_id": subject}


def _references(metadata, *, history=None):
    """Keep all declared parent edges; malformed metadata must not disappear."""
    if not isinstance(metadata, dict):
        raise TypeError("source provenance must be an object")
    items = [metadata]
    for candidate in (metadata.get("provenance_history", []), history if history is not None else []):
        if not isinstance(candidate, list) or any(not isinstance(entry, dict) for entry in candidate):
            raise TypeError("provenance_history must be a list of objects")
        items.extend(candidate)
    ids, hashes = [], []
    for item in items:
        for singular, plural, target, is_hash in (
            ("source_asset_id", "source_asset_ids", ids, False),
            ("source_sha256", "source_sha256s", hashes, True),
        ):
            values = []
            if item.get(singular) is not None:
                values.append(item[singular])
            if plural in item:
                if not isinstance(item[plural], list):
                    raise TypeError(plural + " must be a list")
                values.extend(item[plural])
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    raise TypeError(singular + " must be a nonblank string or null")
                if is_hash and re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
                    raise ValueError("source_sha256 must be SHA256")
                target.append(value.lower() if is_hash else value)
    return ids, hashes


def _source_rows(assets, splits, source_assets, unconfirmed_matches):
    if source_assets is not None and not isinstance(source_assets, Mapping):
        raise TypeError("source_assets must map asset IDs to source Asset dictionaries")
    assignment = {entry["group_id"]: entry["split"] for entry in splits}
    rows, without_parents, checked, relation_members = [], [], [], {}
    for asset in assets:
        provenance = asset["provenance"]
        ids, hashes = _references(provenance)
        ids.extend(asset.get("root_asset_ids", []))
        hashes.extend(value.lower() for value in asset.get("source_sha256s", []))
        # Collect typed session/group edges in their own namespaces. Later we
        # connect their actual member IDs, never invent pseudo asset IDs.
        for kind, values in (("session", [asset.get("recording_session_id")]),
                             ("group", [asset.get("group_id"), *asset.get("source_group_ids", [])])):
            for value in values:
                if value and value.strip().casefold() not in UNKNOWN:
                    relation_members.setdefault((kind, value), []).append(len(rows))
                elif value and kind == "group" and value in asset.get("source_group_ids", []):
                    ids.append("unknown")  # An explicitly unknown ancestor is a blocker.
        if source_assets is not None:
            source = source_assets.get(asset["asset_id"])
            if not isinstance(source, dict):
                raise ValueError("source Asset missing: " + asset["asset_id"])
            for field in ("asset_id", "sha256", "relative_path", "size_bytes", "duration_ms"):
                left, right = source.get(field), asset[field]
                if field == "sha256" and isinstance(left, str):
                    left, right = left.lower(), right.lower()
                if type(left) is not type(right) or left != right:
                    raise ValueError("source Asset identity mismatch: " + asset["asset_id"] + "." + field)
            if "provenance_history" in source and not isinstance(source["provenance_history"], list):
                raise TypeError("source provenance_history must be a list")
            extra_ids, extra_hashes = _references(source.get("provenance", {}), history=source.get("provenance_history"))
            ids.extend(extra_ids)
            hashes.extend(extra_hashes)
            checked.append(asset["asset_id"])
        if not ids and not hashes:
            without_parents.append(asset["asset_id"])
        # Source metadata can add edges, never elevate snapshot confirmations.
        rows.append({"asset_id": asset["asset_id"], "sha256": asset["sha256"],
                     "match_id": asset.get("match_id"),
                     "match_confirmed": bool(asset.get("match_id")) and asset["asset_id"] not in unconfirmed_matches,
                     "group_id": asset.get("group_id"), "group_confirmed": asset["group_status"] == "confirmed",
                     "source_asset_ids": sorted(set(ids)), "source_sha256s": sorted(set(hashes)),
                     "split": assignment.get(asset.get("group_id"), "unassigned")})
    for members in relation_members.values():
        # Equivalent union edges, including ancestors absent from this snapshot.
        # The anchor is deterministic and always an actual snapshot asset ID.
        members = sorted(set(members), key=lambda index: rows[index]["asset_id"])
        if members:
            anchor = rows[members[0]]["asset_id"]
            for index in members[1:]:
                rows[index]["source_asset_ids"] = sorted(set(rows[index]["source_asset_ids"]) | {anchor})
    return rows, sorted(without_parents), sorted(checked)


def _review_reasons(record):
    review = record["review"]
    reasons = []
    if record["deleted"]:
        reasons.append("deleted")
    if record["visibility"] != "clear":
        reasons.append("visibility_not_clear")
    if review["status"] != "confirmed":
        reasons.append("not_confirmed")
    if review["reviewer_type"] != "human":
        reasons.append("not_human_review")
    if not review["reviewed_at"]:
        reasons.append("reviewed_at_missing")
    revision_audit = record["provenance"].get("revision_audit")
    if not isinstance(revision_audit, dict):
        reasons.append("revision_audit_missing_or_invalid")
    else:
        if revision_audit.get("actor_type") != "human" or revision_audit.get("actor_type") != review["reviewer_type"]:
            reasons.append("revision_audit_actor_mismatch")
        if not revision_audit.get("reviewer") or revision_audit.get("reviewer") != review["reviewer"]:
            reasons.append("revision_audit_reviewer_mismatch")
    if not any(record["evidence"]):
        reasons.append("evidence_missing")
    return reasons


def audit_snapshot(snapshot, *, source_assets=None):
    """Validate a public TrainingSnapshot and return a JSON-safe audit report.

    source_assets optionally maps IDs to separately frozen library Asset dicts.
    Exact ID/hash/path/size/duration equality is required before adding all
    provenance/history parent edges. These assets cannot elevate confirmation.
    Invalid public snapshots or malformed source metadata raise; incomplete
    review/identity/coverage data yield exclusions and blockers. Inputs are not
    mutated. Calls have no filesystem, time, media, or ML side effects.
    """
    from packages.contracts.training import TrainingSnapshot

    # Revalidate even a supplied instance, including its derived view and hash.
    if isinstance(snapshot, TrainingSnapshot):
        snapshot = snapshot.model_dump(mode="json")
    validated = TrainingSnapshot.model_validate(snapshot)
    body = validated.model_dump(mode="json")
    assets = {asset["asset_id"]: asset for asset in body["assets"]}
    unconfirmed_matches = set(body["quality_summary"].get("unconfirmed_match_asset_ids", assets))
    rows, without_parents, checked = _source_rows(body["assets"], body["splits"], source_assets, unconfirmed_matches)
    grouping = audit_groups(rows)
    eligible_assets = set(grouping["eligible_asset_ids"])
    all_labels = {label["label_id"]: label for label in body["taxonomy"]["labels"]}
    labels = {key: label for key, label in all_labels.items() if label.get("selectable", True)}
    public_view = {_key(item): item for item in body["training_view"]}
    public_exclusions = sorted(body["exclusions"], key=_ordered)
    excluded = {}
    for item in public_exclusions:
        key = _key(item)
        if key not in excluded:
            excluded[key] = {**item, "reasons": list(item["reasons"])}
        else:
            excluded[key]["reasons"].extend(item["reasons"])

    by_label = {label_id: {"label_id": label_id, "dimension": label["dimension"], "status": label["status"],
                          "applicable_record_count": 0, "explicit_judgement_count": 0,
                          "implicit_unlabeled_count": 0, "value_counts": Counter({value: 0 for value in VALUES}),
                          "kind_counts": Counter(), "visibility_counts": Counter(),
                          "reviewer_type_counts": Counter(), "subject_role_counts": Counter(), "strict_count": 0}
                for label_id, label in labels.items()}
    records, strict = [], []
    kind_counts, visibility_counts, reviewer_counts, review_counts = Counter(), Counter(), Counter(), Counter()
    values, missing_roles = Counter({value: 0 for value in VALUES}), Counter()
    live_count = explicit_count = implicit_count = 0
    missing_person_count = missing_state_count = missing_evidence_count = 0
    for bundle in body["bundles"]:
        people = {person["person_id"]: person for person in bundle["people"]}
        for record in bundle["records"]:
            common = _review_reasons(record)
            if record["asset_id"] not in eligible_assets:
                common.append("group_ineligible")
            state = record.get("state")
            absent_roles = [role for role in ("self", "opponent", "partner", "opponent_partner")
                            if not state or not state.get(role)]
            person = people.get(record.get("person_id"))
            missing_person = person is None or person["identity_status"] != "confirmed"
            reviewer_type = record["review"].get("reviewer_type") or "unspecified"
            if not record["deleted"]:
                live_count += 1
                kind_counts[record["kind"]] += 1
                visibility_counts[record["visibility"]] += 1
                reviewer_counts[reviewer_type] += 1
                review_counts[record["review"]["status"]] += 1
                missing_person_count += missing_person
                missing_state_count += state is None
                missing_evidence_count += not any(record["evidence"])
                missing_roles.update(absent_roles)
                explicit_labels = {item["label_id"] for item in record["judgements"]}
                for label_id, label in labels.items():
                    if record["kind"] in label["kinds"]:
                        by_label[label_id]["applicable_record_count"] += 1
                        if label_id not in explicit_labels:
                            by_label[label_id]["implicit_unlabeled_count"] += 1
                            implicit_count += 1
            strict_count = 0
            judgement_audit = []
            resolved_counts = Counter(_key(_judgement_identity(record, item)) for item in record["judgements"])
            for judgement in record["judgements"]:
                label_id = judgement["label_id"]
                label = all_labels[label_id]
                identity = _judgement_identity(record, judgement)
                subject_id = identity["subject_person_id"]
                key = _key(identity)
                reasons = list(common)
                if resolved_counts[key] != 1:
                    reasons.append("duplicate_resolved_judgement")
                if not label.get("selectable", True):
                    reasons.append("navigation_label_not_selectable")
                if body["taxonomy"]["status"] != "reviewed" or label["status"] != "defined":
                    reasons.append("provisional_semantics")
                if judgement["value"] not in ("present", "absent"):
                    reasons.append(judgement["value"])
                if judgement["value"] == "absent" and not (judgement.get("reason") or "").strip():
                    reasons.append("absent_reason_missing")
                if judgement["mapping_status"] in ("coarse", "unverified"):
                    reasons.append("mapping_not_semantically_confirmed")
                subject = people.get(subject_id)
                if label["requires_person"] and (subject is None or subject["identity_status"] != "confirmed"):
                    reasons.append("identity_unknown")
                if key in excluded:
                    reasons.extend(excluded[key]["reasons"])
                if key not in public_view:
                    reasons.append("not_in_public_training_view")
                reasons = sorted(set(reasons))
                if reasons:
                    if key not in excluded:
                        excluded[key] = {**identity, "reasons": []}
                    excluded[key]["reasons"].extend(reasons)
                else:
                    # Preserve all public example fields, including subject/role
                    # dimensions as the public contract expands.
                    strict.append(dict(public_view[key]))
                    by_label[label_id]["strict_count"] += 1
                    strict_count += 1
                judgement_audit.append({**judgement, "strict_eligible": not reasons, "exclusion_reasons": reasons})
                if not record["deleted"] and label_id in by_label:
                    explicit_count += 1
                    values[judgement["value"]] += 1
                    coverage = by_label[label_id]
                    coverage["explicit_judgement_count"] += 1
                    coverage["value_counts"][judgement["value"]] += 1
                    coverage["kind_counts"][record["kind"]] += 1
                    coverage["visibility_counts"][record["visibility"]] += 1
                    coverage["reviewer_type_counts"][reviewer_type] += 1
                    coverage["subject_role_counts"][judgement.get("subject_role") or judgement.get("role") or "unspecified"] += 1
            records.append({**record, "judgements": sorted(judgement_audit, key=_ordered),
                            "reviewer_type": record["review"]["reviewer_type"],
                            "evidence_count": len(record["evidence"]), "issues": sorted(set(common)),
                            "missing": {"person_or_confirmed_identity": missing_person, "state": state is None,
                                        "state_roles": absent_roles},
                            "time": {field: record[field] for field in ("at_ms", "start_ms", "end_ms", "uncertainty_start_ms", "uncertainty_end_ms")},
                            "duration_ms": assets[record["asset_id"]]["duration_ms"],
                            "strict_example_count": strict_count})
    missing_bundles = sorted(set(assets) - {bundle["asset"]["asset_id"] for bundle in body["bundles"]})
    blockers = {"public:" + reason for reason in body["quality_summary"]["blockers"]}
    if grouping["issues"]:
        blockers.add("group_audit_failed")
    if missing_bundles:
        blockers.add("annotation_bundle_missing")
    if not strict:
        blockers.add("no_strict_training_examples")
    if body["taxonomy"]["status"] != "reviewed":
        blockers.add("taxonomy_not_reviewed")
    strict_splits = Counter({split: 0 for split in ("train", "validation", "test")})
    strict_splits.update(item["split"] for item in strict)
    for split in ("train", "validation", "test"):
        if not strict_splits[split]:
            blockers.add("missing_" + split + "_examples")
    for item in excluded.values():
        item["reasons"] = sorted(set(item["reasons"]))
    result = {"snapshot_id": body["snapshot_id"], "content_sha256": body["content_sha256"],
              "usage_scope": body["usage_scope"], "trainable": not blockers, "blockers": sorted(blockers),
              "strict_training_view": sorted(strict, key=_ordered),
              "exclusions": sorted(excluded.values(), key=_ordered), "public_exclusions": public_exclusions,
              "group_audit": grouping, "records": sorted(records, key=lambda item: (item["asset_id"], item["record_id"])),
              "coverage": {"assets": {"total": len(assets), "missing_bundle_ids": missing_bundles,
                                       "without_declared_parent_ids": without_parents, "source_assets_checked": checked},
                           "records": {"total": len(records), "live": live_count, "deleted": len(records) - live_count,
                                       "by_kind": kind_counts, "by_visibility": visibility_counts,
                                       "by_reviewer_type": reviewer_counts, "by_review_status": review_counts,
                                       "missing_person_or_confirmed_identity": missing_person_count,
                                       "missing_state": missing_state_count, "missing_state_roles": missing_roles,
                                       "missing_evidence": missing_evidence_count},
                           "judgements": {"explicit": explicit_count, "explicit_unlabeled": values["unlabeled"],
                                          "implicit_unlabeled": implicit_count, "by_value": values},
                           "by_label": [by_label[label_id] for label_id in sorted(by_label)],
                           "navigation_group_count": len(all_labels) - len(labels),
                           "strict_by_split": strict_splits, "public_training_count": len(body["training_view"])},
              "versions": {"schema_version": body["schema_version"], "project_revision": body["project"]["revision"],
                           "catalog_version": body["project"]["catalog_version"],
                           "taxonomy_id": body["taxonomy"]["taxonomy_id"], "taxonomy_version": body["taxonomy"]["version"],
                           "bundle_revisions": {bundle["asset"]["asset_id"]: bundle["revision"] for bundle in body["bundles"]}},
              "public_quality_summary": body["quality_summary"],
              "audit_rules": {"visibility": "clear", "review_status": "confirmed", "reviewer_type": "human",
                              "reviewed_at_required": True, "matching_revision_audit_required": True,
                              "evidence_required": True, "absent_reason_required": True,
                              "required_splits": ["train", "validation", "test"],
                              "media_pts_verified": False, "reviewer_identity_authenticated": False},
              "limitations": LIMITATIONS}
    # Plain dictionaries/lists only, canonical object order, no mutable aliases
    # to model instances or module constants, and non-finite numbers prohibited.
    return json.loads(_ordered(result))
