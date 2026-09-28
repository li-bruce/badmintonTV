"""Runtime correctness tests; fake CLI fixtures are not video-recognition evidence."""

import concurrent.futures
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from packages.runtime import CapacityLedger, Queue, resolve_relative_path
from packages.runtime.worker import run_once


@pytest.fixture
def queue(tmp_path):
    return Queue(tmp_path / "runtime.sqlite3")


def test_queue_persistence_idempotency_and_competing_claims(queue):
    job = queue.enqueue("probe", {"relative_path": "data/a.mp4"}, "import-a")
    reopened = Queue(queue.db_path)
    assert reopened.enqueue("probe", job["payload"], "import-a")["job_id"] == job["job_id"]
    with pytest.raises(ValueError, match="different request"):
        reopened.enqueue("render", {}, "import-a")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda number: Queue(queue.db_path).claim(f"worker-{number}"), range(8)))
    winners = [item for item in claims if item]
    assert len(winners) == 1
    claimed = winners[0]
    assert claimed["attempt"] == 1
    assert not reopened.heartbeat(job["job_id"], "other-worker")
    assert reopened.heartbeat(job["job_id"], claimed["worker_id"])
    reopened.append_log(job["job_id"], "progress", stage="read", current=7, total=None, unit="bytes")
    completed = reopened.finish(job["job_id"], claimed["worker_id"], "succeeded", result={"checked": True})
    assert completed["result"] == {"checked": True}
    logs = Queue(queue.db_path).logs(job["job_id"])
    assert [entry["seq"] for entry in logs] == list(range(1, len(logs) + 1))
    assert reopened.logs(job["job_id"], after_seq=2) == logs[2:]
    assert completed["progress"]["total"] is None


def test_expired_lease_is_interrupted_requires_explicit_retry(queue, monkeypatch):
    import packages.runtime.queue as queue_module

    now = [1000.0]
    monkeypatch.setattr(queue_module.time, "time", lambda: now[0])
    job = queue.enqueue("probe", {}, max_attempts=2)
    queue.claim("old-worker", lease_seconds=10)
    now[0] = 1011
    assert not queue.heartbeat(job["job_id"], "old-worker")
    assert queue.recover_expired() == [job["job_id"]]
    assert queue.get(job["job_id"])["error"]["code"] == "WORKER_INTERRUPTED"
    assert queue.claim("new-worker") is None
    with pytest.raises(RuntimeError, match="lease"):
        queue.finish(job["job_id"], "old-worker", "succeeded")
    queue.retry(job["job_id"])
    assert queue.claim("new-worker")["attempt"] == 2
    with pytest.raises(RuntimeError):
        queue.finish(job["job_id"], "old-worker", "succeeded")
    queue.finish(job["job_id"], "new-worker", "failed", error={"code": "fixture", "message": "test"})
    with pytest.raises(ValueError, match="maximum attempts"):
        queue.retry(job["job_id"])


def test_queued_and_running_cancellation_are_distinct(queue):
    queued = queue.enqueue("model", {})
    assert queue.request_cancel(queued["job_id"])["status"] == "cancelled"
    assert queue.claim("worker") is None
    queue.retry(queued["job_id"])
    claimed = queue.claim("worker")
    assert queue.request_cancel(claimed["job_id"])["status"] == "running"
    assert queue.finish(claimed["job_id"], "worker", "succeeded")["status"] == "cancelled"


def test_attempt_fences_workers_reusing_same_name(queue):
    job = queue.enqueue("model", {})
    queue.claim("same-name")
    queue.finish(job["job_id"], "same-name", "failed", expected_attempt=1)
    queue.retry(job["job_id"])
    queue.claim("same-name")
    assert not queue.heartbeat(job["job_id"], "same-name", expected_attempt=1)
    with pytest.raises(RuntimeError, match="lease"):
        queue.finish(job["job_id"], "same-name", "succeeded", expected_attempt=1)
    assert queue.heartbeat(job["job_id"], "same-name", expected_attempt=2)


@pytest.mark.parametrize("relative", ["../secret", "/etc/passwd", "data/../secret", "C:/secret", "data\\secret", "data//secret", "data/./secret", "data/a:stream", "data/NUL.txt", "data/file.", "data/file "])
def test_paths_reject_traversal_and_windows_aliases(tmp_path, relative):
    with pytest.raises(ValueError):
        resolve_relative_path(tmp_path, relative)


def test_paths_allow_valid_paths_and_reject_symlink_escape(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    assert resolve_relative_path(storage, "data/video.mp4") == storage / "data" / "video.mp4"
    try:
        (storage / "escape").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not grant symlink creation to this test process")
    with pytest.raises(ValueError, match="escapes"):
        resolve_relative_path(storage, "escape/outside.mp4")


def test_capacity_reservations_are_atomic_and_do_not_remove_existing_data(tmp_path):
    storage = tmp_path / "storage"
    owner = storage / "platform"
    owner.mkdir(parents=True)
    existing = owner / "existing.bin"
    existing.write_bytes(b"x" * 20)
    ledger = CapacityLedger(tmp_path / "capacity.sqlite3", storage, quotas={"platform": 100})
    def reserve(_):
        try:
            return ledger.reserve("platform", 50)
        except ValueError:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        winners = [value for value in executor.map(reserve, range(4)) if value]
    assert len(winners) == 1
    assert ledger.usage()["platform"]["reserved_bytes"] == 50
    ledger.release(winners[0])
    assert ledger.reserve("platform", 80)
    assert existing.read_bytes() == b"x" * 20
    with pytest.raises(ValueError, match="allocated quota"):
        ledger.reserve("unallocated", 1)


def test_directory_scan_raises_instead_of_silently_skipping_permission_errors(tmp_path, monkeypatch):
    import packages.runtime.storage as storage
    def denied_walk(root, followlinks=False, onerror=None):
        onerror(PermissionError("fixture denied"))
        return iter(())
    monkeypatch.setattr(storage.os, "walk", denied_walk)
    with pytest.raises(PermissionError, match="denied"):
        storage.directory_bytes(tmp_path)


def test_unreadable_other_owner_uses_quota_once_only_for_logical_limit(tmp_path, monkeypatch):
    import packages.runtime.storage as storage
    root = tmp_path / "storage"
    (root / "platform").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "platform" / "actual.bin").write_bytes(b"x" * 20)
    ledger = CapacityLedger(tmp_path / "ledger.sqlite3", root, quotas={"platform": 100, "models": 200})
    original_size = storage.directory_bytes
    def inaccessible(path, exclude_roots=()):
        if Path(path) == root / "models":
            raise PermissionError("other owner")
        return original_size(path, exclude_roots)
    monkeypatch.setattr(storage, "directory_bytes", inaccessible)
    monkeypatch.setattr(storage, "GLOBAL_QUOTA", 250)
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda path: type("Disk", (), {"free": 60})())
    usage = ledger.usage()
    assert usage["models"]["used_bytes"] == 200
    assert usage["models"]["measured"] is False
    assert usage["platform"]["used_bytes"] == 20
    # Logical: 20 actual + 200 fallback + 30 reservation = 250; physical only requires 30.
    assert ledger.reserve("platform", 30)
    with pytest.raises(ValueError, match="global hard limit"):
        ledger.reserve("platform", 1)
    with pytest.raises(PermissionError):
        ledger.reserve("models", 1)


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    script = tmp_path / "fake_cli.py"
    script.write_text('''import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('mode'); p.add_argument('run'); p.add_argument('--request'); p.add_argument('--result')
a = p.parse_args(); request = json.loads(Path(a.request).read_text(encoding='utf-8'))
if a.mode == 'slow':
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    print(json.dumps({'schema_version':'1.0','job_id':request['job_id'],'seq':1,'event':'progress','stage':'waiting','message':str(child.pid)}), flush=True)
    time.sleep(60)
output = Path(os.environ['BTV_STORAGE_ROOT']) / request['output_dir']; output.mkdir(parents=True)
artifact = output / 'output.json'; artifact.write_bytes(b'{}')
result = {'schema_version':'1.0','job_id':request['job_id'],'attempt_id':request['attempt_id'],'status':'succeeded','events':[],'error':None,'artifacts':[{'artifact_id':'test-artifact','kind':'report','relative_path':artifact.relative_to(Path(os.environ['BTV_STORAGE_ROOT'])).as_posix(),'sha256':hashlib.sha256(b'{}').hexdigest(),'size_bytes':2,'created_at':'2026-09-28T00:00:00Z','producer':'fixture'}]}
if a.mode == 'wrong-attempt': result['attempt_id'] = 'stale-attempt'
if a.mode == 'bad-artifact': result['artifacts'][0]['sha256'] = '0' * 64
if a.mode == 'blocked': result.update(status='blocked', error={'code':'not_installed','message':'fixture unavailable'})
if a.mode == 'secret': print(os.environ['FIXTURE_API_KEY'], file=sys.stderr, flush=True)
print(json.dumps({'schema_version':'1.0','job_id':request['job_id'],'seq':1,'event':'progress','stage':'written','current':2,'total':2,'unit':'bytes','message':'fixture output'}), flush=True)
if a.mode == 'verbose':
    for seq in range(2, 202):
        print(json.dumps({'schema_version':'1.0','job_id':request['job_id'],'seq':seq,'event':'progress','stage':'logging','current':seq,'total':201,'unit':'records','message':'中文日志'*200}), flush=True)
Path(a.result).write_text(json.dumps(result), encoding='utf-8')
sys.exit(1 if a.mode == 'wrong-exit' else 2 if a.mode == 'blocked' else 0)
''', encoding="utf-8")
    def configure(mode):
        monkeypatch.setenv("BTV_MODEL_COMMAND_JSON", json.dumps([sys.executable, "-u", str(script), mode]))
        return script
    return configure


def model_payload(**overrides):
    return {"assets": [], "parameters": {}, "model_id": "fixture-model", "model_version": "1.0",
            "adapter_operation": "query_parse", **overrides}


def test_adapter_real_subprocess_progress_result_and_persistence(tmp_path, queue, fake_cli):
    fake_cli("success")
    job = queue.enqueue("model", model_payload(command=["must-never-run"]))
    result = run_once(queue, tmp_path)
    assert result["status"] == "succeeded", result
    assert result["result"]["attempt_id"] == "attempt-1"
    assert result["result"]["exit_code"] == 0
    assert result["progress"]["current"] == 2
    assert result["progress"]["source_seq"] == 1
    assert Queue(queue.db_path).get(job["job_id"])["status"] == "succeeded"


@pytest.mark.parametrize("mode,expected", [("wrong-exit", "failed"), ("wrong-attempt", "failed"), ("bad-artifact", "failed"), ("blocked", "blocked")])
def test_adapter_checks_return_code_attempt_and_actual_artifact(tmp_path, queue, fake_cli, mode, expected):
    fake_cli(mode)
    queue.enqueue("model", model_payload())
    result = run_once(queue, tmp_path)
    assert result["status"] == expected, result
    assert result["error"]


def test_adapter_redacts_secret_stderr(tmp_path, queue, fake_cli, monkeypatch):
    fake_cli("secret")
    secret = "fixture-never-log-sensitive-value"
    monkeypatch.setenv("FIXTURE_API_KEY", secret)
    job = queue.enqueue("model", model_payload())
    assert run_once(queue, tmp_path)["status"] == "succeeded"
    logs = json.dumps(queue.logs(job["job_id"]))
    assert secret not in logs
    assert "[REDACTED]" in logs


def test_attempt_log_byte_budget_suppresses_flood_but_task_finishes(tmp_path, queue, fake_cli, monkeypatch):
    from packages.runtime.worker import WorkerContext
    fake_cli("verbose")
    contexts = []
    original_init = WorkerContext.__init__
    def small_budget(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.log_budget_bytes = 1400
        contexts.append(self)
    monkeypatch.setattr(WorkerContext, "__init__", small_budget)
    job = queue.enqueue("model", model_payload())
    result = run_once(queue, tmp_path)
    assert result["status"] == "succeeded", result
    assert result["result"]["exit_code"] == 0
    logs = queue.logs(job["job_id"])
    assert sum(log.get("stage") == "log_budget" for log in logs) == 1
    persisted = [log for log in logs if log["event"] != "state"]
    actual_bytes = sum(len(json.dumps(log, ensure_ascii=False).encode("utf-8")) for log in persisted)
    assert actual_bytes == contexts[0].log_bytes_written <= contexts[0].log_budget_bytes
    assert len(persisted) < 10
    assert logs[-1]["stage"] == "succeeded"


def test_suppressed_logging_still_checks_cancellation(tmp_path, queue):
    from packages.runtime.worker import JobCancelled, WorkerContext
    job = queue.enqueue("model", model_payload())
    claimed = queue.claim("log-budget-worker")
    context = WorkerContext(queue, claimed, "log-budget-worker", tmp_path, 30)
    context.log_budget_bytes = 1000
    context.log("progress", message="large fixture message" * 400)
    assert context.log_omission_reported
    queue.request_cancel(job["job_id"])
    with pytest.raises(JobCancelled):
        context.log("progress", message="this suppressed event must still check cancellation")


def test_missing_model_is_blocked_not_fake_success(tmp_path, queue, monkeypatch):
    monkeypatch.delenv("BTV_MODEL_COMMAND_JSON", raising=False)
    monkeypatch.delenv("BTV_MODEL_COMMANDS_JSON", raising=False)
    queue.enqueue("model", {"assets": []})
    result = run_once(queue, tmp_path)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "not_installed"


def test_model_adapter_uses_capability_and_immutable_model_version(tmp_path, queue, fake_cli):
    fake_cli("success")
    payload = model_payload(parameters={"text": "网前击球", "model_id": "browser-forged-id", "model_version": "browser-forged-version"})
    job = queue.enqueue("model", payload)
    assert run_once(queue, tmp_path)["status"] == "succeeded"
    request = json.loads((tmp_path / "platform" / "jobs" / job["job_id"] / "attempt-1" / "request.json").read_text(encoding="utf-8"))
    assert request["operation"] == "query_parse"
    assert request["parameters"] == {"text": "网前击球", "model_id": "fixture-model", "model_version": "1.0"}
    assert payload["parameters"]["model_id"] == "browser-forged-id"
    assert queue.get(job["job_id"])["operation"] == "model"


@pytest.mark.parametrize("field", ["adapter_operation", "model_id", "model_version"])
def test_model_adapter_does_not_guess_missing_snapshot_fields(tmp_path, queue, fake_cli, field):
    fake_cli("success")
    payload = model_payload()
    del payload[field]
    queue.enqueue("model", payload)
    result = run_once(queue, tmp_path)
    assert result["status"] == "failed"
    assert field in result["error"]["message"]


def test_model_not_in_registered_map_is_not_installed(tmp_path, queue, fake_cli, monkeypatch):
    fake_cli("success")
    monkeypatch.setenv("BTV_MODEL_COMMANDS_JSON", json.dumps({"different-model": [sys.executable]}))
    queue.enqueue("model", model_payload())
    result = run_once(queue, tmp_path)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "not_installed"


@pytest.mark.parametrize("operation", ["model", "render"])
def test_gpu_required_blocks_before_launch_without_shared_lease(tmp_path, queue, fake_cli, operation):
    fake_cli("success")
    job = queue.enqueue(operation, model_payload(gpu_required=True, gpu_lease_token="client-token-is-not-a-lease"))
    result = run_once(queue, tmp_path)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "GPU_LEASE_REQUIRED"
    assert not (tmp_path / "platform" / "jobs" / job["job_id"]).exists()
    assert not any(log.get("stage") == "adapter" for log in queue.logs(job["job_id"]))


def manifest_asset(tmp_path, name, content):
    path = tmp_path / "data" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(content)
    # File-byte verification fixture only; this is not a decodable real video or ML evidence.
    return {"asset_id": f"asset-{name}", "relative_path": f"data/{name}", "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content), "duration_ms": 1000, "width": 16, "height": 16,
            "fps_num": 1, "fps_den": 1, "time_base": "1/1000", "match_id": "match-fixture", "source_type": "synthetic"}


def test_verify_manifest_streams_actual_bytes_and_returns_verified_assets(tmp_path, queue, monkeypatch):
    from packages.runtime.worker import WorkerContext
    monkeypatch.setattr(WorkerContext, "execute", lambda *args, **kwargs: pytest.fail("manifest verification must not spawn ffmpeg or other processes"))
    first = manifest_asset(tmp_path, "first.bin", b"stream-verification-fixture" * 200000)
    second = manifest_asset(tmp_path, "second.bin", b"second fixture")
    job = queue.enqueue("verify_manifest", {"assets": [first, second], "library_id": "library-fixture"})
    result = run_once(queue, tmp_path)
    assert result["status"] == "succeeded", result
    assert result["result"]["attempt_id"] == "attempt-1"
    assert result["result"]["artifacts"] == []
    assert [item["sha256"] for item in result["result"]["assets"]] == [first["sha256"], second["sha256"]]
    assert result["progress"]["stage"] == "verify_manifest"
    assert result["progress"]["current"] == result["progress"]["total"] == first["size_bytes"] + second["size_bytes"]
    assert Queue(queue.db_path).get(job["job_id"])["result"] == result["result"]
    assert list((tmp_path / "platform" / "jobs" / job["job_id"] / "attempt-1").iterdir()) == []


@pytest.mark.parametrize("field,bad_value", [("sha256", "0" * 64), ("size_bytes", 999)])
def test_verify_manifest_rejects_claims_that_do_not_match_source(tmp_path, queue, field, bad_value):
    asset = manifest_asset(tmp_path, "wrong.bin", b"real bytes for integrity verification")
    asset[field] = bad_value
    queue.enqueue("verify_manifest", {"assets": [asset], "library_id": "library-fixture"})
    result = run_once(queue, tmp_path)
    assert result["status"] == "failed"
    assert field + " mismatch" in result["error"]["message"]
    assert result["result"] is None


def test_verify_manifest_does_not_publish_partial_assets(tmp_path, queue):
    first = manifest_asset(tmp_path, "valid.bin", b"valid source")
    second = manifest_asset(tmp_path, "invalid.bin", b"invalid claim")
    second["sha256"] = "0" * 64
    queue.enqueue("verify_manifest", {"assets": [first, second], "library_id": "library-fixture"})
    result = run_once(queue, tmp_path)
    assert result["status"] == "failed"
    assert result["result"] is None
    assert result["progress"]["current"] == first["size_bytes"]


def test_verify_manifest_limits_asset_count(tmp_path, queue):
    queue.enqueue("verify_manifest", {"assets": [{}] * 1001, "library_id": "library-fixture"})
    result = run_once(queue, tmp_path)
    assert result["status"] == "failed"
    assert "1000 assets" in result["error"]["message"]


def test_running_subprocess_cancellation_preserves_heartbeat_and_stops_tree(tmp_path, queue, fake_cli):
    fake_cli("slow")
    job = queue.enqueue("model", model_payload())
    worker = threading.Thread(target=run_once, args=(queue, tmp_path, "cancel-worker", 1))
    worker.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        live = queue.get(job["job_id"])
        if live["progress"] and live["progress"]["stage"] == "waiting":
            break
        time.sleep(0.05)
    else:
        queue.request_cancel(job["job_id"])
        worker.join(timeout=5)
        pytest.fail("test CLI did not start")
    child_pid = int(live["progress"]["message"])
    time.sleep(1.2)  # Longer than the lease: its heartbeat must keep the task alive.
    assert queue.recover_expired() == []
    assert queue.request_cancel(job["job_id"])["status"] == "running"
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert queue.get(job["job_id"])["status"] == "cancelled"
    if os.name == "nt":
        import ctypes
        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, child_pid)
        if process:
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(process)
            assert exit_code.value != 259  # STILL_ACTIVE
    else:
        # A reaped process is absent. An orphan may briefly remain as a terminated zombie.
        status = Path(f"/proc/{child_pid}/stat")
        assert not status.exists() or status.read_text().split()[2] == "Z"
