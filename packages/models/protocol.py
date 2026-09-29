"""Version 1 JSON/JSONL boundary; importing this module never imports ML code.

Protocol tests exercise transport and validation only, not inference quality.
Adapter ``execute`` receives a validated request, resolved storage root and
output directory, and a ``ProgressWriter`` callable. ModelBlocked messages must
be safe for display and must not contain credentials or private endpoint data.
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import threading
from typing import Any, TextIO
import uuid


SCHEMA_VERSION = "1.0"
OPERATIONS = frozenset({"analyze", "query_parse", "pose", "video_embedding", "movement_classification", "tracking", "stroke_classification"})
REQUEST_FIELDS = frozenset({"schema_version", "job_id", "attempt_id", "operation", "assets", "parameters", "output_dir"})
ASSET_FIELDS = frozenset({
    "schema_version", "asset_id", "relative_path", "sha256", "size_bytes",
    "duration_ms", "width", "height", "fps_num", "fps_den", "time_base", "title",
    "match_id", "source_type", "source_url", "source_page", "acquired_at",
    "camera_type", "discipline", "players", "rights", "split", "probe", "provenance",
})
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_RESERVED_WINDOWS = frozenset({"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)})


class InvalidRequest(ValueError):
    """An invalid v1 request; messages identify fields, not their contents."""

    def __init__(self, message: str, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.code = code


class ModelBlocked(RuntimeError):
    """A known missing prerequisite, distinct from an execution failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def storage_root() -> Path:
    """Resolve only the administrator's configured root, never a request value."""
    default = r"D:\video" if os.name == "nt" else "/mnt/d/video"
    return Path(os.environ.get("BTV_STORAGE_ROOT", default)).expanduser().resolve()


def _string(value: Any, field: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise InvalidRequest(f"{field} must be a {'non-empty ' if not allow_empty else ''}string")
    if any(ord(character) < 32 for character in value):
        raise InvalidRequest(f"{field} must not contain control characters")


def _integer(value: Any, field: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise InvalidRequest(f"{field} must be an integer >= {minimum}")


def _choice(value: Any, field: str, choices: set[str] | frozenset[str]) -> None:
    if not isinstance(value, str) or value not in choices:
        raise InvalidRequest(f"{field} is not a supported value")


def _timestamp(value: Any, field: str) -> None:
    _string(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidRequest(f"{field} must be an ISO8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise InvalidRequest(f"{field} must include a timezone")


def resolve_relative(root: str | Path, relative: str, owner: str | None = None) -> Path:
    """Resolve a portable POSIX path and reject traversal and escaping symlinks.

    ``owner='models'`` additionally requires a child of the physical models
    directory; a symlink into another owner's directory is rejected as well.
    This check assumes storage directories cannot be concurrently replaced by
    an untrusted process between validation and use.
    """
    _string(relative, "relative_path")
    if "\\" in relative or any(character in relative for character in ':*?"<>|') or relative.startswith("/"):
        raise InvalidRequest("relative_path must be a relative POSIX path", "invalid_path")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} or part.endswith((" ", "."))
           or part.split(".")[0].upper() in _RESERVED_WINDOWS for part in parts):
        raise InvalidRequest("relative_path contains an unsafe path component", "invalid_path")
    if owner is not None and (parts[0] != owner or len(parts) < 2):
        raise InvalidRequest("output_dir must be a child of models/", "invalid_path")
    base = Path(root).resolve()
    try:
        target = base.joinpath(*parts).resolve()
        contained = target.relative_to(base)
    except (ValueError, OSError, RuntimeError) as exc:
        raise InvalidRequest("relative_path resolves outside its storage root", "invalid_path") from exc
    if owner is not None and (not contained.parts or contained.parts[0] != owner or len(contained.parts) < 2):
        raise InvalidRequest("output_dir resolves outside its owner directory", "invalid_path")
    return target


def _validate_asset(asset: Any, root: Path, index: int) -> None:
    field = f"assets[{index}]"
    if not isinstance(asset, dict) or not ASSET_FIELDS.issubset(asset):
        raise InvalidRequest(f"{field} must contain the complete v1 Asset fields")
    if asset["schema_version"] != SCHEMA_VERSION:
        raise InvalidRequest(f"{field}.schema_version must be 1.0")
    for key in ("asset_id", "match_id"):
        _string(asset[key], f"{field}.{key}")
    _string(asset["title"], f"{field}.title", allow_empty=True)
    resolve_relative(root, asset["relative_path"])
    if not isinstance(asset["sha256"], str) or not _SHA256.fullmatch(asset["sha256"]):
        raise InvalidRequest(f"{field}.sha256 must be a 64-digit SHA256 hex digest")
    for key in ("size_bytes", "duration_ms", "width", "height"):
        _integer(asset[key], f"{field}.{key}")
    if (asset["fps_num"] is None) != (asset["fps_den"] is None):
        raise InvalidRequest(f"{field}.fps_num and fps_den must both be present or both be null")
    if asset["fps_num"] is not None:
        _integer(asset["fps_num"], f"{field}.fps_num")
        _integer(asset["fps_den"], f"{field}.fps_den", 1)
    if asset["time_base"] is not None:
        _string(asset["time_base"], f"{field}.time_base")
        if not re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", asset["time_base"]):
            raise InvalidRequest(f"{field}.time_base must be a positive rational string")
    _choice(asset["source_type"], f"{field}.source_type", {"broadcast", "personal", "dataset", "synthetic"})
    _choice(asset["camera_type"], f"{field}.camera_type", {"rear", "side", "overhead", "handheld", "mixed", "unknown"})
    _choice(asset["discipline"], f"{field}.discipline", {"singles", "doubles", "unknown"})
    _choice(asset["split"], f"{field}.split", {"unassigned", "train", "validation", "test"})
    if "usage_scope" in asset:
        _choice(asset["usage_scope"], f"{field}.usage_scope", {"general", "training_only"})
    for key in ("source_url", "source_page"):
        if asset[key] is not None:
            _string(asset[key], f"{field}.{key}")
    if asset["acquired_at"] is not None:
        _timestamp(asset["acquired_at"], f"{field}.acquired_at")
    for key in ("probe", "provenance"):
        if not isinstance(asset[key], dict):
            raise InvalidRequest(f"{field}.{key} must be an object")
    if "usage_scope" in asset["provenance"]:
        _choice(asset["provenance"]["usage_scope"], f"{field}.provenance.usage_scope", {"general", "training_only"})
    if not isinstance(asset["players"], list):
        raise InvalidRequest(f"{field}.players must be an array")
    for player in asset["players"]:
        if not isinstance(player, dict) or not {"player_id", "display_name", "identity_status"}.issubset(player):
            raise InvalidRequest(f"{field}.players entries must contain player identity fields")
        for key in ("player_id", "display_name", "identity_status"):
            _string(player[key], f"{field}.players.{key}")
    rights = asset["rights"]
    if not isinstance(rights, dict) or not {"status", "license_url", "evidence", "allowed_uses"}.issubset(rights):
        raise InvalidRequest(f"{field}.rights must contain status, license_url, evidence and allowed_uses")
    _choice(rights["status"], f"{field}.rights.status", {"unknown", "research_only", "permitted", "owned"})
    if rights["license_url"] is not None:
        _string(rights["license_url"], f"{field}.rights.license_url")
    if not isinstance(rights["evidence"], (str, list, dict)):
        raise InvalidRequest(f"{field}.rights.evidence must be text, an array or an object")
    if not isinstance(rights["allowed_uses"], list) or any(not isinstance(item, str) for item in rights["allowed_uses"]):
        raise InvalidRequest(f"{field}.rights.allowed_uses must be an array of strings")


def validate_request(request: Any, root: str | Path | None = None) -> dict[str, Any]:
    """Validate the v1 envelope and Assets without loading any model dependencies."""
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise InvalidRequest("request must contain exactly the seven v1 request fields")
    if request["schema_version"] != SCHEMA_VERSION:
        raise InvalidRequest("schema_version must be 1.0")
    _string(request["job_id"], "job_id")
    _string(request["attempt_id"], "attempt_id")
    _choice(request["operation"], "operation", OPERATIONS)
    if not isinstance(request["parameters"], dict):
        raise InvalidRequest("parameters must be an object")
    _string(request["parameters"].get("model_id"), "parameters.model_id")
    if not isinstance(request["assets"], list):
        raise InvalidRequest("assets must be an array")
    if request["operation"] != "query_parse" and not request["assets"]:
        raise InvalidRequest("video operations require at least one complete Asset")
    base = Path(root).resolve() if root is not None else storage_root()
    resolve_relative(base, request["output_dir"], owner="models")
    seen_assets = set()
    for index, asset in enumerate(request["assets"]):
        _validate_asset(asset, base, index)
        if asset["asset_id"] in seen_assets:
            raise InvalidRequest("assets must have unique asset_id values")
        seen_assets.add(asset["asset_id"])
    try:
        json.dumps(request, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidRequest("request must contain finite JSON-compatible values") from exc
    return request


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    """Publish complete UTF-8 JSON atomically without replacing an existing file.

    A same-directory hard link is the exclusive publication operation on both
    NTFS and Linux. Filesystems without hard-link support fail safely. The
    destination is intentionally caller-selected; asset/output paths use
    ``resolve_relative`` separately.
    """
    target = Path(path)
    encoded = (json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".btv-models-", suffix=".tmp", dir=target.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return target


def make_artifact(root: str | Path, path: str | Path, kind: str, producer: Any) -> dict[str, Any]:
    """Hash an already-complete models file and produce the seven artifact fields."""
    base = Path(root).resolve()
    given = Path(path)
    target = given.resolve() if given.is_absolute() else resolve_relative(base, given.as_posix(), owner="models")
    try:
        relative = target.relative_to(base).as_posix()
    except ValueError as exc:
        raise InvalidRequest("artifact resolves outside storage root", "invalid_path") from exc
    target = resolve_relative(base, relative, owner="models")
    _string(kind, "artifact.kind")
    if not isinstance(producer, (str, dict)) or not producer:
        raise InvalidRequest("artifact.producer must be a non-empty string or object")
    digest = hashlib.sha256()
    size = 0
    with target.open("rb") as stream:
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or size != after.st_size:
        raise OSError("artifact changed while being hashed")
    return {
        "artifact_id": f"artifact-{uuid.uuid4().hex}",
        "kind": kind,
        "relative_path": relative,
        "sha256": digest.hexdigest(),
        "size_bytes": size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": producer,
    }


class ProgressWriter:
    """A callback with monotonic sequence numbers and the exact JSONL fields."""

    def __init__(self, job_id: str | None, stream: TextIO | None = None) -> None:
        self.job_id = job_id
        self.stream = stream if stream is not None else sys.stdout
        self.seq = 0

    def __call__(self, stage: str, current: int | float | None = None,
                 total: int | float | None = None, unit: str | None = None,
                 message: str = "", event: str = "progress") -> None:
        _choice(event, "progress.event", {"progress", "artifact", "warning", "error"})
        _string(stage, "progress.stage")
        _string(message, "progress.message", allow_empty=True)
        for field, value in (("current", current), ("total", total)):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise InvalidRequest(f"progress.{field} must be a finite non-negative number or null")
        if current is not None and total is not None and current > total:
            raise InvalidRequest("progress.current must not exceed total")
        if unit is not None:
            _string(unit, "progress.unit")
        self.seq += 1
        record = {"schema_version": SCHEMA_VERSION, "job_id": self.job_id,
                  "seq": self.seq, "event": event, "stage": stage,
                  "current": current, "total": total, "unit": unit, "message": message}
        self.stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()


def _reject_constant(value: str) -> Any:
    raise InvalidRequest("request contains a non-finite JSON number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidRequest("request contains a duplicate JSON key")
        result[key] = value
    return result


@contextlib.contextmanager
def _cancellation_signals():
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.getsignal(signal.SIGTERM)
        def cancel(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, cancel)
    try:
        yield
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def run_request(request_path: str | Path, result_path: str | Path) -> int:
    """Run one request: success=0, failed=1, blocked=2, cancelled=130."""
    job_id = None
    attempt_id = None
    progress = ProgressWriter(job_id)
    status, exit_code, artifacts, events, error = "failed", 1, [], [], None
    try:
        with Path(request_path).open("r", encoding="utf-8-sig") as stream:
            request = json.load(stream, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        if isinstance(request, dict) and isinstance(request.get("job_id"), str) and request["job_id"].strip():
            job_id = request["job_id"]
            progress.job_id = job_id
        if isinstance(request, dict) and isinstance(request.get("attempt_id"), str) and request["attempt_id"].strip():
            attempt_id = request["attempt_id"]
        root = storage_root()
        validate_request(request, root)
        result_target = Path(result_path)
        if result_target.exists() or result_target.is_symlink():
            raise FileExistsError("result destination already exists")
        output = resolve_relative(root, request["output_dir"], owner="models")
        output.mkdir(parents=True, exist_ok=True)
        output = resolve_relative(root, request["output_dir"], owner="models")
        progress("starting", message="Validated model request; execution is starting")
        from .inference import execute
        with _cancellation_signals(), contextlib.redirect_stdout(sys.stderr):
            payload = execute(request, root, output, progress)
        if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list) or not isinstance(payload.get("events"), list):
            raise ValueError("adapter returned an invalid payload")
        artifacts, events = payload["artifacts"], payload["events"]
        status, exit_code = "succeeded", 0
    except ModelBlocked as exc:
        status, exit_code = "blocked", 2
        error = {"code": exc.code, "message": exc.message}
    except KeyboardInterrupt:
        status, exit_code = "cancelled", 130
        error = {"code": "cancelled", "message": "Model execution was cancelled"}
    except InvalidRequest as exc:
        error = {"code": exc.code, "message": str(exc)}
    except (json.JSONDecodeError, UnicodeDecodeError):
        error = {"code": "invalid_json", "message": "Request must contain valid UTF-8 JSON"}
    except FileExistsError:
        error = {"code": "output_exists", "message": "A requested output already exists; no existing file was replaced"}
    except FileNotFoundError:
        error = {"code": "file_not_found", "message": "A required request, source or model file was not found"}
    except Exception:
        # Adapter exceptions can include headers, credentials or query text.
        error = {"code": "execution_failed", "message": "Model execution failed; inspect the adapter environment and inputs"}
    result = {"schema_version": SCHEMA_VERSION, "job_id": job_id, "attempt_id": attempt_id, "status": status,
              "artifacts": artifacts, "events": events, "error": error}
    try:
        atomic_write_json(result_path, result)
    except Exception:
        progress("result_write_failed", event="error", message="Could not exclusively publish result; existing files are preserved")
        return 1
    if status == "succeeded":
        progress("completed", current=1, total=1, unit="job", message="Model result was published")
    else:
        progress(status, event="error", message=error["message"])
    return exit_code


def main(argv: list[str] | None = None) -> int:
    # A Windows subprocess can inherit a legacy code page. The wire contract
    # stays UTF-8 regardless of the caller's console or locale.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")
    parser = argparse.ArgumentParser(
        description="Model v1 JSON executor. BTV_STORAGE_ROOT selects the controlled storage root.",
        epilog="Asset paths are relative POSIX paths inside the storage root; output_dir must be inside models/. Absolute paths, traversal and escaping symlinks are rejected. Existing results and artifacts are never replaced.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("catalog", help="Print the registered model catalog without loading ML dependencies")
    run = subparsers.add_parser("run", help="Execute a v1 request and publish a result with exclusive creation")
    run.add_argument("--request", required=True, type=Path, help="UTF-8 v1 request JSON file")
    run.add_argument("--result", required=True, type=Path, help="Caller-selected result JSON file; must not exist")
    args = parser.parse_args(argv)
    if args.command == "catalog":
        from .registry import catalog
        print(json.dumps(catalog(), ensure_ascii=False, allow_nan=False))
        return 0
    return run_request(args.request, args.result)
