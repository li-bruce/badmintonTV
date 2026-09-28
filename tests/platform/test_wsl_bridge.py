"""Bridge tests separate byte/path/process safety from real model inference."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from packages.runtime.wsl_bridge import (
    build_wsl_command, exchange_paths, validate_env_prefix,
    wait_for_bridge_done, windows_to_wsl,
)


def test_windows_paths_translate_without_shell_interpretation():
    assert windows_to_wsl(r"D:\video\platform\jobs\job-01\attempt-1\request.json", storage_only=True) == "/mnt/d/video/platform/jobs/job-01/attempt-1/request.json"
    assert windows_to_wsl("C:/Users/USER/Repo with space") == "/mnt/c/Users/Li/Repo with space"
    assert windows_to_wsl("D:/video/a;$literal.txt", storage_only=True) == "/mnt/d/video/a;$literal.txt"


@pytest.mark.parametrize("value", ["D:video/file", "../video/file", "/mnt/d/video/file", "C:/video/file", "D:/video2/file",
                                   "D:/video/../file", "D:/video/./file", r"\\host\share\video", "D:/video/file:ads", "D:/video/NUL.txt", "D:/video/file. "])
def test_storage_exchange_translation_rejects_escaping_or_ambiguous_paths(value):
    with pytest.raises(ValueError):
        windows_to_wsl(value, storage_only=True)


def test_exchange_requires_same_attempt_directory(monkeypatch):
    # Pure path checks run on Windows without touching the actual storage directory.
    import packages.runtime.wsl_bridge as bridge
    monkeypatch.setattr(bridge.os, "name", "posix")
    request = "D:/video/platform/jobs/job-1/attempt-1/request.json"
    result = "D:/video/platform/jobs/job-1/attempt-1/result.json"
    assert exchange_paths(request, result)[2:] == ("job-1", "attempt-1")
    for invalid in [result.replace("attempt-1", "attempt-2"), result.replace("result.json", "other.json")]:
        with pytest.raises(ValueError):
            exchange_paths(request, invalid)
    with pytest.raises(ValueError):
        exchange_paths(request.replace("platform", "models"), result.replace("platform", "models"))


@pytest.mark.parametrize("value", ["/usr", "/mnt/d/video/runtime/models", "/mnt/d/video/runtime/models/../env", "/mnt/d/video/runtime/models/env/", "relative/env"])
def test_environment_prefix_is_fixed_to_models_runtime(value):
    with pytest.raises(ValueError):
        validate_env_prefix(value)


def test_wsl_command_uses_argv_env_and_fixed_python_module():
    args = argparse.Namespace(distribution="Ubuntu", env_prefix="/mnt/d/video/runtime/models/env", repo="C:/repo with spaces", heartbeat_timeout=8)
    command = build_wsl_command(args, "/mnt/d/video/platform/jobs/job/attempt-1/request.json", "/mnt/d/video/platform/jobs/job/attempt-1/result.json", "token")
    assert command[:5] == ["wsl.exe", "--distribution", "Ubuntu", "--exec", "/usr/bin/env"]
    assert "HF_HUB_OFFLINE=1" in command and "TRANSFORMERS_OFFLINE=1" in command
    assert "TORCH_HOME=/mnt/d/video/models/cache/torch" in command
    assert command[command.index("--repo") + 1] == "/mnt/c/repo with spaces"
    assert "bash" not in command and "-c" not in command


@pytest.mark.parametrize("body,expected", [
    ({"job_id": "job", "attempt_id": "attempt-1", "compute_stopped": True}, True),
    ({"job_id": "job", "attempt_id": "attempt-2", "compute_stopped": True}, False),
    ({"job_id": "other", "attempt_id": "attempt-1", "compute_stopped": True}, False),
    ({"job_id": "job", "attempt_id": "attempt-1", "compute_stopped": "true"}, False),
    ({"job_id": "job", "attempt_id": "attempt-1", "compute_stopped": False}, False),
])
def test_done_evidence_requires_exact_job_attempt_and_boolean(tmp_path, body, expected):
    path = tmp_path / "bridge.done.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    assert wait_for_bridge_done(path, "job", "attempt-1", timeout=0) is expected


def test_bridge_registration_requires_gpu_even_when_payload_claims_cpu(tmp_path, monkeypatch):
    from packages.runtime import Queue
    from packages.runtime.worker import run_once
    monkeypatch.setenv("BTV_MODEL_COMMANDS_JSON", json.dumps({"pose": [sys.executable, "-m", "packages.runtime.wsl_bridge"]}))
    queue = Queue(tmp_path / "runtime.sqlite3")
    queue.enqueue("model", {"model_id": "pose", "model_version": "1", "adapter_operation": "pose", "gpu_required": False, "assets": [], "parameters": {}})
    result = run_once(queue, tmp_path)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "GPU_LEASE_REQUIRED"


@pytest.mark.parametrize("matching_done,expected_code", [(True, "ready"), (False, "GPU_LEASE_ORPHANED")])
def test_worker_gpu_release_requires_matching_bridge_done(tmp_path, monkeypatch, matching_done, expected_code):
    from packages.runtime import Queue
    from packages.runtime.gpu import GPUCoordinator
    from packages.runtime.worker import WorkerContext, run_once
    import packages.runtime.wsl_bridge as bridge
    queue = Queue(tmp_path / "runtime.sqlite3")
    coordinator = GPUCoordinator(queue.db_path)
    coordinator.grant_window("fixture-window", ["pose"], 60, coordination_note="CPU-only worker cleanup protocol fixture; does not run GPU code")
    monkeypatch.setenv("BTV_MODEL_COMMANDS_JSON", json.dumps({"pose": [sys.executable, "-m", "packages.runtime.wsl_bridge"]}))
    original_wait = bridge.wait_for_bridge_done
    monkeypatch.setattr(bridge, "wait_for_bridge_done", lambda path, job_id, attempt_id, timeout=15: original_wait(path, job_id, attempt_id, timeout=0))
    def fixture_execute(self, argv, *args, **kwargs):
        self.compute_started, self.compute_stopped = True, True
        request_path = Path(argv[argv.index("--request") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result_path = Path(argv[argv.index("--result") + 1])
        result_path.write_text(json.dumps({"schema_version": "1.0", "job_id": request["job_id"], "attempt_id": request["attempt_id"], "status": "succeeded", "artifacts": [], "events": [], "error": None}), encoding="utf-8")
        request_path.with_name("bridge.done.json").write_text(json.dumps({"job_id": request["job_id"], "attempt_id": request["attempt_id"] if matching_done else "attempt-stale", "compute_stopped": True}), encoding="utf-8")
        return 0, "", ""
    monkeypatch.setattr(WorkerContext, "execute", fixture_execute)
    queue.enqueue("model", {"model_id": "pose", "model_version": "1", "adapter_operation": "pose", "gpu_required": False, "assets": [], "parameters": {}})
    result = run_once(queue, tmp_path)
    if matching_done:
        assert result["status"] == "succeeded"
        assert coordinator.status()["lease"] is None
    else:
        assert result["status"] == "failed"
        assert result["error"]["code"] == "WORKER_INTERRUPTED"
        assert coordinator.status()["code"] == expected_code


@pytest.mark.parametrize("done_case", ["matching", "false", "mismatched", "missing"])
def test_cancel_stays_running_and_heartbeating_until_bridge_cleanup(tmp_path, monkeypatch, done_case):
    from packages.runtime import Queue
    from packages.runtime.gpu import GPUCoordinator
    from packages.runtime.worker import JobCancelled, WorkerContext, run_once
    import packages.runtime.wsl_bridge as bridge
    queue = Queue(tmp_path / "runtime.sqlite3")
    coordinator = GPUCoordinator(queue.db_path)
    coordinator.grant_window("fixture-window", ["pose"], 60, coordination_note="NoGPU cancellation/cleanup protocol fixture")
    monkeypatch.setenv("BTV_MODEL_COMMANDS_JSON", json.dumps({"pose": [sys.executable, "-m", "packages.runtime.wsl_bridge"]}))
    original_wait = bridge.wait_for_bridge_done
    observed_leases = []

    def fixture_execute(self, argv, *args, **kwargs):
        self.compute_started, self.compute_stopped = True, True
        queue.request_cancel(self.job["job_id"])
        raise JobCancelled("fixture Windows bridge stopped; Linux stop confirmation is still pending")

    def wait_for_cleanup(path, job_id, attempt_id, timeout=15):
        live = queue.get(job_id)
        lease = coordinator.status()["lease"]
        assert live["status"] == "running"
        assert live["cancel_requested"] is True
        assert lease["status"] == "active"
        observed_leases.append(lease["lease_id"])
        before_job_heartbeat = live["lease_expires_at"]
        before_gpu_heartbeat = lease["expires_at"]
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            live = queue.get(job_id)
            lease = coordinator.get(lease["lease_id"])
            assert live["status"] == "running"
            assert live["cancel_requested"] is True
            assert lease["status"] == "active"
            if live["lease_expires_at"] > before_job_heartbeat and lease["expires_at"] > before_gpu_heartbeat:
                break
            time.sleep(0.02)
        else:
            pytest.fail("job and GPU heartbeats did not advance during bridge cleanup")
        if done_case != "missing":
            Path(path).write_text(json.dumps({"job_id": job_id, "attempt_id": attempt_id if done_case != "mismatched" else "attempt-stale",
                                             "compute_stopped": done_case != "false"}), encoding="utf-8")
        return original_wait(path, job_id, attempt_id, timeout=0)

    monkeypatch.setattr(WorkerContext, "execute", fixture_execute)
    monkeypatch.setattr(bridge, "wait_for_bridge_done", wait_for_cleanup)
    job = queue.enqueue("model", {"model_id": "pose", "model_version": "1", "adapter_operation": "pose", "gpu_required": False, "assets": [], "parameters": {}})
    result = run_once(queue, tmp_path, worker_id="cleanup-fixture-worker", lease_seconds=1.5)
    assert len(observed_leases) == 1
    lease = coordinator.get(observed_leases[0])
    if done_case == "matching":
        assert result["status"] == "cancelled"
        assert lease["status"] == "released"
    else:
        assert result["status"] == "failed"
        assert result["error"]["code"] == "WORKER_INTERRUPTED"
        assert lease["status"] == "orphaned"
    assert queue.get(job["job_id"])["cancel_requested"] is True


@pytest.mark.skipif(os.name != "nt" or not os.environ.get("BTV_WSL_BRIDGE_TEST_ENV"), reason="explicit Windows/WSL CPU watchdog integration opt-in required")
def test_windows_job_death_triggers_linux_watchdog_cleanup():
    """Actual Windows→WSL boundary using a stdlib-only fake model; no GPU is loaded."""
    from packages.runtime.windows_job import WindowsJob
    from packages.runtime.wsl_bridge import wait_for_bridge_done
    identifier = "job-bridge-watchdog-" + uuid.uuid4().hex
    directory = Path("D:/video/platform/jobs") / identifier / "attempt-1"
    directory.mkdir(parents=True)
    repo = directory / "fixture-repo"
    module = repo / "packages" / "models"
    module.mkdir(parents=True)
    (module / "__main__.py").write_text("""import argparse,json,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--request');p.add_argument('--result');a=p.parse_args()
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
Path(a.request).with_name('fixture-child.json').write_text(json.dumps({'pid':child.pid}))
time.sleep(60)
""", encoding="utf-8")
    request = directory / "request.json"
    request.write_text(json.dumps({"schema_version": "1.0", "job_id": identifier, "attempt_id": "attempt-1", "operation": "query_parse", "assets": [], "parameters": {"model_id": "fixture-cpu"}, "output_dir": "models/jobs/" + identifier + "/attempt-1"}), encoding="utf-8")
    command = [sys.executable, "-m", "packages.runtime.wsl_bridge", "--env-prefix", os.environ["BTV_WSL_BRIDGE_TEST_ENV"], "--repo", str(repo), "--heartbeat-timeout", "2", "run", "--request", str(request), "--result", str(directory / "result.json")]
    job = WindowsJob()
    process = subprocess.Popen([sys.executable, "-m", "packages.runtime.launcher"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        job.assign(process)
        process.stdin.write(json.dumps(command) + "\n")
        process.stdin.close()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (directory / "fixture-child.json").exists():
            if process.poll() is not None:
                pytest.fail("WSL bridge exited before fixture model started: " + process.stderr.read())
            time.sleep(0.1)
        assert (directory / "fixture-child.json").exists(), "CPU fixture model did not start"
        job.close()  # Simulate abrupt Windows worker/bridge/wsl.exe death.
        process.wait(timeout=10)
        assert wait_for_bridge_done(directory / "bridge.done.json", identifier, "attempt-1", timeout=12)
        done = json.loads((directory / "bridge.done.json").read_text(encoding="utf-8"))
        assert done["reason"] in {"heartbeat_lost", "guardian_signal"}
        assert done["compute_stopped"] is True
        print("CPU watchdog evidence:", directory / "bridge.done.json")
    finally:
        job.close()
        if process.poll() is None:
            process.kill()
