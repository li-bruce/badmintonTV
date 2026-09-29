"""Independent fixed-operation worker. No ML runtime is imported by this process."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import queue as streams
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from .queue import Queue
from .storage import CapacityLedger, resolve_owner_path, resolve_relative_path


class JobCancelled(Exception):
    pass


class JobBlocked(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _sha256(path, context=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if context is not None:
                context.check()
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _kill_tree(process, windows_job=None):
    if windows_job is not None:
        windows_job.close()
    elif os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


class WorkerContext:
    def __init__(self, queue, job, worker_id, storage_root, lease_seconds):
        self.queue, self.job, self.worker_id = queue, job, worker_id
        self.storage_root = Path(storage_root).resolve()
        self.lease_seconds = lease_seconds
        self.stopped = threading.Event()
        self.lost_lease = threading.Event()
        self.secrets = [value for key, value in os.environ.items() if any(word in key.upper() for word in ("SECRET", "TOKEN", "API_KEY", "PASSWORD")) and len(value) >= 4]
        self.log_budget_bytes = 8_000_000
        self.log_bytes_written = 0
        self.log_omission_reported = False
        self.gpu_coordinator = None
        self.gpu_lease = None
        self.registered_command = None
        self.bridge_done_path = None
        self.compute_started = False
        self.compute_stopped = True
        self.thread = threading.Thread(target=self._keepalive, daemon=True)

    def _keepalive(self):
        while not self.stopped.wait(max(0.02, min(5, self.lease_seconds / 3))):
            try:
                if not self.queue.heartbeat(self.job["job_id"], self.worker_id, self.lease_seconds, expected_attempt=self.job["attempt"]):
                    self.lost_lease.set()
                    return
                if self.gpu_lease and not self.gpu_coordinator.heartbeat(self.gpu_lease["lease_id"], self.worker_id, self.lease_seconds):
                    self.lost_lease.set()
                    return
            except Exception:
                self.lost_lease.set()
                return

    def check(self):
        if self.lost_lease.is_set():
            raise JobCancelled("worker lease was lost")
        row = self.queue.get(self.job["job_id"])
        if row is None or row["cancel_requested"] or row["status"] != "running" or row["worker_id"] != self.worker_id or row["attempt"] != self.job["attempt"]:
            raise JobCancelled("cancel requested or worker no longer owns job")

    def redact(self, message):
        message = str(message)
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        return message[:8000]

    def log(self, event, **data):
        self.check()
        if "message" in data:
            data["message"] = self.redact(data["message"])
        if self.log_omission_reported:
            return None

        def estimated_size(log_event, fields):
            # Reserve the complete JSON envelope with conservative seq/time widths.
            body = {"event": log_event, "stage": None, "current": None, "total": None,
                    "unit": None, "message": "", **fields, "schema_version": "1.0",
                    "job_id": self.job["job_id"], "seq": 9223372036854775807,
                    "created_at": 999999999999.9999}
            return len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"))

        omission = {"stage": "log_budget", "message": "本次日志达到字节预算，后续省略；任务继续运行。"}
        omission_size = estimated_size("warning", omission)
        if self.log_bytes_written + estimated_size(event, data) + omission_size > self.log_budget_bytes:
            self.log_omission_reported = True
            # Tiny test budgets may not even fit the warning. Production always reserves it.
            if self.log_bytes_written + omission_size > self.log_budget_bytes:
                return None
            event, data = "warning", omission
        result = self.queue.append_log(self.job["job_id"], event, **data)
        self.log_bytes_written += len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        return result

    def execute(self, argv, stage, parse_progress=False, timeout=3600, capture_limit=8_000_000, extra_env=None):
        self.check()
        env = dict(os.environ)
        env["BTV_STORAGE_ROOT"] = str(self.storage_root)
        if extra_env:
            env.update(extra_env)
        if not shutil.which(argv[0]):
            raise JobBlocked("not_installed", f"找不到 {stage} 可执行文件")
        windows_job = None
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP, "stdin": subprocess.PIPE} if os.name == "nt" else {"start_new_session": True, "stdin": subprocess.DEVNULL}
        launch_argv = argv
        if os.name == "nt":
            from .windows_job import WindowsJob
            windows_job = WindowsJob()
            launch_argv = [sys.executable, "-m", "packages.runtime.launcher"]
        try:
            process = subprocess.Popen(launch_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env, shell=False, **kwargs)
            if windows_job:
                try:
                    windows_job.assign(process)
                    process.stdin.write(json.dumps(argv) + "\n")
                    process.stdin.close()
                except BaseException:
                    _kill_tree(process, windows_job)
                    raise
            self.compute_started = True
            self.compute_stopped = False
        except FileNotFoundError as exc:
            if windows_job:
                windows_job.close()
            raise JobBlocked("not_installed", f"找不到 {stage} 可执行文件") from exc
        output_queue = streams.Queue(maxsize=100)
        def read_lines(pipe, name):
            try:
                while True:
                    line = pipe.readline(65537)
                    if not line:
                        break
                    output_queue.put((name, line))
            finally:
                pipe.close()
                output_queue.put((name, None))
        for name in ("stdout", "stderr"):
            threading.Thread(target=read_lines, args=(getattr(process, name), name), daemon=True).start()
        start = time.monotonic()
        finished = set()
        stdout, stderr = [], []
        captured = 0
        last_seq = 0
        logged_lines = 0
        try:
            while len(finished) < 2 or process.poll() is None:
                self.check()
                if process.poll() is not None and windows_job:
                    windows_job.close()  # A CLI cannot leave detached descendants holding its pipes.
                if time.monotonic() - start > timeout:
                    raise TimeoutError(f"{stage} exceeded {timeout} seconds")
                try:
                    name, line = output_queue.get(timeout=0.1)
                except streams.Empty:
                    continue
                if line is None:
                    finished.add(name)
                    continue
                if len(line) > 65536:
                    raise ValueError("subprocess output line exceeds 64 KiB")
                if name == "stdout" and parse_progress:
                    try:
                        item = json.loads(line)
                        if not isinstance(item, dict) or item.get("schema_version") != "1.0" or item.get("job_id") != self.job["job_id"]:
                            raise ValueError("invalid progress identity")
                        if item.get("event") not in {"progress", "artifact", "warning", "error"}:
                            raise ValueError("invalid progress event")
                        from packages.contracts import ProgressEvent
                        item = ProgressEvent.model_validate(item).model_dump(mode="json")
                        seq = item.get("seq")
                        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= last_seq:
                            raise ValueError("progress seq is not increasing")
                        last_seq = seq
                        for field in ("current", "total"):
                            if item.get(field) is not None and (not isinstance(item[field], (int, float)) or not math.isfinite(item[field]) or item[field] < 0):
                                raise ValueError("progress counters must be nonnegative finite values")
                        event = item["event"]
                        data = {key: item.get(key) for key in ("stage", "current", "total", "unit", "message")}
                        data["source_seq"] = seq
                        self.log(event, **data)
                        logged_lines += 1
                    except (ValueError, TypeError):
                        if logged_lines < 10000:
                            self.log("warning", stage=stage, message="忽略无效的 CLI JSONL 进度行")
                            logged_lines += 1
                elif name == "stdout":
                    captured += len(line.encode("utf-8"))
                    if captured > capture_limit:
                        raise ValueError("subprocess response exceeds bounded capture limit")
                    stdout.append(line)
                else:
                    if sum(map(len, stderr)) < 16000:
                        stderr.append(self.redact(line))
                    if logged_lines < 10000:
                        self.log("warning", stage=stage, message=line.rstrip())
                        logged_lines += 1
            return process.wait(), "".join(stdout), "".join(stderr)
        except BaseException:
            _kill_tree(process, windows_job)
            raise
        finally:
            if windows_job:
                windows_job.close()
            self.compute_stopped = process.poll() is not None


def _binary(env_name, fallback):
    value = os.environ.get(env_name) or shutil.which(fallback)
    if not value:
        raise JobBlocked("not_installed", f"{fallback} 尚未安装；管理员可配置 {env_name}")
    return value


def render_backend():
    """Trusted process configuration; never read from the request parameters."""
    backend=os.environ.get('BTV_RENDER_BACKEND','cpu')
    if backend not in {'cpu','nvenc','auto'}:
        raise JobBlocked('invalid_configuration','BTV_RENDER_BACKEND must be cpu, nvenc or auto')
    return backend


def _artifact(path, context, kind):
    return {"artifact_id": "artifact-" + uuid.uuid4().hex, "kind": kind,
            "relative_path": Path(path).relative_to(context.storage_root).as_posix(),
            "sha256": _sha256(path, context), "size_bytes": Path(path).stat().st_size,
            "created_at": datetime.now(timezone.utc).isoformat(), "producer": "platform.worker"}


def verify_manifest(context, exchange_dir):
    """Validate declared source bytes without decoding, copying, or importing media."""
    from packages.contracts import AssetManifest

    payload = context.job["payload"]
    assets = payload.get("assets")
    if not isinstance(assets, list) or not 1 <= len(assets) <= 1000:
        raise ValueError("verify_manifest requires between 1 and 1000 assets")
    if not isinstance(payload.get("library_id"), str) or not payload["library_id"].strip():
        raise ValueError("verify_manifest requires library_id")
    if len(json.dumps(assets, ensure_ascii=False).encode("utf-8")) > 16_000_000:
        raise ValueError("manifest metadata exceeds 16 MB limit")
    assets = AssetManifest.model_validate({"schema_version": "1.0", "assets": assets}).model_dump(mode="json")["assets"]
    sources = []
    for asset in assets:
        context.check()
        path = resolve_relative_path(context.storage_root, asset["relative_path"], must_exist=True)
        if not path.is_file():
            raise ValueError(f"asset source is not a regular file: {asset['asset_id']}")
        stat = path.stat()
        if stat.st_size != asset["size_bytes"]:
            raise ValueError(f"asset size_bytes mismatch: {asset['asset_id']}; declared={asset['size_bytes']}, actual={stat.st_size}")
        sources.append((asset, path, stat))
    total = sum(stat.st_size for _, _, stat in sources)
    verified_bytes = 0
    context.log("progress", stage="verify_manifest", current=0, total=total, unit="bytes", message=f"开始校验 {len(assets)} 个原文件")
    def identity(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    for index, (asset, path, before) in enumerate(sources, 1):
        context.check()
        digest = hashlib.sha256()
        read = 0
        last_log = time.monotonic()
        with path.open("rb") as handle:
            if identity(os.fstat(handle.fileno())) != identity(before):
                raise ValueError(f"asset changed before verification: {asset['asset_id']}")
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                context.check()
                read += len(chunk)
                if read > asset["size_bytes"]:
                    raise ValueError(f"asset grew during verification: {asset['asset_id']}")
                digest.update(chunk)
                if time.monotonic() - last_log >= 0.5:
                    context.log("progress", stage="verify_manifest", current=verified_bytes + read, total=total, unit="bytes",
                                message=f"读取 {index}/{len(assets)}: {asset['asset_id']}")
                    last_log = time.monotonic()
            if identity(os.fstat(handle.fileno())) != identity(before):
                raise ValueError(f"asset changed during verification: {asset['asset_id']}")
        if identity(path.stat()) != identity(before) or read != asset["size_bytes"]:
            raise ValueError(f"asset changed during verification: {asset['asset_id']}")
        if digest.hexdigest() != asset["sha256"]:
            raise ValueError(f"asset sha256 mismatch: {asset['asset_id']}")
        verified_bytes += read
        context.log("progress", stage="verify_manifest", current=verified_bytes, total=total, unit="bytes",
                    message=f"已核验 {index}/{len(assets)}: {asset['asset_id']}")
    return {"schema_version": "1.0", "job_id": context.job["job_id"], "attempt_id": f"attempt-{context.job['attempt']}",
            "status": "succeeded", "assets": assets, "artifacts": [], "events": [], "error": None}


def probe(context, exchange_dir):
    payload = context.job["payload"]
    source = resolve_relative_path(context.storage_root, payload["relative_path"], must_exist=True)
    if not source.is_file():
        raise ValueError("source must be a regular file")
    ffprobe, ffmpeg = _binary("BTV_FFPROBE", "ffprobe"), _binary("BTV_FFMPEG", "ffmpeg")
    before = source.stat()
    digest = hashlib.sha256()
    read = 0
    context.log("progress", stage="hash", current=0, total=before.st_size, unit="bytes", message="读取原片 SHA-256")
    last_log = time.monotonic()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            context.check()
            digest.update(chunk)
            read += len(chunk)
            if time.monotonic() - last_log >= 0.5:
                context.log("progress", stage="hash", current=read, total=before.st_size, unit="bytes")
                last_log = time.monotonic()
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("source changed while hashing; retry after writer completes")
    context.log("progress", stage="hash", current=read, total=before.st_size, unit="bytes", message="SHA-256 已完成")
    context.log("progress", stage="probe", message="ffprobe 正在读取媒体流信息")
    code, output, error = context.execute([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)], "ffprobe", timeout=300)
    if code:
        raise ValueError(f"ffprobe failed with exit {code}: {error}")
    media = json.loads(output)
    stream = next((item for item in media.get("streams", []) if item.get("codec_type") == "video"), None)
    if not stream:
        raise ValueError("no video stream found")
    duration = stream.get("duration") or media.get("format", {}).get("duration")
    if duration is None or not math.isfinite(float(duration)) or float(duration) <= 0:
        raise ValueError("video duration is missing or invalid")
    duration_ms = math.ceil(float(duration) * 1000)
    try:
        rate = Fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    except (ValueError, ZeroDivisionError):
        rate = Fraction(0, 1)
    thumbnail = exchange_dir / "thumbnail.jpg"
    context.log("progress", stage="thumbnail", message="CPU 提取预览缩略图")
    code, _, error = context.execute([ffmpeg, "-nostdin", "-v", "error", "-ss", str(min(1.0, float(duration) / 2)), "-i", str(source), "-frames:v", "1", "-vf", "scale=480:-2", "-threads", "1", "-n", str(thumbnail)], "ffmpeg", timeout=300)
    if code or not thumbnail.is_file():
        raise ValueError(f"thumbnail extraction failed with exit {code}: {error}")
    metadata = payload.get("asset_metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("asset_metadata must be an object")
    asset = {
        "title": source.name, "match_id": "unassigned-" + digest.hexdigest()[:16],
        "source_type": "personal", "source_url": None, "source_page": None,
        "acquired_at": datetime.now(timezone.utc).isoformat(), "camera_type": "unknown",
        "discipline": "unknown", "players": [], "rights": {"status": "unknown", "license_url": None, "evidence": "用户本地引用；权利待确认", "allowed_uses": []},
        "split": "unassigned", "provenance": {"source": "local_reference", "match_grouping": "unassigned; generated identifier does not establish a full match"}, **metadata,
        "schema_version": "1.0", "asset_id": metadata.get("asset_id") or "asset-" + digest.hexdigest()[:24],
        "relative_path": payload["relative_path"], "sha256": digest.hexdigest(), "size_bytes": before.st_size,
        "duration_ms": duration_ms, "width": int(stream.get("width", 0)), "height": int(stream.get("height", 0)),
        "fps_num": rate.numerator, "fps_den": rate.denominator, "time_base": stream.get("time_base") or "1/1000",
        "probe": {**(metadata.get("probe", {}) if metadata.get("sha256") == digest.hexdigest() else {}),
                  "tool": "ffprobe", "format": media.get("format", {}), "streams": media["streams"],
                  "thumbnail_relative_path": thumbnail.relative_to(context.storage_root).as_posix()},
    }
    from packages.contracts import Asset
    asset = Asset.model_validate(asset).model_dump(mode="json")
    # The platform validates this object again before inserting its business record.
    return {"schema_version": "1.0", "job_id": context.job["job_id"], "attempt_id": f"attempt-{context.job['attempt']}", "status": "succeeded", "asset": asset,
            "artifacts": [_artifact(thumbnail, context, "thumbnail")], "events": [], "error": None}


def registered_command(operation, payload):
    encoded = os.environ.get("BTV_RENDER_COMMAND_JSON") if operation == "render" else None
    if operation == "model":
        if not isinstance(payload.get("model_id"), str) or not payload["model_id"].strip():
            raise ValueError("model payload requires a nonempty model_id snapshot")
        if not os.environ.get("BTV_MODEL_COMMANDS_JSON"):
            raise JobBlocked("not_installed", "model_id 尚未在管理员 BTV_MODEL_COMMANDS_JSON 精确登记")
        commands = json.loads(os.environ["BTV_MODEL_COMMANDS_JSON"])
        if not isinstance(commands, dict):
            raise JobBlocked("invalid_configuration", "管理员模型命令表必须是 JSON 对象")
        command = commands.get(payload.get("model_id"))
        if command is None:
            raise JobBlocked("not_installed", "该 model_id 尚未由管理员登记 CLI")
    elif encoded:
        command = json.loads(encoded)
    elif operation == "render":
        try:
            available = importlib.util.find_spec("packages.render") is not None
        except ModuleNotFoundError:
            available = False
        if not available:
            raise JobBlocked("not_installed", "render 模块尚未安装且未登记 BTV_RENDER_COMMAND_JSON")
        command = [sys.executable, "-m", "packages.render"]
    else:
        raise JobBlocked("not_installed", "model CLI 尚未由管理员登记")
    if not isinstance(command, list) or not command or not all(isinstance(arg, str) and arg and "\x00" not in arg for arg in command):
        raise JobBlocked("invalid_configuration", "管理员 CLI 配置必须是非空 JSON argv 数组")
    return command


def adapter(context, exchange_dir):
    from packages.contracts import JobRequest, JobResult
    job, payload = context.job, context.job["payload"]
    command = context.registered_command or registered_command(job["operation"], payload)
    if "packages.runtime.wsl_bridge" in command:
        context.bridge_done_path = exchange_dir / "bridge.done.json"
    adapter_operation = job["operation"]
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    parameters = dict(parameters)
    if job["operation"] == "model":
        adapter_operation = payload.get("adapter_operation")
        if not isinstance(adapter_operation, str) or not adapter_operation.strip():
            raise ValueError("model payload requires its validated capability as adapter_operation")
        for field in ("model_id", "model_version"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"model payload requires a nonempty {field} snapshot")
            parameters[field] = value
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("assets must be an Asset array")
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("each assets entry must be an Asset object")
        resolve_relative_path(context.storage_root, asset["relative_path"], must_exist=True)
    owner = "render" if job["operation"] == "render" else "models"
    relative_output = f"{owner}/jobs/{job['job_id']}/attempt-{job['attempt']}"
    resolve_owner_path(context.storage_root, relative_output, owner)
    attempt_id = f"attempt-{job['attempt']}"
    request = {"schema_version": "1.0", "job_id": job["job_id"], "attempt_id": attempt_id, "operation": adapter_operation, "assets": assets,
               "parameters": parameters, "output_dir": relative_output}
    request = JobRequest.model_validate(request).model_dump(mode="json")
    if len(json.dumps(request, ensure_ascii=False).encode("utf-8")) > 16_000_000:
        raise ValueError("CLI request exceeds 16 MB exchange-file limit")
    request_file, result_file = exchange_dir / "request.json", exchange_dir / "result.json"
    _atomic_json(request_file, request)
    context.log("progress", stage="adapter", message=f"启动已登记的 {job['operation']} CLI")
    trusted_env = None
    if job['operation']=='render':
        trusted_env={'BTV_RENDER_BACKEND':render_backend(),'BTV_RUNTIME_DB':context.queue.db_path,
                     'BTV_GPU_LEASE_ID':context.gpu_lease['lease_id'] if context.gpu_lease else ''}
    code, _, error = context.execute([*command, "run", "--request", str(request_file), "--result", str(result_file)], job["operation"], parse_progress=True, extra_env=trusted_env)
    if not result_file.is_file() or result_file.stat().st_size > 16_000_000:
        raise ValueError(f"CLI result file missing or exceeds 16 MB (exit={code}): {error}")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("schema_version") != "1.0" or result.get("job_id") != job["job_id"] or result.get("attempt_id") != attempt_id:
        raise ValueError("CLI result schema_version/job_id/attempt_id mismatch")
    result = JobResult.model_validate(result).model_dump(mode="json")
    if result.get("status") not in {"succeeded", "failed", "blocked", "cancelled"}:
        raise ValueError("CLI result has an invalid status")
    expected_exit = {"succeeded": 0, "failed": 1, "blocked": 2, "cancelled": 130}[result["status"]]
    if code != expected_exit:
        raise ValueError(f"CLI reported {result['status']} but exited {code}; expected {expected_exit}")
    if result["status"] == "blocked" and not (result.get("error") or {}).get("code"):
        raise ValueError("blocked CLI result must include error.code")
    if not isinstance(result.get("artifacts"), list) or not isinstance(result.get("events"), list):
        raise ValueError("CLI result must contain artifacts and events arrays")
    for artifact in result["artifacts"]:
        required = {"artifact_id", "kind", "relative_path", "sha256", "size_bytes", "created_at", "producer"}
        if not isinstance(artifact, dict) or not required.issubset(artifact):
            raise ValueError("CLI Artifact is incomplete")
        path = resolve_owner_path(context.storage_root, artifact["relative_path"], owner, must_exist=True)
        output = resolve_owner_path(context.storage_root, relative_output, owner)
        if not path.is_relative_to(output) or not path.is_file():
            raise ValueError("CLI Artifact is outside its controlled job output")
        if path.stat().st_size != artifact["size_bytes"] or _sha256(path, context) != artifact["sha256"]:
            raise ValueError("CLI Artifact size or SHA-256 mismatch")
    result["exit_code"] = code
    return result


def run_once(queue, storage_root, worker_id=None, lease_seconds=30):
    worker_id = worker_id or "worker-" + uuid.uuid4().hex
    queue.recover_expired()
    job = queue.claim(worker_id, lease_seconds)
    if job is None:
        return None
    context = WorkerContext(queue, job, worker_id, storage_root, lease_seconds)
    context.thread.start()
    ledger = None
    reservation = None
    status, result, error = "failed", None, {"code": "WORKER_INTERRUPTED", "message": "worker interrupted before completion"}
    try:
        ledger = CapacityLedger(queue.db_path, storage_root)
        context.check()
        if job["operation"] not in {"probe", "verify_manifest", "render", "model"}:
            raise JobBlocked("unsupported_operation", "该 operation 没有固定处理器")
        gpu_required = job["payload"].get("gpu_required", False)
        if not isinstance(gpu_required, bool):
            raise ValueError("gpu_required must be a boolean derived by the platform from trusted model requirements")
        if job["operation"] == "model":
            context.registered_command = registered_command(job["operation"], job["payload"])
            gpu_required = gpu_required or "packages.runtime.wsl_bridge" in context.registered_command
        if job['operation']=='render':
            backend=render_backend()
            if job['payload'].get('render_backend',backend)!=backend:
                raise JobBlocked('RENDER_CONFIG_CHANGED','管理员渲染后端已变化，请按当前配置重新创建任务')
            if backend in {'nvenc','auto'}:
                if job['payload'].get('model_id')!='render-nvenc':
                    raise JobBlocked('GPU_RESOURCE_MISMATCH','GPU渲染须由可信管理员登记render-nvenc资源身份')
                gpu_required=True
        if gpu_required:
            from .gpu import GPUCoordinator, GPUUnavailable
            coordinator = GPUCoordinator(queue.db_path)
            try:
                lease = coordinator.claim(job["payload"].get("model_id"), job["job_id"], job["attempt"], worker_id, lease_seconds)
            except GPUUnavailable as exc:
                raise JobBlocked(exc.code, exc.message) from exc
            context.gpu_coordinator, context.gpu_lease = coordinator, lease
        if job["operation"] == "render":
            context.registered_command = registered_command(job["operation"], job["payload"])
        # Covers protocol atomic-write overlap, SQLite/WAL, bounded logs and one thumbnail.
        # External modules own their media-output reservations.
        reservation = ledger.reserve("platform", 128_000_000, job["job_id"])
        exchange_dir = resolve_owner_path(storage_root, f"platform/jobs/{job['job_id']}/attempt-{job['attempt']}", "platform")
        exchange_dir.mkdir(parents=True, exist_ok=False)
        handler = {"probe": probe, "verify_manifest": verify_manifest}.get(job["operation"], adapter)
        result = handler(context, exchange_dir)
        context.check()
        status, error = result["status"], result.get("error")
    except JobCancelled as exc:
        status, result, error = "cancelled", None, {"code": "cancelled", "message": context.redact(exc)}
    except JobBlocked as exc:
        status, result, error = "blocked", None, {"code": exc.code, "message": context.redact(exc)}
    except Exception as exc:
        status, result, error = "failed", None, {"code": type(exc).__name__, "message": context.redact(exc)}
    finally:
        # Keep the job running and both heartbeats alive until the external
        # compute tree is proven stopped. Terminal state is the last write.
        cleanup_error = None
        try:
            compute_stopped = not context.compute_started or context.compute_stopped
            if context.bridge_done_path and context.compute_started:
                from .wsl_bridge import wait_for_bridge_done
                compute_stopped = wait_for_bridge_done(context.bridge_done_path, job["job_id"], f"attempt-{job['attempt']}", timeout=15)
            if not compute_stopped:
                cleanup_error = "未确认本任务计算进程停止；保留GPU租约，需管理员核验"
            elif context.gpu_lease and not context.gpu_coordinator.release(context.gpu_lease["lease_id"], worker_id, compute_stopped=True):
                cleanup_error = "计算已停止，但GPU租约不再由当前worker有效持有；需管理员核验"
        except Exception as exc:
            cleanup_error = "计算停止核验失败：" + context.redact(exc)
        try:
            if cleanup_error:
                status, result, error = "failed", None, {"code": "WORKER_INTERRUPTED", "message": cleanup_error}
                if context.gpu_lease:
                    context.gpu_coordinator.mark_orphaned(context.gpu_lease["lease_id"], worker_id, cleanup_error)
                queue.append_log(job["job_id"], "error", stage="compute_cleanup", message=cleanup_error)
            try:
                queue.finish(job["job_id"], worker_id, status, result=result, error=error, expected_attempt=job["attempt"])
            except RuntimeError:
                pass  # A newer lease/recovery owns durable state; never overwrite it.
        finally:
            context.stopped.set()
            context.thread.join(timeout=6)
            if reservation:
                ledger.release(reservation)
    return queue.get(job["job_id"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--storage-root", required=True)
    parser.add_argument("--worker-id", default="worker-" + uuid.uuid4().hex)
    parser.add_argument("--lease-seconds", type=float, default=30)
    parser.add_argument("--poll-seconds", type=float, default=1)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.lease_seconds <= 0 or args.poll_seconds <= 0:
        parser.error("lease and poll seconds must be positive")
    queue = Queue(args.db)
    while True:
        result = run_once(queue, args.storage_root, args.worker_id, args.lease_seconds)
        if args.once:
            return 0
        if result is None:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
