"""Label Studio REST and loss-aware video annotation interchange.

No Label Studio dependency is imported into the web process. Frame maps are
explicit per-media/proxy records, never inferred by dividing a frame by FPS.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from xml.sax.saxutils import escape


class LabelStudioError(ValueError):
    pass


def annotation_timestamp(value: str | None) -> datetime | None:
    """Only timezone-qualified LS timestamps can establish snapshot ordering."""
    if value is None:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise LabelStudioError('Label Studio updated_at must be an ISO8601 timestamp with timezone') from None


def annotation_hash(annotation: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(annotation, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


LABEL_DEFINITIONS = {
    "rally": ("rally", {}),
    "shot": ("shot", {}),
    "stroke.unknown": ("stroke", {"stroke": "unknown", "hand_technique": "unknown"}),
    "stroke.net_shot": ("stroke", {"stroke": "net_shot", "hand_technique": "unknown"}),
    "stroke.smash": ("stroke", {"stroke": "smash", "hand_technique": "unknown"}),
    "hand.net_zhan_cuo": ("stroke", {"hand_technique": "net_zhan_cuo"}),
    "hand.net_shou_cuo": ("stroke", {"hand_technique": "net_shou_cuo"}),
    "movement.unknown": ("movement", {"footwork": "unknown"}),
    "footwork.backward_small_hop_start": ("movement", {"footwork": "backward_small_hop_start"}),
}


def label_config(framerate: float = 30.0) -> str:
    """A project must contain only videos/proxies with this verified display FPS."""
    if not math.isfinite(framerate) or framerate <= 0:
        raise LabelStudioError("framerate must be positive")
    labels = "".join(f'<Label value="{escape(name)}"/>' for name in LABEL_DEFINITIONS)
    return (f'<View><Header value="标注可见事实；细手法看不清时保留 unknown"/>'
            f'<Video name="video" value="$video" framerate="{framerate}"/>'
            f'<TimelineLabels name="events" toName="video">{labels}</TimelineLabels>'
            '<VideoRectangle name="box" toName="video"/>'
            '<Labels name="players" toName="video"><Label value="player_unconfirmed"/></Labels>'
            '</View>')


@dataclass(frozen=True)
class FrameMap:
    mapping_id: str
    frames: tuple[dict[str, Any], ...]
    source_duration_ms: int

    def __post_init__(self):
        if not self.mapping_id or not self.frames or self.source_duration_ms <= 0:
            raise LabelStudioError("PTS mapping_id, frames and duration are required")
        previous_frame, previous_start, previous_end = -1, -1, -1
        for frame in self.frames:
            for key in ("ls_frame", "source_start_ms", "source_end_ms"):
                if type(frame.get(key)) is not int:
                    raise LabelStudioError(f"PTS {key} must be an integer")
            index, start, end = (frame[k] for k in ("ls_frame", "source_start_ms", "source_end_ms"))
            if index < 0 or index <= previous_frame or not 0 <= start < end <= self.source_duration_ms:
                raise LabelStudioError("invalid or unordered PTS frame mapping")
            # A CFR proxy may duplicate a source image. Its identical source
            # interval is valid, but arbitrary overlapping intervals are not.
            if previous_end > start and (start, end) != (previous_start, previous_end):
                raise LabelStudioError("partially overlapping source frame intervals are not supported")
            previous_frame, previous_start, previous_end = index, start, end

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> "FrameMap":
        return cls(str(body["mapping_id"]), tuple(copy.deepcopy(body["frames"])), body["source_duration_ms"])

    def as_dict(self) -> dict[str, Any]:
        return {"mapping_id": self.mapping_id, "source_duration_ms": self.source_duration_ms,
                "frames": copy.deepcopy(list(self.frames))}

    def frame(self, index: int) -> dict[str, Any]:
        if type(index) is not int:
            raise LabelStudioError("Label Studio frame must be an integer")
        indices = [f["ls_frame"] for f in self.frames]
        position = bisect_left(indices, index)
        if position == len(indices) or indices[position] != index:
            raise LabelStudioError(f"frame {index} is missing from the explicit PTS map")
        return self.frames[position]

    def interval(self, start_frame: int, end_frame: int) -> tuple[int, int]:
        """TimelineLabels endpoints are inclusive frame indices, including a single frame."""
        if start_frame > end_frame:
            raise LabelStudioError("reversed frame range")
        start, end = self.frame(start_frame), self.frame(end_frame)
        selected = [f for f in self.frames if start_frame <= f["ls_frame"] <= end_frame]
        if len(selected) != end_frame - start_frame + 1:
            raise LabelStudioError("range crosses missing display frames")
        if any(a["source_end_ms"] < b["source_start_ms"] for a, b in zip(selected, selected[1:])):
            raise LabelStudioError("range crosses an unmapped source interval")
        return start["source_start_ms"], end["source_end_ms"]

    def range_for(self, start_ms: int, end_ms: int) -> dict[str, int]:
        if not 0 <= start_ms < end_ms <= self.source_duration_ms:
            raise LabelStudioError("event interval is outside the source")
        starts = [f["source_start_ms"] for f in self.frames]
        ends = [f["source_end_ms"] for f in self.frames]
        first, last = bisect_right(ends, start_ms), bisect_left(starts, end_ms) - 1
        if first >= len(self.frames) or first > last:
            raise LabelStudioError("event interval is outside mapped media")
        if starts[first] > start_ms or ends[last] < end_ms:
            raise LabelStudioError("event interval crosses unmapped source media")
        result = {"start": self.frames[first]["ls_frame"], "end": self.frames[last]["ls_frame"]}
        self.interval(result["start"], result["end"])
        return result


def _event_label(event: dict[str, Any]) -> str:
    kind, labels = event["kind"], event.get("labels", {})
    for name, (candidate_kind, candidate_labels) in reversed(list(LABEL_DEFINITIONS.items())):
        if kind == candidate_kind and candidate_labels and all(labels.get(k) == v for k, v in candidate_labels.items()):
            return name
    return kind if kind in ("rally", "shot") else f"{kind}.unknown"


def build_task(asset: dict[str, Any], media_url: str, frame_map: FrameMap,
               events: list[dict[str, Any]] | None = None,
               context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build importable LS task; seed events remain recoverable after an unchanged roundtrip."""
    if asset["duration_ms"] != frame_map.source_duration_ms:
        raise LabelStudioError("frame map duration differs from asset")
    if urlsplit(media_url).scheme not in ("http", "https"):
        raise LabelStudioError("media_url must be an HTTP URL")
    seeds, results = {}, []
    for event in events or []:
        if event["asset_id"] != asset["asset_id"]:
            raise LabelStudioError("event belongs to another asset")
        region = "btv" + hashlib.sha256(event["event_id"].encode()).hexdigest()[:20]
        label = _event_label(event)
        ranges = [frame_map.range_for(event["start_ms"], event["end_ms"])]
        results.append({"id": region, "from_name": "events", "to_name": "video", "type": "timelinelabels",
                        "value": {"ranges": ranges, "timelinelabels": [label]}})
        seeds[region] = {"event": copy.deepcopy(event), "ranges": ranges, "labels": [label]}
    result = {"data": {"video": media_url, "asset_id": asset["asset_id"], "match_id": asset["match_id"],
                       "btv": {"schema_version": "1.0", "frame_map": frame_map.as_dict(),
                               "seed_events": seeds, "context": context or {}}}}
    if results:
        result["annotations"] = [{"result": results}]
    return result


def _raw_reference(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise LabelStudioError("raw export reference must be a safe relative path")
    return value


def import_annotation(task: dict[str, Any], annotation: dict[str, Any], *,
                      tool_version: str, raw_export_relative_path: str,
                      frame_map: FrameMap | None = None) -> dict[str, Any]:
    """Convert one chosen LS annotation; callers persist raw JSON and apply revision CAS.

    Return events (unreviewed), expected_revisions, tracks and warnings. Reimporting
    the identical annotation is idempotent by event ID; callers should compare
    provenance/raw hash before creating another revision. Tracks are evidence,
    never fabricated movement or identity labels.
    """
    if annotation.get("was_cancelled"):
        raise LabelStudioError("cancelled annotation cannot be imported")
    if not tool_version or annotation.get("id") is None or task.get("id") is None:
        raise LabelStudioError("task ID, annotation ID and tool version are required")
    raw_ref = _raw_reference(raw_export_relative_path)
    data = task["data"]
    btv = data.get("btv", {})
    frame_map = frame_map or FrameMap.from_dict(btv["frame_map"])
    seeds, context = btv.get("seed_events", {}), btv.get("context", {})
    result = {"schema_version": "1.0", "events": [], "expected_revisions": {}, "tracks": [], "warnings": []}
    seen = set()
    raw_hash = annotation_hash(annotation)
    base_provenance = {"source": "import", "tool": "label-studio", "tool_version": tool_version,
                       "task_id": task["id"], "annotation_id": annotation["id"],
                       "annotation_updated_at": annotation.get("updated_at"),
                       "annotator": annotation.get("completed_by"), "mapping_id": frame_map.mapping_id,
                       "raw_export_relative_path": raw_ref, "annotation_sha256": raw_hash}
    for region in annotation.get("result", []):
        if region.get("to_name") != "video":
            result["warnings"].append(f"ignored result for {region.get('to_name')}")
            continue
        region_id = region.get("id")
        region_key = (region_id, region.get("type"))
        if not region_id or region_key in seen:
            raise LabelStudioError("missing or duplicate region ID")
        seen.add(region_key)
        value = region["value"]
        provenance = {**base_provenance, "region_id": region_id}
        if region["type"] == "videorectangle":
            sequence = []
            for keyframe in value.get("sequence", []):
                mapped = frame_map.frame(keyframe["frame"])
                sequence.append({**copy.deepcopy(keyframe), "source_start_ms": mapped["source_start_ms"],
                                 "source_end_ms": mapped["source_end_ms"]})
            result["tracks"].append({"track_id": f"ls:{task['id']}:{annotation['id']}:{region_id}",
                                      "asset_id": data["asset_id"], "player_id": None,
                                      "identity_status": "unconfirmed", "labels": value.get("labels", []),
                                      "keyframes": sequence, "provenance": provenance})
            continue
        if region["type"] != "timelinelabels":
            result["warnings"].append(f"unsupported result type: {region['type']}")
            continue
        selected = value.get("timelinelabels", [])
        if len(selected) != 1 or selected[0] not in LABEL_DEFINITIONS:
            raise LabelStudioError("timeline region must have one known badmintonTV label")
        kind, labels = LABEL_DEFINITIONS[selected[0]]
        ranges = value.get("ranges", [])
        if not ranges:
            raise LabelStudioError("timeline region has no ranges")
        for range_index, interval in enumerate(ranges):
            start_ms, end_ms = frame_map.interval(interval["start"], interval["end"])
            seed = seeds.get(region_id) if len(ranges) == 1 else None
            original = copy.deepcopy(seed["event"]) if seed else {}
            unchanged_range = seed and seed["ranges"] == ranges
            if unchanged_range:
                start_ms, end_ms = original["start_ms"], original["end_ms"]
            event_id = original.get("event_id") or "ls-" + hashlib.sha256(
                f"{task['id']}:{annotation['id']}:{region_id}:{range_index}".encode()).hexdigest()[:24]
            expected = original.get("revision")
            event_labels = copy.deepcopy(original.get("labels", {})) if seed and seed["labels"] == selected else copy.deepcopy(labels)
            contact = original.get("contact_ms")
            if contact is not None and not start_ms <= contact < end_ms:
                contact = None
            event = {"schema_version": "1.0", "event_id": event_id, "asset_id": data["asset_id"],
                     "match_id": data["match_id"], "rally_id": original.get("rally_id", context.get("rally_id")),
                     "shot_id": original.get("shot_id", context.get("shot_id")),
                     "player_id": original.get("player_id", context.get("player_id")),
                     "track_id": original.get("track_id"), "kind": kind,
                     "start_ms": start_ms, "end_ms": end_ms, "contact_ms": contact,
                     "labels": event_labels, "visibility": "insufficient", "confidence": None,
                     "review_status": "unreviewed", "revision": (expected or 0) + 1,
                     "provenance": {**provenance, "previous_revision": expected},
                     "evidence": [{"type": "source_interval", "asset_id": data["asset_id"],
                                   "start_ms": start_ms, "end_ms": end_ms},
                                  {"type": "label_studio_region", "region_id": region_id,
                                   "frame_range": interval, "mapping_id": frame_map.mapping_id}],
                     "unknown_reason": "Imported annotation requires platform visibility, identity and label review"}
            result["events"].append(event)
            result["expected_revisions"][event_id] = expected
    missing_seeds = [seed["event"]["event_id"] for region_id, seed in seeds.items()
                     if (region_id, "timelinelabels") not in seen]
    if missing_seeds:
        result["warnings"].append("Seed regions removed in Label Studio; platform events were not deleted: "
                                  + ", ".join(missing_seeds))
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LabelStudioError("Label Studio redirects are disabled")


class LabelStudioClient:
    """Small local REST client; credentials are read from environment, never returned."""
    def __init__(self, base_url: str = "http://127.0.0.1:18081", token_env: str = "BTV_LABEL_STUDIO_TOKEN",
                 timeout: float = 20.0, max_response_bytes: int = 32_000_000):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise LabelStudioError("Label Studio must use a loopback URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise LabelStudioError("invalid Label Studio base URL")
        self.base_url, self.token_env = base_url.rstrip("/"), token_env
        self.timeout, self.max_response_bytes = timeout, max_response_bytes
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, method: str, path: str, body: Any = None, auth: bool = True) -> Any:
        headers = {"Accept": "application/json"}
        if auth:
            token = os.environ.get(self.token_env)
            if not token:
                raise LabelStudioError(f"Label Studio token environment variable {self.token_env} is not set")
            headers["Authorization"] = f"Token {token}"
        payload = None if body is None else json.dumps(body).encode()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            request = Request(self.base_url + path, data=payload, headers=headers, method=method)
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
            if len(raw) > self.max_response_bytes:
                raise LabelStudioError("Label Studio response exceeds configured byte limit")
            return json.loads(raw) if raw else None
        except HTTPError as exc:
            # Do not echo response bodies: they may include submitted sensitive data.
            raise LabelStudioError(f"Label Studio HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise LabelStudioError("Label Studio unavailable or invalid response") from None

    def health(self) -> dict[str, Any]:
        try:
            self._request("GET", "/health", auth=False)
            return {"status": "ready", "base_url": self.base_url,
                    "token_present": bool(os.environ.get(self.token_env))}
        except LabelStudioError as exc:
            return {"status": "unavailable", "base_url": self.base_url, "reason": str(exc)}

    def create_project(self, title: str, framerate: float = 30.0) -> dict[str, Any]:
        return self._request("POST", "/api/projects/", {"title": title, "label_config": label_config(framerate)})

    @staticmethod
    def _id(value: int) -> int:
        if type(value) is not int or value <= 0:
            raise LabelStudioError("Label Studio ID must be a positive integer")
        return value

    def import_tasks(self, project_id: int, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", f"/api/projects/{self._id(project_id)}/import?return_task_ids=true", tasks)

    def get_task(self, task_id: int) -> dict[str, Any]:
        return self._request("GET", f"/api/tasks/{self._id(task_id)}/")

    def create_annotation(self, task_id: int, results: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", f"/api/tasks/{self._id(task_id)}/annotations/", {"result": results})

    def update_annotation(self, annotation_id: int, results: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("PATCH", f"/api/annotations/{self._id(annotation_id)}/", {"result": results})

    def export_project(self, project_id: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/projects/{self._id(project_id)}/export?exportType=JSON")
