"""Real CPU worker→render cancellation check; isolated queue, original media read-only."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE))
from packages.runtime import Queue, CapacityLedger
from packages.runtime.storage import resolve_owner_path
from packages.runtime.worker import run_once


def process_rows(parent_pid):
    command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               f"@(Get-CimInstance Win32_Process -Filter 'ParentProcessId = {int(parent_pid)}' | Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate) | ConvertTo-Json -Compress"]
    raw = subprocess.check_output(command, text=True, timeout=10).strip()
    rows = json.loads(raw) if raw else []
    return rows if isinstance(rows, list) else [rows]


def alive(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--render-repo", required=True)
    args = parser.parse_args()
    root = Path("D:/video").resolve()
    output = resolve_owner_path(root, args.evidence, "platform")
    if output.exists():
        raise ValueError("preserve previous evidence; choose a new directory")
    output.mkdir(parents=True)
    queue = Queue(output / "runtime-test.sqlite3")
    ledger = CapacityLedger(queue.db_path, root)
    reservation = ledger.reserve("platform", 16_000_000, "render-cancel-validation-setup")
    record = {"case_id": "G-02", "subcase_id": "G-02a-render-cpu-cancel", "started_at": time.time(), "status": "RUNNING", "storage_root": str(root),
              "queue": queue.db_path, "setup_peak_bytes": 16_000_000, "physical_free_before": shutil.disk_usage(root).free,
              "render_repo": args.render_repo, "gpu_used": False}
    record["render_revision"] = subprocess.check_output(["git", "-c", f"safe.directory={args.render_repo}", "-C", args.render_repo, "rev-parse", "HEAD"], text=True).strip()
    os.environ.pop("BTV_DB_PATH", None)
    os.environ["BTV_RENDER_BACKEND"] = "cpu"
    os.environ["BTV_STORAGE_ROOT"] = str(root)
    binary_dir = Path("D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin")
    os.environ["BTV_FFMPEG"], os.environ["BTV_FFPROBE"] = str(binary_dir / "ffmpeg.exe"), str(binary_dir / "ffprobe.exe")
    launcher = f"import sys;sys.path.insert(0,{args.render_repo!r});from packages.render.__main__ import main;raise SystemExit(main())"
    os.environ["BTV_RENDER_COMMAND_JSON"] = json.dumps([sys.executable, "-c", launcher])
    assets = json.loads((root / "data/handoff/assets.v1.json").read_text(encoding="utf-8"))["assets"]
    asset = assets[0]
    record["source"] = {key: asset[key] for key in ("asset_id", "relative_path", "sha256", "size_bytes")}
    def payload(duration, segments):
        return {"assets": [asset], "gpu_required": False, "render_backend": "cpu", "model_id": "render-cpu",
                "parameters": {"research_preview": True, "timeline": {"schema_version": "1.0", "timeline_id": "cpu-cancel-validation",
                    "title": "CPU cancellation integration; real source; research preview",
                    "segments": [{"segment_id": f"segment-{i}", "asset_id": asset["asset_id"], "in_ms": 0, "out_ms": duration,
                                  "speed": 1.0, "fit": "contain", "audio": "mute", "event_ids": [], "review_status": "unreviewed"} for i in range(segments)],
                    "output": {"width": 1080, "height": 1920, "fps": 30, "video_codec": "h264", "audio_codec": "aac"}}}}
    thread = None
    cancelled_job = None
    try:
        lock = root / "render/.render.lock"
        if lock.exists():
            raise RuntimeError("render lock already exists; no other task will be stopped")
        cancelled_job = queue.enqueue("render", payload(4000, 2))
        outcome = {}
        def run_cancel_job():
            try:
                outcome["job"] = run_once(queue, root, worker_id="cancel-integration-worker", lease_seconds=30)
            except BaseException as exc:
                outcome["thread_error"] = repr(exc)
        thread = threading.Thread(target=run_cancel_job, daemon=False)
        thread.start()
        deadline = time.monotonic() + 55
        active = None
        while time.monotonic() < deadline and thread.is_alive():
            if lock.exists():
                try:
                    owner = json.loads(lock.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    time.sleep(0.05)
                    continue
                if owner.get("job_id") != cancelled_job["job_id"]:
                    raise RuntimeError("unexpected lock owner; cannot exercise cancellation")
                children = process_rows(owner["pid"])
                encoding = [item for item in children if item["Name"].lower() == "ffmpeg.exe" and ".partial.mov" in (item.get("CommandLine") or "")]
                if encoding:
                    active = {"lock": owner, "children": children, "observed_at": time.time()}
                    break
            time.sleep(0.1)
        if active is None:
            raise RuntimeError("real encoding process not observed before timeout/completion")
        record["active_before_cancel"] = active
        record["cancel_requested_at"] = time.time()
        queue.request_cancel(cancelled_job["job_id"])
        print(json.dumps({"stage": "cancel_requested", "job_id": cancelled_job["job_id"], "ffmpeg_pids": [p["ProcessId"] for p in active["children"]]}), flush=True)
        thread.join(timeout=25)
        if thread.is_alive():
            raise RuntimeError("worker did not finish after cancellation")
        record["cancel_result"] = queue.get(cancelled_job["job_id"])
        record["cancel_logs"] = queue.logs(cancelled_job["job_id"])
        cancel_file = root / f"platform/jobs/{cancelled_job['job_id']}/attempt-1/cancel.request"
        record["cancel_file"] = {"path": str(cancel_file), "body": json.loads(cancel_file.read_text(encoding="utf-8")) if cancel_file.exists() else None}
        record["lock_released_after_cancel"] = not lock.exists()
        pids = [active["lock"]["pid"], *(item["ProcessId"] for item in active["children"])]
        record["owned_alive_after_cancel"] = [pid for pid in pids if alive(pid)]
        assert record["cancel_result"]["status"] == "cancelled", record["cancel_result"]
        assert record["cancel_file"]["body"]["job_id"] == cancelled_job["job_id"]
        assert record["cancel_file"]["body"]["attempt_id"] == "attempt-1"
        assert record["lock_released_after_cancel"] and not record["owned_alive_after_cancel"]
        next_job = queue.enqueue("render", payload(1000, 1))
        record["next_job_result"] = run_once(queue, root, worker_id="cancel-integration-worker", lease_seconds=30)
        record["next_job_logs"] = queue.logs(next_job["job_id"])
        assert record["next_job_result"]["status"] == "succeeded", record["next_job_result"]
        assert not lock.exists()
        record["status"] = "PASS"
        print(json.dumps({"stage": "complete", "status": "PASS", "cancel_job": cancelled_job["job_id"], "next_job": next_job["job_id"]}), flush=True)
    except BaseException as exc:
        record["status"], record["failure"] = "FAIL", repr(exc)
        if cancelled_job:
            if thread and thread.is_alive():
                queue.request_cancel(cancelled_job["job_id"])
                thread.join(timeout=25)
            record["cancel_result"] = queue.get(cancelled_job["job_id"])
            record["cancel_logs"] = queue.logs(cancelled_job["job_id"])
        raise
    finally:
        record["finished_at"] = time.time()
        record["elapsed_seconds"] = record["finished_at"] - record["started_at"]
        record["physical_free_after"] = shutil.disk_usage(root).free
        (output / "render-cancel-validation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        ledger.release(reservation)


if __name__ == "__main__":
    main()
