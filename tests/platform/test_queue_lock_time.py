"""Lease clocks are sampled only after an actual competing SQLite writer exits."""

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import packages.runtime.queue as queue_module
from packages.runtime.queue import Queue


@pytest.mark.parametrize("operation", ["enqueue", "claim", "heartbeat", "finish", "recover_expired"])
def test_lease_decisions_use_clock_after_waiting_for_native_sqlite_lock(tmp_path, monkeypatch, operation):
    clock = [1000.0]
    monkeypatch.setattr(queue_module, "time", SimpleNamespace(time=lambda: clock[0]))
    queue = Queue(tmp_path / "runtime.sqlite3")
    job = queue.enqueue("probe", {})
    if operation in ("heartbeat", "finish", "recover_expired"):
        claimed = queue.claim("worker-a", lease_seconds=5)
        assert claimed["lease_expires_at"] == 1005.0

    original_connection = queue.connection
    about_to_wait = threading.Event()

    @contextmanager
    def signalled_connection(write=False):
        if write:
            about_to_wait.set()
        with original_connection(write=write) as db:
            yield db

    monkeypatch.setattr(queue, "connection", signalled_connection)

    def perform():
        if operation == "enqueue":
            return queue.enqueue("probe", {"new": True})
        if operation == "claim":
            return queue.claim("worker-a", lease_seconds=30)
        if operation == "heartbeat":
            return queue.heartbeat(job["job_id"], "worker-a", lease_seconds=30, expected_attempt=1)
        if operation == "finish":
            return queue.finish(job["job_id"], "worker-a", "succeeded", expected_attempt=1)
        return queue.recover_expired()

    with ThreadPoolExecutor(max_workers=1) as executor:
        # Hold the actual native SQLite write transaction while the other
        # thread enters its operation. Advance a controlled clock across the
        # lease boundary; no sleep or wall-clock timing assumption is needed.
        with original_connection(write=True):
            pending = executor.submit(perform)
            assert about_to_wait.wait(timeout=2)
            assert not pending.done()
            clock[0] = 1010.0
        if operation == "finish":
            with pytest.raises(RuntimeError, match="no longer owned"):
                pending.result(timeout=2)
            state = queue.get(job["job_id"])
            assert state["status"] == "running" and state["result"] is None
            assert not any(log["stage"] == "succeeded" for log in queue.logs(job["job_id"]))
            return
        result = pending.result(timeout=2)

    if operation == "enqueue":
        assert result["created_at"] == result["updated_at"] == 1010.0
    elif operation == "claim":
        assert result["lease_expires_at"] == 1040.0
        assert result["updated_at"] == 1010.0
    elif operation == "heartbeat":
        assert result is False
        assert queue.get(job["job_id"])["lease_expires_at"] == 1005.0
    else:
        assert result == [job["job_id"]]
        state = queue.get(job["job_id"])
        assert state["status"] == "failed"
        assert state["error"]["code"] == "WORKER_INTERRUPTED"
        assert state["updated_at"] == 1010.0
