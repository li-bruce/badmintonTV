"""Standard-library evaluation helpers; these functions do not run a model.

Candidate ``relevance`` is an audited judgement: positive/negative/unknown.
Inputs must already be ranked, matched and deduplicated by actual occurrence.
No confidence score is interpreted as truth. Unit-test fixtures are not model
measurements. Source grouping can only detect relationships present in input.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
import math
from typing import Any


STRATA = ("source_type", "discipline", "camera_type")
SPLITS = frozenset({"train", "validation", "test", "unassigned"})


class EvaluationInputError(ValueError):
    """Invalid evaluation inputs, with JSON-compatible issues for reporting."""

    def __init__(self, message: str, issues: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.issues = issues or []


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError(f"{field} must be a non-empty string")
    return value


def _records(values: Iterable[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    try:
        records = list(values)
    except TypeError as exc:
        raise EvaluationInputError(f"{field} must be an iterable of mappings") from exc
    if any(not isinstance(item, Mapping) for item in records):
        raise EvaluationInputError(f"{field} entries must be mappings")
    return [dict(item) for item in records]


def validate_splits(assets: Iterable[Mapping[str, Any]], *, formal: bool = True) -> dict[str, Any]:
    """Reject split leakage, including transitive derivation/hash relationships.

    Same match_id, same SHA256 (case-insensitive), and provenance.source_asset_id
    form connected groups. A source ID may reference an asset in this manifest
    or an external original shared by several derived assets. Formal evaluation
    rejects absent match_id, empty manifests and unassigned splits. Exploratory
    mode permits missing match_id/unassigned but still rejects known leakage.
    This checks a full split manifest, not just the selected test subset.
    """
    if type(formal) is not bool:
        raise EvaluationInputError("formal must be a boolean")
    rows = _records(assets, "assets")
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if formal and not rows:
        issues.append({"code": "empty_manifest"})
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        parent[find(right)] = find(left)

    seen: dict[tuple[str, str], int] = {}
    by_id: dict[str, int] = {}
    for index, asset in enumerate(rows):
        asset_id = _identifier(asset.get("asset_id"), "asset_id")
        if asset_id in by_id:
            issues.append({"code": "duplicate_asset_id", "asset_id": asset_id})
            union(index, by_id[asset_id])
        by_id[asset_id] = index
        match_id = asset.get("match_id")
        if match_id is None or match_id == "" or (isinstance(match_id, str) and not match_id.strip()):
            issue = {"code": "missing_match_id", "asset_id": asset_id}
            (issues if formal else warnings).append(issue)
            match_id = None
        else:
            _identifier(match_id, "match_id")
        split = asset.get("split", "unassigned")
        if not isinstance(split, str) or split not in SPLITS:
            issues.append({"code": "invalid_split", "asset_id": asset_id})
        elif split == "unassigned":
            (issues if formal else warnings).append({"code": "unassigned_split", "asset_id": asset_id})
        digest = asset.get("sha256")
        if digest not in (None, ""):
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
                raise EvaluationInputError("sha256 must be a 64-digit hexadecimal digest when provided")
            digest = digest.lower()
        provenance = asset.get("provenance")
        if provenance is None:
            provenance = {}
        if not isinstance(provenance, Mapping):
            raise EvaluationInputError("provenance must be a mapping")
        source_id = provenance.get("source_asset_id")
        if source_id is not None:
            _identifier(source_id, "provenance.source_asset_id")
        for key, value in (("match", match_id), ("sha256", digest), ("source", source_id)):
            if value:
                token = (key, value)
                if token in seen:
                    union(index, seen[token])
                else:
                    seen[token] = index
    for index, asset in enumerate(rows):
        source_id = (asset.get("provenance") or {}).get("source_asset_id")
        if source_id in by_id:
            union(index, by_id[source_id])
    connected: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        connected[find(index)].append(index)
    groups = []
    for indices in connected.values():
        ids = sorted(rows[index]["asset_id"] for index in indices)
        splits = sorted({rows[index].get("split", "unassigned") for index in indices
                         if isinstance(rows[index].get("split", "unassigned"), str)})
        groups.append({"asset_ids": ids, "splits": splits})
        if len(splits) > 1:
            issues.append({"code": "split_leakage", "asset_ids": ids, "splits": splits})
    if issues:
        raise EvaluationInputError("Evaluation rejected: invalid or leaking split manifest", issues)
    return {"formal": formal, "asset_count": len(rows), "group_count": len(groups),
            "groups": sorted(groups, key=lambda group: group["asset_ids"]), "warnings": warnings}


def _relevance(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("relevance", "unknown")
    if value is None:
        value = "unknown"
    if not isinstance(value, str) or value not in {"positive", "negative", "unknown"}:
        raise EvaluationInputError("relevance must be positive, negative or unknown")
    return value


def precision_at_k(candidates: Iterable[Mapping[str, Any]], k: int = 20) -> dict[str, Any]:
    """Audited P@min(k,n), bounds for unknowns, and known judgement coverage.

    ``precision`` is undefined while any judgement is unknown. The conservative
    lower bound is not an instruction to relabel unknown examples as negative.
    Missing/null relevance is unknown. Empty results yield null ratios.
    """
    if type(k) is not int or k < 1:
        raise EvaluationInputError("k must be a positive integer")
    rows = _records(candidates, "candidates")
    values = [_relevance(row) for row in rows]
    chosen = values[:k]
    count = len(chosen)
    positive = chosen.count("positive")
    negative = chosen.count("negative")
    unknown = chosen.count("unknown")
    known = positive + negative
    return {
        "requested_k": k, "k": count, "candidate_count": len(rows),
        "positive": positive, "negative": negative, "unknown": unknown,
        "precision": positive / count if count and not unknown else None,
        "lower_bound": positive / count if count else None,
        "upper_bound": (positive + unknown) / count if count else None,
        "known_coverage": known / count if count else None,
        "known_precision": positive / known if known else None,
    }


def recall_from_truth(retrieved_ids: Iterable[str], truth_ids: Iterable[str], *,
                      complete_truth: bool = False) -> float | None:
    """Unique occurrence recall; null for incomplete truth or no positives.

    Caller must restrict retrieved_ids to audited positive matches. Unknown
    regions are outside this denominator and must be reported separately.
    """
    if type(complete_truth) is not bool:
        raise EvaluationInputError("complete_truth must be a boolean")
    retrieved = {_identifier(value, "retrieved_id") for value in retrieved_ids}
    truth = {_identifier(value, "truth_id") for value in truth_ids}
    if not complete_truth or not truth:
        return None
    return len(retrieved & truth) / len(truth)


def evaluate_rankings(queries: Iterable[Mapping[str, Any]], *,
                      assets: Iterable[Mapping[str, Any]], k: int = 20,
                      complete_truth: bool = False, formal: bool = True) -> dict[str, Any]:
    """Evaluate query dictionaries with candidates and optional positive truth.

    Each candidate has asset_id, relevance and (if positive) truth_id identifying
    a deduplicated occurrence/sequence. Each truth item has truth_id/asset_id.
    Pass the complete split manifest so leakage outside test can be detected.
    Formal scoring accepts only test assets and rejects synthetic sources.

    Strata filter the SAME global top-k reviewed candidates, never promote
    lower-ranked candidates to replace another stratum. Recall_at_k is computed
    against that query's supplied complete positive truth, per stratum too.
    No aggregate average hides per-query or empty-stratum results.
    """
    if type(k) is not int or k < 1:
        raise EvaluationInputError("k must be a positive integer")
    if type(complete_truth) is not bool:
        raise EvaluationInputError("complete_truth must be a boolean")
    asset_rows = _records(assets, "assets")
    split_report = validate_splits(asset_rows, formal=formal)
    by_id = {asset["asset_id"]: asset for asset in asset_rows}
    query_rows = _records(queries, "queries")
    results = []
    seen_queries: set[str] = set()

    def referenced_asset(record: Mapping[str, Any]) -> Mapping[str, Any]:
        asset_id = _identifier(record.get("asset_id"), "asset_id")
        if asset_id not in by_id:
            raise EvaluationInputError("candidate/truth references an unknown asset_id")
        asset = by_id[asset_id]
        if formal and (asset.get("split") != "test" or asset.get("source_type") == "synthetic"):
            raise EvaluationInputError("formal rankings require real test assets")
        return asset

    def stratum(record: Mapping[str, Any], field: str) -> str:
        value = referenced_asset(record).get(field) or "unknown"
        return _identifier(value, field)

    def metrics(candidates: list[dict[str, Any]], truth: list[dict[str, Any]]) -> dict[str, Any]:
        result = precision_at_k(candidates, k)
        retrieved = [row["truth_id"] for row in candidates[:k] if _relevance(row) == "positive"]
        result["recall_at_k"] = recall_from_truth(retrieved, [row["truth_id"] for row in truth],
                                                complete_truth=complete_truth)
        result["truth_positive_count"] = len({row["truth_id"] for row in truth})
        result["complete_truth"] = complete_truth
        return result

    for query in query_rows:
        query_id = _identifier(query.get("query_id"), "query_id")
        if query_id in seen_queries:
            raise EvaluationInputError("query_id must be unique")
        seen_queries.add(query_id)
        candidates = _records(query.get("candidates", []), "candidates")
        truth = _records(query.get("truth", []), "truth")
        truth_assets: dict[str, str] = {}
        for row in truth:
            referenced_asset(row)
            truth_id = _identifier(row.get("truth_id"), "truth_id")
            if truth_id in truth_assets and truth_assets[truth_id] != row["asset_id"]:
                raise EvaluationInputError("truth_id must have one canonical asset for stratification")
            truth_assets[truth_id] = row["asset_id"]
        seen_positive: set[str] = set()
        for row in candidates:
            referenced_asset(row)
            if _relevance(row) == "positive":
                truth_id = _identifier(row.get("truth_id"), "positive candidate.truth_id")
                if truth_id in seen_positive:
                    raise EvaluationInputError("deduplicate positive occurrences before scoring")
                seen_positive.add(truth_id)
                if truth_id in truth_assets and truth_assets[truth_id] != row["asset_id"]:
                    raise EvaluationInputError("matched candidates must use their canonical truth asset")
                if complete_truth and truth_id not in truth_assets:
                    raise EvaluationInputError("positive match absent from declared complete truth")
        selected = candidates[:k]
        strata: dict[str, Any] = {}
        for field in STRATA:
            values = {stratum(row, field) for row in selected + truth}
            strata[field] = {
                value: metrics([row for row in selected if stratum(row, field) == value],
                               [row for row in truth if stratum(row, field) == value])
                for value in sorted(values)
            }
        results.append({"query_id": query_id, "overall": metrics(candidates, truth),
                        "strata": strata})
    return {"formal": formal, "split_report": split_report, "queries": results,
            "strata_policy": "filter_global_top_k", "complete_truth": complete_truth}


def coco17_track_features(frames: Iterable[Mapping[str, Any]], *,
                          identity_confirmed: bool = False, min_score: float = 0.5,
                          max_gap_ms: int = 250) -> dict[str, Any]:
    """Image-coordinate features from one manually confirmed COCO17 track.

    Frames contain track_id, source_ms and 17 [x,y,score] keypoints in consistent
    source-image pixels. Hip midpoint is a landmark proxy, NOT centre of mass.
    COCO17 hips 11/12 and ankles 15/16 must be visible. Velocities use source
    timestamps in seconds; missing/low-score frames or long gaps are not bridged.
    Results never assert airborne state, court direction, or a footwork class.
    """
    if type(identity_confirmed) is not bool:
        raise EvaluationInputError("identity_confirmed must be a boolean")
    if type(min_score) not in (float, int) or not math.isfinite(min_score) or not 0 <= min_score <= 1:
        raise EvaluationInputError("min_score must be a finite number in [0,1]")
    if type(max_gap_ms) is not int or max_gap_ms < 1:
        raise EvaluationInputError("max_gap_ms must be a positive integer")
    rows = _records(frames, "frames")
    if not identity_confirmed:
        return {"status": "unknown", "unknown_reasons": ["track_identity_not_confirmed"], "frames": []}
    output: list[dict[str, Any]] = []
    reasons: set[str] = set()
    track_id = None
    previous_time = None
    previous_valid = None
    for frame in rows:
        current_track = _identifier(frame.get("track_id"), "track_id")
        if track_id is not None and current_track != track_id:
            raise EvaluationInputError("frames must belong to one manually confirmed track")
        track_id = current_track
        source_ms = frame.get("source_ms")
        if type(source_ms) is not int or source_ms < 0 or (previous_time is not None and source_ms <= previous_time):
            raise EvaluationInputError("source_ms must be non-negative and strictly increasing")
        previous_time = source_ms
        keypoints = frame.get("keypoints")
        if not isinstance(keypoints, (list, tuple)) or len(keypoints) != 17:
            raise EvaluationInputError("keypoints must contain 17 COCO [x,y,score] triples")
        for point in keypoints:
            if not isinstance(point, (list, tuple)) or len(point) != 3:
                raise EvaluationInputError("each keypoint must be an [x,y,score] triple")
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in point):
                raise EvaluationInputError("keypoints must contain finite numbers")
            if not 0 <= point[2] <= 1:
                raise EvaluationInputError("keypoint score must be in [0,1]")
        frame_reasons = []
        if any(keypoints[index][2] < min_score for index in (15, 16)):
            frame_reasons.append("low_ankle_visibility")
        if any(keypoints[index][2] < min_score for index in (11, 12)):
            frame_reasons.append("low_hip_visibility")
        if frame_reasons:
            reasons.update(frame_reasons)
            output.append({"source_ms": source_ms, "status": "unknown", "features": None,
                           "unknown_reasons": frame_reasons})
            previous_valid = None
            continue
        hip = [(keypoints[11][axis] + keypoints[12][axis]) / 2 for axis in (0, 1)]
        left = [keypoints[15][axis] - hip[axis] for axis in (0, 1)]
        right = [keypoints[16][axis] - hip[axis] for axis in (0, 1)]
        features = {"hip_midpoint_px": hip, "left_ankle_relative_hip_px": left,
                    "right_ankle_relative_hip_px": right,
                    "ankle_separation_px": math.dist(keypoints[15][:2], keypoints[16][:2]),
                    "hip_velocity_px_s": None, "left_relative_velocity_px_s": None,
                    "right_relative_velocity_px_s": None}
        if previous_valid is not None:
            dt_ms = source_ms - previous_valid["source_ms"]
            if dt_ms <= max_gap_ms:
                for source, target in (("hip_midpoint_px", "hip_velocity_px_s"),
                                       ("left_ankle_relative_hip_px", "left_relative_velocity_px_s"),
                                       ("right_ankle_relative_hip_px", "right_relative_velocity_px_s")):
                    features[target] = [(features[source][axis] - previous_valid["features"][source][axis])
                                        * 1000 / dt_ms for axis in (0, 1)]
            else:
                reasons.add("timestamp_gap")
                frame_reasons.append("timestamp_gap")
        record = {"source_ms": source_ms, "status": "unknown" if frame_reasons else "observed",
                  "features": features, "unknown_reasons": frame_reasons}
        output.append(record)
        previous_valid = record
    if len(rows) < 2:
        reasons.add("insufficient_frames")
    if not any(record.get("features") and record["features"]["hip_velocity_px_s"] is not None for record in output):
        reasons.add("insufficient_contiguous_visible_frames")
    return {"status": "unknown" if reasons else "observed", "track_id": track_id,
            "coordinate_space": "source_image_pixels", "unknown_reasons": sorted(reasons),
            "frames": output}
