"""Deterministic grouping audit for internal, normalized training inputs.

This is not a snapshot schema or exporter. The caller must validate the public
snapshot, its integrity and review provenance before normalizing these rows.
Only declared relationships can be checked; a disconnected component does not
prove that two videos are from independent matches.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
import json
import re
from typing import Any


FIELDS = frozenset({"asset_id", "sha256", "match_id", "match_confirmed",
                    "group_id", "group_confirmed", "source_asset_ids",
                    "source_sha256s", "split"})
SPLITS = frozenset({"train", "validation", "test"})
UNKNOWN = frozenset({"", "unknown", "unassigned", "unconfirmed", "null", "none", "n/a", "missing"})
MESSAGES = {
    "empty_input": "No assets were supplied; no group is eligible.",
    "missing_sha256": "Asset content hash is missing or unknown.",
    "missing_match_id": "Match identity is missing or unknown; it is not an independent match.",
    "match_unconfirmed": "Match identity has not been confirmed.",
    "missing_group_id": "Split group identity is missing or unknown.",
    "group_unconfirmed": "Split group identity has not been confirmed.",
    "unknown_source_asset_id": "A declared source asset identity is unknown.",
    "unknown_source_sha256": "A declared source content hash is unknown.",
    "unassigned_split": "Asset has no assigned train/validation/test split.",
    "duplicate_asset_id": "An asset ID occurs in multiple rows; every connected row is retained and rejected.",
    "conflicting_asset_hashes": "One asset ID declares multiple content hashes.",
    "conflicting_groups": "A connected match/source relationship declares multiple split groups.",
    "split_leakage": "Connected assets cross train/validation/test; the entire component is rejected.",
}


def _identity(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string or None")
    if value.strip().casefold() in UNKNOWN:
        return None
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field} must be a canonical identifier without surrounding whitespace or controls")
    return value


def _sha256(value, field):
    value = _identity(value, field)
    if value is not None and re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError(f"{field} must be a SHA256 hex digest or an unknown value")
    return value.lower() if value is not None else None


def audit_groups(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Audit internal normalized rows without files, ML imports or mutation.

    Each row has exactly FIELDS. asset_id is a known canonical string; sha256,
    match_id and group_id can be None/empty/unknown placeholders. Confirmation
    fields are strict booleans, source fields are lists of strings, and split
    is train/validation/test or a missing/unknown value. Malformed structures
    raise TypeError/ValueError; insufficient data produce readable issues.

    Self/source asset IDs share one union namespace, self/source SHA256s share
    another, and known match/group IDs add further edges. Source lists are sets
    of relationships, not paired ID-to-hash assertions. Multiple confirmed
    matches may share one conservative group; multiple group IDs within any
    connected component are a conflict. Unknown values never create identities.

    Return keys: issues (code/message/asset_ids/component_asset_ids/details),
    components (asset_ids/row_count/match_ids/group_ids/splits/eligible/issue_codes),
    and eligible_asset_ids. Any issue rejects its entire connected component;
    no bad row is removed before constructing the closure. Output ordering is
    independent of row/reference order. Eligibility covers grouping only, not
    human truth, label semantics, media integrity, or readiness to train.
    """
    if isinstance(rows, (str, bytes, Mapping)):
        raise TypeError("rows must be an iterable of normalized mappings")
    records, pending = [], []
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) != FIELDS:
            raise ValueError("Each normalized row must contain exactly the documented fields")
        asset_id = _identity(raw["asset_id"], "asset_id")
        if asset_id is None:
            raise ValueError("asset_id must identify a known asset")
        for field in ("match_confirmed", "group_confirmed"):
            if type(raw[field]) is not bool:
                raise TypeError(f"{field} must be a boolean")
        row = {"asset_id": asset_id, "sha256": _sha256(raw["sha256"], "sha256"),
               "match_id": _identity(raw["match_id"], "match_id"),
               "group_id": _identity(raw["group_id"], "group_id")}
        codes = []
        for field in ("sha256", "match_id", "group_id"):
            if row[field] is None:
                codes.append("missing_" + field)
        for field, code in (("match_confirmed", "match_unconfirmed"), ("group_confirmed", "group_unconfirmed")):
            if not raw[field]:
                codes.append(code)
        for field, parser, code in (("source_asset_ids", _identity, "unknown_source_asset_id"),
                                    ("source_sha256s", _sha256, "unknown_source_sha256")):
            if not isinstance(raw[field], list) or any(not isinstance(item, str) for item in raw[field]):
                raise TypeError(f"{field} must be a list of strings")
            values = [parser(item, field) for item in raw[field]]
            if None in values:
                codes.append(code)
            row[field] = sorted({item for item in values if item is not None})
        split = _identity(raw["split"], "split")
        if split is not None and split not in SPLITS:
            raise ValueError("split must be train/validation/test or missing/unknown")
        row["split"] = split or "unassigned"
        if split is None:
            codes.append("unassigned_split")
        records.append(row)
        pending.append(codes)

    parent = list(range(len(records)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seen = {}
    for index, row in enumerate(records):
        tokens = [("asset", row["asset_id"]), ("sha", row["sha256"]),
                  ("match", row["match_id"]), ("group", row["group_id"])]
        tokens += [("asset", value) for value in row["source_asset_ids"]]
        tokens += [("sha", value) for value in row["source_sha256s"]]
        for token in tokens:
            if token[1] is None:
                continue
            if token in seen:
                parent[find(index)] = find(seen[token])
            else:
                seen[token] = index
    connected = defaultdict(list)
    for index in range(len(records)):
        connected[find(index)].append(index)

    issues, components, eligible_ids = [], [], []

    def issue(code, asset_ids, component_ids, **details):
        item = {"code": code, "message": MESSAGES[code], "asset_ids": sorted(asset_ids),
                "component_asset_ids": component_ids, "details": details}
        issues.append(item)

    if not records:
        issue("empty_input", [], [])
    for indices in connected.values():
        members = [records[index] for index in indices]
        ids = sorted({row["asset_id"] for row in members})
        matches = sorted({row["match_id"] for row in members if row["match_id"] is not None})
        groups = sorted({row["group_id"] for row in members if row["group_id"] is not None})
        splits = sorted({row["split"] for row in members})
        first_issue = len(issues)
        for index in indices:
            for code in pending[index]:
                issue(code, [records[index]["asset_id"]], ids)
        for asset_id, count in sorted(Counter(row["asset_id"] for row in members).items()):
            if count > 1:
                issue("duplicate_asset_id", [asset_id], ids, row_count=count)
                hashes = sorted({row["sha256"] for row in members if row["asset_id"] == asset_id and row["sha256"]})
                if len(hashes) > 1:
                    issue("conflicting_asset_hashes", [asset_id], ids, sha256s=hashes)
        if len(groups) > 1:
            issue("conflicting_groups", ids, ids, group_ids=groups)
        assigned = sorted(set(splits) & SPLITS)
        if len(assigned) > 1:
            issue("split_leakage", ids, ids, splits=assigned)
        eligible = first_issue == len(issues)
        components.append({"asset_ids": ids, "row_count": len(members), "match_ids": matches,
                           "group_ids": groups, "splits": splits, "eligible": eligible,
                           "issue_codes": sorted({item["code"] for item in issues[first_issue:]})})
        if eligible:
            eligible_ids.extend(ids)
    # Duplicate input rows can repeat identical insufficiency findings; retain
    # their multiplicity in row_count/duplicate_asset_id rather than noisy issues.
    unique = {json.dumps(item, sort_keys=True, ensure_ascii=False): item for item in issues}
    return {"issues": [unique[key] for key in sorted(unique)],
            "components": sorted(components, key=lambda component: component["asset_ids"]),
            "eligible_asset_ids": sorted(eligible_ids)}
