"""Native SQLite GPU scheduling tests. No CUDA process or real grant is started."""

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from packages.runtime.gpu import GPUCoordinator, GPUUnavailable, main
from packages.runtime.queue import Queue


@pytest.fixture
def gpu_env(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    queue = Queue(path)
    clock = [time.time()]
    gpu = GPUCoordinator(path, clock=lambda: clock[0])

    def running(model="model-approved", worker="worker-a"):
        job = queue.enqueue("model", {"model_id": model})
        claimed = queue.claim(worker, lease_seconds=10000)
        assert claimed["job_id"] == job["job_id"]
        return claimed

    return gpu, queue, clock, running


def grant(gpu, seconds=120):
    return gpu.grant_window("window-1", ["model-approved"], seconds, coordination_note="Synthetic scheduler test; not a real GPU window")


def claim(gpu, job, seconds=30):
    return gpu.claim(job["payload"]["model_id"], job["job_id"], job["attempt"], job["worker_id"], lease_seconds=seconds)


def test_default_requires_admin_window_and_model_allowlist(gpu_env):
    gpu, _, _, running = gpu_env
    job = running()
    with pytest.raises(GPUUnavailable) as error:
        claim(gpu, job)
    assert error.value.code == "GPU_LEASE_REQUIRED"
    assert gpu.status()["code"] == "GPU_LEASE_REQUIRED"
    grant(gpu)
    wrong_model = running("not-approved", "worker-b")
    with pytest.raises(GPUUnavailable) as error:
        claim(gpu, wrong_model)
    assert error.value.code == "GPU_LEASE_REQUIRED"
    lease = claim(gpu, job)
    assert lease["resource"] == "gpu0" and lease["status"] == "active"
    status = gpu.status()
    assert status["lease"]["job_id"] == job["job_id"]
    assert status["lease"]["worker_id"] == "worker-a"
    assert status["active_window"]["model_ids"] == ["model-approved"]


def test_single_atomic_owner_across_two_coordinators(gpu_env):
    gpu, _, clock, running = gpu_env
    grant(gpu)
    jobs = [running(worker="worker-a"), running(worker="worker-b")]
    second = GPUCoordinator(gpu.db_path, clock=lambda: clock[0])

    def attempt(pair):
        coordinator, job = pair
        try:
            return claim(coordinator, job)["lease_id"]
        except GPUUnavailable as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attempt, [(gpu, jobs[0]), (second, jobs[1])]))
    assert result.count("GPU_BUSY") == 1
    assert len([item for item in result if item.startswith("gpu-lease-")]) == 1


def test_claim_requires_current_running_job_worker_attempt_and_model(gpu_env):
    gpu, _, _, running = gpu_env
    grant(gpu)
    job = running()
    for job_id, attempt, worker in (("absent-job", 1, "worker-a"), (job["job_id"], 2, "worker-a"), (job["job_id"], 1, "worker-wrong")):
        with pytest.raises(GPUUnavailable) as error:
            gpu.claim("model-approved", job_id, attempt, worker)
        assert error.value.code == "GPU_JOB_LEASE_MISMATCH"
    different = running("not-approved", "worker-b")
    with pytest.raises(GPUUnavailable) as error:
        gpu.claim("model-approved", different["job_id"], 1, "worker-b")
    assert error.value.code == "GPU_MODEL_MISMATCH"


def test_heartbeat_is_capped_by_window_and_wrong_worker_cannot_extend(gpu_env):
    gpu, _, clock, running = gpu_env
    window = grant(gpu, seconds=40)
    lease = claim(gpu, running(), seconds=20)
    clock[0] += 10
    assert gpu.heartbeat(lease["lease_id"], "worker-a", lease_seconds=100)
    assert gpu.get(lease["lease_id"])["expires_at"] == window["expires_at"]
    assert not gpu.heartbeat(lease["lease_id"], "worker-wrong")
    clock[0] = window["expires_at"]
    assert not gpu.heartbeat(lease["lease_id"], "worker-a")
    assert gpu.get(lease["lease_id"])["status"] == "orphaned"


def test_expired_lease_is_persistently_orphaned_never_reused(gpu_env):
    gpu, _, clock, running = gpu_env
    grant(gpu)
    lease = claim(gpu, running(), seconds=5)
    waiting = running(worker="worker-b")
    clock[0] += 6
    with pytest.raises(GPUUnavailable) as error:
        claim(gpu, waiting)
    assert error.value.code == "GPU_LEASE_ORPHANED"
    # The blocked claim must commit the orphan transition rather than roll it back.
    with gpu.queue.connection() as db:
        assert db.execute("SELECT status FROM resource_leases WHERE lease_id=?", (lease["lease_id"],)).fetchone()[0] == "orphaned"
    restarted = GPUCoordinator(gpu.db_path, clock=lambda: clock[0])
    assert restarted.status()["code"] == "GPU_LEASE_ORPHANED"
    assert not restarted.release(lease["lease_id"], "worker-a", compute_stopped=True)
    assert not restarted.heartbeat(lease["lease_id"], "worker-a")


def test_release_requires_trusted_stop_and_current_owner(gpu_env):
    gpu, _, _, running = gpu_env
    grant(gpu)
    lease = claim(gpu, running())
    for unproven in (False, None, 1, "true"):
        with pytest.raises(GPUUnavailable) as error:
            gpu.release(lease["lease_id"], "worker-a", compute_stopped=unproven)
        assert error.value.code == "GPU_STOP_UNVERIFIED"
    assert not gpu.release(lease["lease_id"], "other-worker", compute_stopped=True)
    assert gpu.release(lease["lease_id"], "worker-a", compute_stopped=True)
    assert not gpu.release(lease["lease_id"], "worker-a", compute_stopped=True)
    assert gpu.get(lease["lease_id"])["release_evidence"]["method"] == "trusted_worker_compute_stopped"
    claim(gpu, running(worker="worker-next"))


def test_unverified_bridge_stop_immediately_orphans_lease(gpu_env):
    gpu, _, _, running = gpu_env
    grant(gpu)
    lease = claim(gpu, running())
    assert not gpu.mark_orphaned(lease["lease_id"], "wrong-worker", "wrong")
    assert gpu.mark_orphaned(lease["lease_id"], "worker-a", "bridge.done absent after watchdog timeout")
    assert gpu.status()["lease"]["orphan_reason"] == "bridge.done absent after watchdog timeout"
    assert not gpu.release(lease["lease_id"], "worker-a", compute_stopped=True)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf"), True, 3601])
def test_window_duration_is_finite_bounded(gpu_env, seconds):
    gpu, *_ = gpu_env
    with pytest.raises(ValueError):
        grant(gpu, seconds)


def test_grants_are_explicit_non_overlapping_and_cannot_extend_existing_ids(gpu_env):
    gpu, _, clock, _ = gpu_env
    with pytest.raises(ValueError, match="coordination_note"):
        gpu.grant_window("no-coordination", ["model-approved"], 10)
    grant(gpu, seconds=5)
    with pytest.raises(GPUUnavailable) as error:
        gpu.grant_window("overlap", ["model-approved"], 5, coordination_note="test")
    assert error.value.code == "GPU_WINDOW_ACTIVE"
    clock[0] += 6
    with pytest.raises(GPUUnavailable) as error:
        grant(gpu)
    assert error.value.code == "GPU_WINDOW_EXISTS"
    assert gpu.grant_window("new-window", ["model-approved"], 5, coordination_note="test")["window_id"] == "new-window"


def orphan_with_done(gpu_env, tmp_path):
    gpu, _, clock, running = gpu_env
    grant(gpu)
    lease = claim(gpu, running(), seconds=1)
    clock[0] += 2
    gpu.status()
    done = tmp_path / "bridge.done.json"
    done.write_text(json.dumps({"job_id": lease["job_id"], "attempt_id": "attempt-1", "compute_stopped": True}), encoding="utf-8")
    return gpu, lease, done


def test_admin_recovery_checks_bridge_identity_then_live_gpu(gpu_env, tmp_path, monkeypatch):
    gpu, lease, done = orphan_with_done(gpu_env, tmp_path)
    calls = []

    def empty_gpu(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", empty_gpu)
    assert gpu.prove_stopped(lease["lease_id"], done, nvidia_smi="fixed-nvidia-smi", administrator="test-admin", note="test watchdog stop verified")
    assert calls == [["fixed-nvidia-smi", "--id=0", "--query-compute-apps=pid", "--format=csv,noheader,nounits"]]
    result = gpu.get(lease["lease_id"])
    assert result["status"] == "released"
    assert result["release_evidence"]["administrator"] == "test-admin"


@pytest.mark.parametrize("changes", [{"job_id": "wrong-job"}, {"attempt_id": "attempt-0"}, {"compute_stopped": False}, {"compute_stopped": "true"}])
def test_admin_recovery_refuses_stale_or_unproven_done(gpu_env, tmp_path, monkeypatch, changes):
    gpu, lease, done = orphan_with_done(gpu_env, tmp_path)
    data = json.loads(done.read_text())
    done.write_text(json.dumps({**data, **changes}), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("invalid bridge marker must be rejected before GPU check"))
    with pytest.raises(GPUUnavailable) as error:
        gpu.prove_stopped(lease["lease_id"], done, nvidia_smi="fixed", note="test")
    assert error.value.code == "GPU_STOP_UNVERIFIED"
    assert gpu.get(lease["lease_id"])["status"] == "orphaned"


@pytest.mark.parametrize("returncode,stdout", [(0, "9876\n"), (0, "N/A\n"), (1, "")])
def test_admin_recovery_refuses_live_or_unknown_gpu_process_state(gpu_env, tmp_path, monkeypatch, returncode, stdout):
    gpu, lease, done = orphan_with_done(gpu_env, tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=""))
    with pytest.raises(GPUUnavailable):
        gpu.prove_stopped(lease["lease_id"], done, nvidia_smi="fixed", note="test")
    assert gpu.get(lease["lease_id"])["status"] == "orphaned"


def test_admin_cli_grant_and_status(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"
    assert main(["status", "--db", str(db)]) == 0
    assert json.loads(capsys.readouterr().out)["code"] == "GPU_LEASE_REQUIRED"
    assert main(["grant-window", "--db", str(db), "--window-id", "cli-test", "--models", "model-a,model-b", "--seconds", "30", "--coordination-note", "Test only; no real GPU started"]) == 0
    assert json.loads(capsys.readouterr().out)["model_ids"] == ["model-a", "model-b"]
    assert main(["grant-window", "--db", str(db), "--window-id", "bad", "--models", "model-a", "--seconds", "nan", "--coordination-note", "test"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "GPU_CONFIGURATION_ERROR"


@pytest.mark.parametrize("operation", ["grant", "claim", "heartbeat", "release", "status"])
def test_waiting_for_sqlite_writer_never_reuses_stale_clock(gpu_env, monkeypatch, operation):
    gpu, _, clock, running = gpu_env
    if operation != "grant":
        grant(gpu, seconds=5 if operation == "claim" else 120)
    job = running()
    lease = claim(gpu, job, seconds=5) if operation in ("heartbeat", "release", "status") else None
    original_connection = gpu.queue.connection

    @contextmanager
    def delayed_writer(write=False):
        with original_connection(write=write) as db:
            if write:
                # Model six seconds spent awaiting SQLite's writer lock.
                clock[0] += 6
            yield db

    monkeypatch.setattr(gpu.queue, "connection", delayed_writer)
    if operation == "grant":
        assert grant(gpu)["created_at"] == clock[0]
    elif operation == "claim":
        with pytest.raises(GPUUnavailable) as error:
            claim(gpu, job)
        assert error.value.code == "GPU_LEASE_REQUIRED"
    elif operation == "heartbeat":
        assert not gpu.heartbeat(lease["lease_id"], "worker-a")
    elif operation == "release":
        assert not gpu.release(lease["lease_id"], "worker-a", compute_stopped=True)
    else:
        assert gpu.status()["code"] == "GPU_LEASE_ORPHANED"


def test_revoke_released_window_prevents_any_new_claim(gpu_env):
    gpu, _, clock, running = gpu_env
    original = grant(gpu, seconds=120)
    lease = claim(gpu, running())
    assert gpu.release(lease["lease_id"], "worker-a", compute_stopped=True)
    clock[0] += 1
    revoked = gpu.revoke_window("window-1", reason="verified compute stopped; return GPU to models")
    assert revoked["expires_at"] == revoked["revoked_at"] == clock[0]
    assert revoked["expires_at"] < original["expires_at"]
    assert revoked["revocation_reason"] == "verified compute stopped; return GPU to models"
    assert gpu.status()["code"] == "GPU_LEASE_REQUIRED"
    waiting = running(worker="next-worker")
    with pytest.raises(GPUUnavailable) as error:
        claim(gpu, waiting)
    assert error.value.code == "GPU_LEASE_REQUIRED"
    clock[0] += 1
    again = gpu.revoke_window("window-1", reason="retry must not rewrite original audit")
    assert again == revoked


@pytest.mark.parametrize("orphaned", [False, True])
def test_revoke_refuses_active_or_orphaned_leases(gpu_env, orphaned):
    gpu, _, clock, running = gpu_env
    window = grant(gpu)
    lease = claim(gpu, running(), seconds=5)
    if orphaned:
        clock[0] += 6
    with pytest.raises(GPUUnavailable) as error:
        gpu.revoke_window("window-1", reason="must not bypass existing compute")
    assert error.value.code == "GPU_WINDOW_IN_USE"
    assert gpu.get_window("window-1")["expires_at"] == window["expires_at"]
    assert gpu.get_window("window-1")["revoked_at"] is None
    assert gpu.get(lease["lease_id"])["status"] == ("orphaned" if orphaned else "active")


def test_revocation_migration_preserves_existing_window_and_lease(gpu_env):
    gpu, _, clock, running = gpu_env
    original = grant(gpu)
    lease = claim(gpu, running())
    gpu.release(lease["lease_id"], "worker-a", compute_stopped=True)
    # Reproduce the already-running database schema from before this addition.
    with gpu.queue.connection() as db:
        db.execute("DROP TABLE gpu_window_revocations")
    reopened = GPUCoordinator(gpu.db_path, clock=lambda: clock[0])
    assert reopened.get_window("window-1")["coordination_note"] == original["coordination_note"]
    assert reopened.get(lease["lease_id"])["status"] == "released"
    assert reopened.revoke_window("window-1", reason="migrated existing window")["revocation_reason"] == "migrated existing window"


def test_revoke_cli_preserves_audit_and_handles_unknown_window(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"
    gpu = GPUCoordinator(db)
    grant(gpu)
    assert main(["revoke-window", "--db", str(db), "--window-id", "window-1", "--reason", "completed CPU protocol test"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["revocation_reason"] == "completed CPU protocol test"
    assert result["revoked_at"] is not None
    assert main(["revoke-window", "--db", str(db), "--window-id", "absent", "--reason", "test"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
