"""Storage regression tests: native queue liveness and owner write boundaries."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import pytest

from packages.runtime.queue import Queue
from packages.runtime.storage import CapacityLedger, resolve_owner_path, resolve_relative_path


@pytest.fixture
def capacity(tmp_path):
    root = tmp_path / "video"
    (root / "platform").mkdir(parents=True)
    path = tmp_path / "queue.sqlite3"
    ledger = CapacityLedger(path, root, quotas={"platform": 100})
    return ledger, Queue(path), root


def test_slow_capacity_measurement_does_not_block_queue_heartbeat(capacity, monkeypatch):
    ledger, queue, _ = capacity
    job = queue.enqueue("probe", {})
    queue.claim("worker-live", lease_seconds=60)
    scanning, resume = threading.Event(), threading.Event()
    original = ledger._measure_owners

    def slow_scan(strict_owner=None):
        scanning.set()
        assert resume.wait(timeout=5)
        return original(strict_owner=strict_owner)

    monkeypatch.setattr(ledger, "_measure_owners", slow_scan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservation = pool.submit(ledger.reserve, "platform", 10)
        assert scanning.wait(timeout=2)
        heartbeat = pool.submit(queue.heartbeat, job["job_id"], "worker-live", 60)
        try:
            assert heartbeat.result(timeout=1) is True
        finally:
            resume.set()
        assert reservation.result(timeout=2)


def test_release_cannot_drop_reservation_during_measurement(capacity, monkeypatch):
    ledger, queue, _ = capacity
    prior = ledger.reserve("platform", 60)
    scanning, resume = threading.Event(), threading.Event()
    original = ledger._measure_owners

    def slow_scan(strict_owner=None):
        scanning.set()
        assert resume.wait(timeout=5)
        return original(strict_owner=strict_owner)

    monkeypatch.setattr(ledger, "_measure_owners", slow_scan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(ledger.reserve, "platform", 50)
        assert scanning.wait(timeout=2)
        release = pool.submit(ledger.release, prior)
        try:
            with pytest.raises(TimeoutError):
                release.result(timeout=0.1)
            with queue.connection() as db:
                assert db.execute("SELECT released_at FROM reservations WHERE reservation_id=?", (prior,)).fetchone()[0] is None
        finally:
            resume.set()
        with pytest.raises(ValueError, match="owner quota exceeded"):
            pending.result(timeout=2)
        release.result(timeout=2)


def test_two_independent_ledgers_cannot_overreserve(capacity):
    ledger, _, root = capacity
    other = CapacityLedger(ledger.queue.db_path, root, quotas={"platform": 100})

    def reserve(manager):
        try:
            return manager.reserve("platform", 60)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, (ledger, other)))
    assert sum(result is not None for result in results) == 1
    assert ledger.usage()["platform"]["reserved_bytes"] == 60


def junction_or_symlink(target, link):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_cross_owner_alias_can_be_read_but_never_used_for_platform_writes(tmp_path):
    root = tmp_path / "video"
    (root / "platform").mkdir(parents=True)
    target = root / "data" / "link-target"
    target.mkdir(parents=True)
    alias = root / "platform" / "jobs"
    junction_or_symlink(target, alias)
    assert resolve_relative_path(root, "platform/jobs/request.json") == target / "request.json"
    with pytest.raises(ValueError, match="symlink/junction"):
        resolve_owner_path(root, "platform/jobs/request.json", "platform")
    assert not (target / "request.json").exists()


def test_even_same_owner_write_aliases_are_rejected(tmp_path):
    root = tmp_path / "video"
    target = root / "platform" / "real"
    target.mkdir(parents=True)
    junction_or_symlink(target, root / "platform" / "alias")
    with pytest.raises(ValueError, match="symlink/junction"):
        resolve_owner_path(root, "platform/alias/new.json", "platform")


def test_owner_directory_itself_cannot_be_junction(tmp_path):
    root = tmp_path / "video"
    target = root / "data"
    target.mkdir(parents=True)
    junction_or_symlink(target, root / "platform")
    with pytest.raises(ValueError, match="symlink/junction"):
        resolve_owner_path(root, "platform/jobs/new.json", "platform")


def test_native_owner_paths_and_nested_runtime_owners(tmp_path):
    root = tmp_path / "video"
    root.mkdir()
    assert resolve_owner_path(root, "platform/jobs/new.json", "platform") == root / "platform" / "jobs" / "new.json"
    assert resolve_owner_path(root, "runtime/platform/env", "runtime/platform") == root / "runtime" / "platform" / "env"
    for relative, owner in (("data/raw.mp4", "platform"), ("platform-other/job.json", "platform"), ("runtime/models/cache", "runtime/platform")):
        with pytest.raises(ValueError, match="expected owner"):
            resolve_owner_path(root, relative, owner)
    with pytest.raises(FileNotFoundError):
        resolve_owner_path(root, "platform/absent.json", "platform", must_exist=True)


def test_storage_root_alias_is_rejected_for_writes(tmp_path):
    target = tmp_path / "physical-video"
    target.mkdir()
    alias = tmp_path / "video-alias"
    junction_or_symlink(target, alias)
    with pytest.raises(ValueError, match="storage root"):
        resolve_owner_path(alias, "platform/jobs/new.json", "platform")


def test_capacity_initialization_failure_finishes_worker_attempt(tmp_path, monkeypatch):
    from packages.runtime import worker
    from packages.runtime.queue import Queue
    root=tmp_path/'video';root.mkdir()
    queue=Queue(tmp_path/'runtime.sqlite3')
    job=queue.enqueue('probe',{'relative_path':'data/missing.mp4'})
    def denied(*args,**kwargs):
        raise ValueError('owner path contains junction')
    monkeypatch.setattr(worker,'CapacityLedger',denied)
    result=worker.run_once(queue,root,'owner-check')
    assert result['job_id']==job['job_id']
    assert result['status']=='failed'
    assert result['error']['message']=='owner path contains junction'
