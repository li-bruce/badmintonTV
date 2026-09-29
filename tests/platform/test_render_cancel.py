"""Real CPU subprocess cancellation; GPU leases use only temporary SQLite state."""
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from packages.runtime import Queue
from packages.runtime.gpu import GPUCoordinator
from packages.runtime import worker


@pytest.fixture
def render_cli(tmp_path, monkeypatch):
    script = tmp_path / "render_cancel_fixture.py"
    script.write_text('''import argparse, json, os, subprocess, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('run'); p.add_argument('--request'); p.add_argument('--result')
a = p.parse_args()
r = json.loads(Path(a.request).read_text(encoding='utf-8'))
exchange = Path(a.request).parent
root = Path(os.environ['BTV_STORAGE_ROOT'])
cancel = Path(os.environ['BTV_RENDER_CANCEL_FILE'])
assert cancel == exchange / 'cancel.request', (cancel, exchange)
identity = {'job_id': r['job_id'], 'attempt_id': r['attempt_id'], 'pid': os.getpid()}
owner = root / 'render'; owner.mkdir(exist_ok=True)
lock = owner / 'fixture-owner.lock'
lock.write_text(json.dumps(identity), encoding='utf-8')
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
(exchange / 'started.json').write_text(json.dumps({**identity, 'child_pid': child.pid,
    'cancel_file': str(cancel), 'gpu_lease_id': os.environ.get('BTV_GPU_LEASE_ID')}), encoding='utf-8')
mode = r['parameters'].get('fixture_mode', 'graceful')
try:
    while not cancel.exists():
        time.sleep(.02)
    (exchange / 'cancel.observed').write_text('received', encoding='utf-8')
    if mode == 'ignore':
        while True: time.sleep(.05)
    # Exceed the parent's bounded reader queue: both pipes must keep draining.
    for n in range(160):
        print('cleanup stdout ' + 'x' * 1024, flush=True)
        print('cleanup stderr ' + 'x' * 1024, file=sys.stderr, flush=True)
    time.sleep(1.4)
finally:
    child.terminate(); child.wait(timeout=5)
    if json.loads(lock.read_text(encoding='utf-8')) == identity:
        lock.unlink()
    (exchange / 'cleanup.done').write_text(json.dumps(identity), encoding='utf-8')
result = {'schema_version':'1.0', 'job_id':r['job_id'], 'attempt_id':r['attempt_id'],
    'status':'cancelled', 'artifacts':[], 'events':[], 'error':{'code':'cancelled','message':'fixture cleanup finished'}}
Path(a.result).write_text(json.dumps(result), encoding='utf-8')
sys.exit(130)
''', encoding="utf-8")
    monkeypatch.setenv("BTV_RENDER_COMMAND_JSON", json.dumps([sys.executable, "-u", str(script)]))
    monkeypatch.setenv("BTV_RENDER_BACKEND", "cpu")
    monkeypatch.setenv("BTV_DB_PATH", str(tmp_path / "unused-platform.sqlite3"))
    # The worker must overwrite inherited/user payload signal paths.
    foreign = tmp_path / "unrelated.lock"
    foreign.write_text("unrelated owner", encoding="utf-8")
    monkeypatch.setenv("BTV_RENDER_CANCEL_FILE", str(foreign))
    return foreign


def await_condition(condition, message, *, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(.02)
    pytest.fail(message)


def assert_stopped(pid):
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            code = ctypes.c_ulong()
            try:
                assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                assert code.value != 259
            finally:
                kernel.CloseHandle(handle)
    else:
        state = Path(f"/proc/{pid}/stat")
        assert not state.exists() or state.read_text().split()[2] == "Z"


@pytest.mark.parametrize("trigger", ["cancel", "timeout"])
def test_render_graceful_cleanup_precedes_terminal_and_gpu_release(tmp_path, monkeypatch, render_cli, trigger):
    queue = Queue(tmp_path / "runtime.sqlite3")
    gpu = GPUCoordinator(queue.db_path)
    gpu.grant_window("cpu-protocol-fixture", ["render-fixture"], 60,
                     coordination_note="CPU-only subprocess and SQLite lease test; no GPU code")
    job = queue.enqueue("render", {"assets": [], "gpu_required": True, "model_id": "render-fixture",
                                   "parameters": {"cancel_file": str(render_cli)}})
    exchange = tmp_path / "platform/jobs" / job["job_id"] / "attempt-1"
    lock = tmp_path / "render/fixture-owner.lock"
    releases, forbidden_calls = [], []
    original_release, original_finish = GPUCoordinator.release, Queue.finish
    original_log, original_check, original_execute = worker.WorkerContext.log, worker.WorkerContext.check, worker.WorkerContext.execute

    def release(self, lease_id, worker_id, *, compute_stopped):
        assert compute_stopped is True
        assert (exchange / "cleanup.done").is_file()
        assert not lock.exists()
        assert queue.get(job["job_id"])["status"] == "running"
        started = json.loads((exchange / "started.json").read_text())
        assert_stopped(started["pid"])
        assert_stopped(started["child_pid"])
        releases.append(lease_id)
        return original_release(self, lease_id, worker_id, compute_stopped=compute_stopped)

    def finish(self, *args, **kwargs):
        assert len(releases) == 1
        assert gpu.get(releases[0])["status"] == "released"
        return original_finish(self, *args, **kwargs)

    def guarded_log(self, *args, **kwargs):
        if (exchange / "cancel.observed").exists():
            forbidden_calls.append("log")
        return original_log(self, *args, **kwargs)

    def guarded_check(self):
        if (exchange / "cancel.observed").exists():
            forbidden_calls.append("check")
        return original_check(self)

    def timed_execute(self, *args, **kwargs):
        kwargs["timeout"] = .6
        return original_execute(self, *args, **kwargs)

    monkeypatch.setattr(GPUCoordinator, "release", release)
    monkeypatch.setattr(Queue, "finish", finish)
    monkeypatch.setattr(worker.WorkerContext, "log", guarded_log)
    monkeypatch.setattr(worker.WorkerContext, "check", guarded_check)
    if trigger == "timeout":
        monkeypatch.setattr(worker.WorkerContext, "execute", timed_execute)
    thread = threading.Thread(target=worker.run_once, args=(queue, tmp_path, "render-cleanup-worker", .8))
    thread.start()
    try:
        await_condition(lambda: (exchange / "started.json").is_file(), "CPU CLI did not start")
        if trigger == "cancel":
            assert queue.request_cancel(job["job_id"])["status"] == "running"
        await_condition(lambda: (exchange / "cancel.observed").exists(), "CLI did not receive its trusted cancellation file")
        before_job = queue.get(job["job_id"])
        before_gpu = gpu.status()["lease"]
        time.sleep(.9)  # Longer than the lease, shorter than the fixture finally delay.
        during_job, during_gpu = queue.get(job["job_id"]), gpu.get(before_gpu["lease_id"])
        assert during_job["status"] == "running" and lock.exists()
        assert during_job["lease_expires_at"] > before_job["lease_expires_at"]
        assert during_gpu["status"] == "active" and during_gpu["expires_at"] > before_gpu["expires_at"]
        assert queue.recover_expired() == []
    finally:
        if thread.is_alive() and not (exchange / "cancel.observed").exists():
            queue.request_cancel(job["job_id"])
        thread.join(timeout=12)
    assert not thread.is_alive()
    result = queue.get(job["job_id"])
    assert result["status"] == ("cancelled" if trigger == "cancel" else "failed"), result
    assert result["error"]["code"] == ("cancelled" if trigger == "cancel" else "TimeoutError")
    assert forbidden_calls == []
    assert len(releases) == 1
    assert not lock.exists()
    assert render_cli.read_text() == "unrelated owner"
    assert json.loads((exchange / "cancel.request").read_text())["attempt_id"] == "attempt-1"
    cleanup_logs = [row for row in queue.logs(job["job_id"]) if row.get("stage") == "render_cancel_cleanup"]
    assert len(cleanup_logs) == 1 and cleanup_logs[0]["graceful"] is True


def test_unresponsive_render_is_hard_stopped_with_explicit_cleanup_error(tmp_path, monkeypatch, render_cli):
    monkeypatch.setattr(worker, "RENDER_CANCEL_GRACE_SECONDS", .3)
    queue = Queue(tmp_path / "runtime.sqlite3")
    job = queue.enqueue("render", {"assets": [], "parameters": {"fixture_mode": "ignore"}})
    exchange = tmp_path / "platform/jobs" / job["job_id"] / "attempt-1"
    thread = threading.Thread(target=worker.run_once, args=(queue, tmp_path, "unresponsive-render", 2))
    thread.start()
    try:
        await_condition(lambda: (exchange / "started.json").is_file(), "CPU CLI did not start")
        queue.request_cancel(job["job_id"])
    finally:
        thread.join(timeout=12)
    assert not thread.is_alive()
    result = queue.get(job["job_id"])
    assert result["status"] == "failed", result
    assert result["error"]["code"] == "RENDER_CLEANUP_REQUIRED"
    assert "人工核验" in result["error"]["message"]
    assert (tmp_path / "render/fixture-owner.lock").is_file()  # Worker must not impersonate lock owner.
    assert not (exchange / "cleanup.done").exists()
    started = json.loads((exchange / "started.json").read_text())
    assert_stopped(started["pid"])
    assert_stopped(started["child_pid"])
    assert render_cli.read_text() == "unrelated owner"
    cleanup_logs = [row for row in queue.logs(job["job_id"]) if row.get("stage") == "render_cancel_cleanup"]
    assert len(cleanup_logs) == 1 and cleanup_logs[0]["graceful"] is False
