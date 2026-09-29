"""Administrator-configured Windows→Ubuntu model bridge with a detached watchdog.

Only standard-library code runs here. SQLite is never opened in WSL.
The Linux entry points also work when this file is invoked directly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

MAX_JSON_BYTES = 16_000_000
WINDOWS_STORAGE = PureWindowsPath("D:/video")
LINUX_STORAGE = Path("/mnt/d/video")
HEARTBEAT_REPLACE_RETRY_SECONDS = 0.7
HEARTBEAT_SHARING_ERRORS = frozenset({32, 33})


def _io_diagnostic(stage, exc, attempts):
    """Never copy exception text/filename or heartbeat identity into diagnostics."""
    return {"stage": stage, "type": type(exc).__name__,
            "errno": getattr(exc, "errno", None), "winerror": getattr(exc, "winerror", None),
            "attempts": attempts}


def _emit_io_diagnostic(diagnostic):
    print(json.dumps(diagnostic, ensure_ascii=True), file=sys.stderr, flush=True)


class HeartbeatWriteError(RuntimeError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__(json.dumps(diagnostic, ensure_ascii=True))


def _target_has_delete_sharing_conflict(path):
    """Distinguish Windows rename error 5 from a confirmed delete-share conflict.

    This opens an existing file for DELETE access and immediately closes the
    handle; it never deletes or writes it. ACL denial/read-only errors do not
    establish a sharing conflict and must fail closed.
    """
    if os.name != "nt":
        return False
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path), 0x00010000, 0x1 | 0x2 | 0x4, None, 3, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        return ctypes.get_last_error() in HEARTBEAT_SHARING_ERRORS
    kernel.CloseHandle(handle)
    return False


def _heartbeat_replace_retryable(exc, path):
    winerror = getattr(exc, "winerror", None)
    return winerror in HEARTBEAT_SHARING_ERRORS or (winerror == 5 and _target_has_delete_sharing_conflict(path))


def windows_to_wsl(value, *, storage_only=False):
    """Translate an absolute local Windows path without shell or wslpath parsing."""
    raw = str(value)
    if not raw or any(ord(char) < 32 for char in raw):
        raise ValueError("invalid Windows path")
    pieces = raw.replace("\\", "/").split("/")
    if any(part in {".", ".."} for part in pieces):
        raise ValueError("dot path segments are forbidden")
    path = PureWindowsPath(raw)
    if not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive):
        raise ValueError("an absolute local Windows drive path is required")
    for part in path.parts[1:]:
        if any(char in part for char in ':*?"<>|') or part.endswith((".", " ")):
            raise ValueError("unsafe Windows path component")
        if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
            raise ValueError("reserved Windows path component")
    parts = list(path.parts[1:])
    if storage_only:
        if path.drive.lower() != "d:" or not parts or parts[0].lower() != "video":
            raise ValueError("bridge exchange paths must be under D:/video")
        parts[0] = "video"
    return PurePosixPath("/mnt", path.drive[0].lower(), *parts).as_posix()


def _atomic_json(path, body, *, replace=True, heartbeat=False):
    path = Path(path)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    stage, attempts, failed = "open_temp", 1, False
    deadline = time.monotonic() + HEARTBEAT_REPLACE_RETRY_SECONDS
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            stage = "write_temp"
            json.dump(body, handle, ensure_ascii=False, allow_nan=False)
            stage = "flush_temp"
            handle.flush()
            stage = "fsync_temp"
            os.fsync(handle.fileno())
        if replace:
            stage = "replace"
            delay, previous = 0.01, None
            while True:
                try:
                    os.replace(temporary, path)
                    if previous is not None:
                        _emit_io_diagnostic(_io_diagnostic("heartbeat.replace.recovered", previous, attempts))
                    break
                except OSError as exc:
                    remaining = deadline - time.monotonic()
                    # Windows may report rename sharing conflicts as error 5;
                    # retry it only after the nonmutating DELETE-access probe
                    # positively returns a sharing violation (32/33).
                    if not heartbeat or remaining <= 0 or not _heartbeat_replace_retryable(exc, path):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise
                    previous = exc
                    _emit_io_diagnostic(_io_diagnostic("heartbeat.replace.retry", exc, attempts))
                    time.sleep(min(delay, remaining))
                    delay = min(delay * 2, 0.1)
                    attempts += 1
        else:
            stage = "link"
            os.link(temporary, path)
    except OSError as exc:
        failed = True
        if heartbeat:
            raise HeartbeatWriteError(_io_diagnostic("heartbeat." + stage + ".failed", exc, attempts)) from None
        raise
    except BaseException:
        failed = True
        raise
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            if heartbeat:
                diagnostic = _io_diagnostic("heartbeat.cleanup_temp.failed", exc, attempts)
                if failed:
                    _emit_io_diagnostic(diagnostic)  # Preserve the original I/O failure.
                else:
                    raise HeartbeatWriteError(diagnostic) from None
            elif not failed:
                raise


def _read_json(path, max_bytes=MAX_JSON_BYTES):
    if Path(path).stat().st_size > max_bytes:
        raise ValueError("bridge JSON file exceeds limit")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def exchange_paths(request_path, result_path):
    request = PureWindowsPath(str(request_path))
    result = PureWindowsPath(str(result_path))
    linux_request = windows_to_wsl(request_path, storage_only=True)
    linux_result = windows_to_wsl(result_path, storage_only=True)
    if request.parent != result.parent or request.name != "request.json" or result.name != "result.json":
        raise ValueError("request.json and result.json must share one attempt directory")
    relative = request.relative_to(WINDOWS_STORAGE).parts
    if len(relative) != 5 or relative[:2] != ("platform", "jobs"):
        raise ValueError("bridge requires platform/jobs/job_id/attempt_id exchange files")
    if not all(re.fullmatch(r"[A-Za-z0-9_-]+", item) for item in relative[2:4]):
        raise ValueError("unsafe job/attempt directory")
    if os.name == "nt":
        native_root = Path("D:/video").resolve(strict=True)
        for path in (Path(request_path).resolve(strict=True), Path(result_path).resolve()):
            if not path.is_relative_to(native_root / "platform" / "jobs"):
                raise ValueError("bridge exchange path escapes through a link")
    return linux_request, linux_result, relative[2], relative[3]


def validate_env_prefix(value):
    if not isinstance(value, str) or any(ord(char) < 32 for char in value) or "\\" in value:
        raise ValueError("invalid environment prefix")
    path = PurePosixPath(value)
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")[1:]):
        raise ValueError("env-prefix must be a normalized absolute POSIX path")
    if not path.is_relative_to(PurePosixPath("/mnt/d/video/runtime/models")) or path == PurePosixPath("/mnt/d/video/runtime/models"):
        raise ValueError("env-prefix must be under /mnt/d/video/runtime/models/")
    return path.as_posix()


def build_wsl_command(args, linux_request, linux_result, token):
    if args.distribution != "Ubuntu":
        raise ValueError("only the authorized Ubuntu distribution is supported")
    prefix = validate_env_prefix(args.env_prefix)
    offline_env = {
        "BTV_STORAGE_ROOT": "/mnt/d/video", "BTV_MODELS_ENV": prefix,
        "CONDA_PKGS_DIRS": "/mnt/d/video/runtime/shared/pkgs", "CONDA_ENVS_PATH": "/mnt/d/video/runtime/models",
        "HF_HOME": "/mnt/d/video/models/cache/huggingface", "TORCH_HOME": "/mnt/d/video/models/cache/torch",
        "TMPDIR": "/mnt/d/video/runtime/models/tmp", "PIP_CACHE_DIR": "/mnt/d/video/runtime/models/pip-cache",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false", "PYTHONUNBUFFERED": "1",
    }
    return ["wsl.exe", "--distribution", "Ubuntu", "--exec", "/usr/bin/env",
            *[key + "=" + value for key, value in offline_env.items()], prefix + "/bin/python",
            windows_to_wsl(Path(__file__).resolve()), "_linux_entry",
            "--env-prefix", prefix, "--repo", windows_to_wsl(args.repo),
            "--request", linux_request, "--result", linux_result,
            "--token", token, "--heartbeat-timeout", str(args.heartbeat_timeout)]


def _base_record(request, token):
    return {"schema_version": "1.0", "job_id": request["job_id"], "attempt_id": request["attempt_id"], "token": token}


def wait_for_bridge_done(path, job_id, attempt_id, timeout=15):
    """The worker releases its GPU only after matching Linux stop evidence."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            done = _read_json(path, 8192)
            if done.get("job_id") == job_id and done.get("attempt_id") == attempt_id and done.get("compute_stopped") is True:
                return True
        except (OSError, ValueError, AttributeError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def run_windows(args):
    linux_request, linux_result, job_id, attempt_id = exchange_paths(args.request, args.result)
    request = _read_json(args.request)
    if request.get("job_id") != job_id or request.get("attempt_id") != attempt_id or request.get("schema_version") != "1.0":
        raise ValueError("request identity does not match controlled exchange directory")
    directory = Path(args.request).parent
    done = directory / "bridge.done.json"
    if done.exists() or Path(args.result).exists() or (directory / "bridge-heartbeat.json").exists():
        raise FileExistsError("bridge attempt already has a result or done record")
    heartbeat = directory / "bridge-heartbeat.json"
    token = uuid.uuid4().hex
    record = _base_record(request, token)
    command = build_wsl_command(args, linux_request, linux_result, token)
    stop = threading.Event()
    failure = []
    def beat():
        tick = 0
        while not stop.is_set():
            try:
                _atomic_json(heartbeat, {**record, "tick": tick, "updated_at": time.time(), "cancel_requested": False}, heartbeat=True)
            except BaseException as exc:
                failure.append(exc if isinstance(exc, HeartbeatWriteError) else
                               HeartbeatWriteError(_io_diagnostic("heartbeat.publish.failed", exc, 1)))
                return
            tick += 1
            stop.wait(0.5)
    process, thread = None, None
    try:
        _atomic_json(heartbeat, {**record, "tick": -1, "updated_at": time.time(), "cancel_requested": False}, heartbeat=True)
        thread = threading.Thread(target=beat, daemon=True)
        thread.start()
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, shell=False)
        while process.poll() is None:
            if failure:
                raise failure[0] from None
            time.sleep(0.1)
        if failure:
            raise failure[0] from None
        return process.returncode
    except BaseException:
        try:
            _atomic_json(directory / "bridge-cancel.json", {**record, "cancel_requested": True})
        except OSError as exc:
            _emit_io_diagnostic(_io_diagnostic("cancel.publish.failed", exc, 1))
        if process is not None:
            try:
                process.wait(timeout=args.heartbeat_timeout + 5)
            except subprocess.TimeoutExpired:
                process.kill()  # Linux guardian remains responsible for its own process group.
        raise
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=2)
        if process is None:
            try:
                _atomic_json(done, {**record, "compute_stopped": True, "reason": "launcher_not_started", "finished_at": time.time()}, replace=False)
            except OSError as exc:
                _emit_io_diagnostic(_io_diagnostic("launcher_done.publish.failed", exc, 1))


def _group_alive(pgid):
    """Only this model's process group; zombies no longer perform computation."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
            if int(fields[2]) == pgid and fields[0] not in {"Z", "X"}:
                return True
        except (FileNotFoundError, ProcessLookupError):
            continue
    return False


def stop_model_group(process, grace_seconds=3):
    pgid = process.pid  # Created with start_new_session=True; never a global process pattern.
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        process.poll()
        if not _group_alive(pgid):
            return True
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return False
    return not _group_alive(pgid)


def _validate_linux_paths(args):
    request_path, result_path = Path(args.request), Path(args.result)
    root = LINUX_STORAGE.resolve(strict=True)
    if not request_path.resolve(strict=True).is_relative_to(root / "platform" / "jobs"):
        raise ValueError("Linux request escapes platform/jobs")
    if result_path.parent.resolve(strict=True) != request_path.parent.resolve(strict=True) or result_path.name != "result.json":
        raise ValueError("Linux result is outside its request attempt")
    if result_path.is_symlink():
        raise ValueError("Linux result must not be a symlink")
    request = _read_json(request_path)
    relative = request_path.relative_to(root).parts
    if len(relative) != 5 or relative[2] != request.get("job_id") or relative[3] != request.get("attempt_id"):
        raise ValueError("Linux exchange identity mismatch")
    return request


def _heartbeat_state(path, record):
    body = _read_json(path, 4096)
    if any(body.get(key) != record[key] for key in ("job_id", "attempt_id", "token")):
        raise ValueError("heartbeat identity mismatch")
    if body.get("cancel_requested"):
        return "cancel", None
    if not isinstance(body.get("tick"), int) or not isinstance(body.get("updated_at"), (int, float)):
        raise ValueError("invalid heartbeat")
    return "alive", body


def supervise_model(args):
    """Detached Linux guardian; stdout/stderr preserve the model's JSONL wire output."""
    request = _validate_linux_paths(args)
    directory = Path(args.request).parent
    record = _base_record(request, args.token)
    heartbeat = directory / "bridge-heartbeat.json"
    cancel_path = directory / "bridge-cancel.json"
    done = directory / "bridge.done.json"
    process = None
    reason = "completed"
    returncode = 1
    compute_stopped = True
    stop = threading.Event()
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[sig] = signal.signal(sig, lambda signum, frame: stop.set())
    try:
        kind, initial = _heartbeat_state(heartbeat, record)
        if kind == "cancel" or time.time() - initial["updated_at"] > args.heartbeat_timeout:
            reason, returncode = "heartbeat_lost_before_start", 130
        else:
            env = dict(os.environ)
            env.update({"BTV_STORAGE_ROOT": str(LINUX_STORAGE), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
                        "PYTHONNOUSERSITE": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
            prefix = validate_env_prefix(args.env_prefix)
            process = subprocess.Popen([prefix + "/bin/python", "-m", "packages.models", "run", "--request", args.request, "--result", args.result],
                                       cwd=args.repo, env=env, stdin=subprocess.DEVNULL, start_new_session=True, shell=False)
            compute_stopped = False
            _atomic_json(directory / "bridge.started.json", {**record, "guardian_pid": os.getpid(), "model_pid": process.pid, "model_pgid": process.pid, "started_at": time.time()}, replace=False)
            last_tick, last_seen = initial["tick"], time.monotonic()
            while process.poll() is None:
                if stop.is_set():
                    reason = "guardian_signal"
                    break
                try:
                    if cancel_path.exists():
                        body = _read_json(cancel_path, 4096)
                        if all(body.get(key) == record[key] for key in ("job_id", "attempt_id", "token")):
                            reason = "cancel_requested"
                            break
                    kind, body = _heartbeat_state(heartbeat, record)
                    if kind == "cancel":
                        reason = "cancel_requested"
                        break
                    if body["tick"] > last_tick:
                        last_tick, last_seen = body["tick"], time.monotonic()
                except (OSError, ValueError, KeyError):
                    pass  # Transient NTFS publication races do not reset the liveness timer.
                if time.monotonic() - last_seen > args.heartbeat_timeout:
                    reason = "heartbeat_lost"
                    break
                time.sleep(0.1)
            returncode = process.poll() if reason == "completed" else 130
    except BaseException:
        reason, returncode = "bridge_execution_failed", 1
    finally:
        if process is not None:
            compute_stopped = stop_model_group(process)
        if returncode not in {0, 1, 2, 130}:
            returncode = 1
        if not Path(args.result).exists():
            status = "cancelled" if returncode == 130 else "failed"
            _atomic_json(args.result, {"schema_version": "1.0", "job_id": request["job_id"], "attempt_id": request["attempt_id"],
                                      "status": status, "artifacts": [], "events": [],
                                      "error": {"code": reason.upper(), "message": "WSL model bridge stopped before publishing a model result"}}, replace=False)
        _atomic_json(done, {**record, "compute_stopped": compute_stopped, "reason": reason,
                           "model_pgid": process.pid if process else None, "guardian_pid": os.getpid(),
                           "exit_code": returncode, "finished_at": time.time()}, replace=False)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return returncode


def linux_entry(args):
    # Detach the actual watchdog from wsl.exe's foreground lifecycle before it starts a model.
    command = [sys.executable, str(Path(__file__).resolve()), "_supervise", "--env-prefix", args.env_prefix,
               "--repo", args.repo, "--request", args.request, "--result", args.result,
               "--token", args.token, "--heartbeat-timeout", str(args.heartbeat_timeout)]
    env = {**os.environ, "PYTHONNOUSERSITE": "1"}
    guardian = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, start_new_session=True, shell=False)
    return guardian.wait()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", default="Ubuntu", choices=["Ubuntu"])
    parser.add_argument("--env-prefix")
    parser.add_argument("--repo")
    parser.add_argument("--heartbeat-timeout", type=float, default=8)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--request", required=True)
    run.add_argument("--result", required=True)
    for name in ("_linux_entry", "_supervise"):
        child = subparsers.add_parser(name)
        for flag in ("env-prefix", "repo", "request", "result", "token"):
            child.add_argument("--" + flag, required=True)
        child.add_argument("--heartbeat-timeout", type=float, default=8)
    args = parser.parse_args(argv)
    if not 2 <= args.heartbeat_timeout <= 10:
        parser.error("heartbeat-timeout must be between 2 and 10 seconds")
    if not args.env_prefix or not args.repo:
        parser.error("administrator env-prefix and repo configuration are required")
    if args.command == "run":
        try:
            return run_windows(args)
        except HeartbeatWriteError as exc:
            _emit_io_diagnostic(exc.diagnostic)
            return 1
    if os.name == "nt":
        parser.error("Linux supervision entry points cannot run on Windows")
    return linux_entry(args) if args.command == "_linux_entry" else supervise_model(args)


if __name__ == "__main__":
    raise SystemExit(main())
