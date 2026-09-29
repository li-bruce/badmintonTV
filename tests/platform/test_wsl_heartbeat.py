"""CPU-only heartbeat fault injection and native Windows file-sharing regression.

No WSL or model process starts in this file. Windows sharing tests hold only a
new pytest temporary file; production queues and GPU state are never opened.
"""

import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import stat
import threading
import time
from types import SimpleNamespace

import pytest

import packages.runtime.wsl_bridge as bridge


def io_error(winerror=None, err=errno.EACCES):
    error = PermissionError(err, "DO-NOT-LOG-token-123", "C:/sensitive-path/token-123.json")
    if winerror is not None:
        error.winerror = winerror
    return error


def diagnostics(text):
    values = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert all(set(value) == {"stage", "type", "errno", "winerror", "attempts"} for value in values)
    assert "sensitive-path" not in text and "token-123" not in text
    return values


def test_transient_sharing_replace_reuses_complete_temp_and_recovers(tmp_path, monkeypatch, capsys):
    path = tmp_path / "heartbeat.json"
    path.write_text('{"old":true}', encoding="utf-8")
    original = bridge.os.replace
    observed = []
    def busy_twice(source, destination):
        observed.append(Path(source))
        assert json.loads(Path(source).read_text(encoding="utf-8")) == {"tick": 2, "token": "token-123"}
        if len(observed) < 3:
            assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
            raise io_error(32 if len(observed) == 1 else 33)
        return original(source, destination)
    monkeypatch.setattr(bridge.os, "replace", busy_twice)
    bridge._atomic_json(path, {"tick": 2, "token": "token-123"}, heartbeat=True)
    assert len(set(observed)) == 1 and len(observed) == 3
    assert json.loads(path.read_text(encoding="utf-8"))["tick"] == 2
    assert list(tmp_path.glob("*.tmp")) == []
    records = diagnostics(capsys.readouterr().err)
    assert [r["stage"] for r in records] == ["heartbeat.replace.retry", "heartbeat.replace.retry", "heartbeat.replace.recovered"]
    assert records[-1]["attempts"] == 3


@pytest.mark.parametrize("winerror", [None, 5, 112, 3])
def test_other_permissions_and_io_errors_fail_immediately_without_retry(tmp_path, monkeypatch, capsys, winerror):
    calls = []
    def deny(*args):
        calls.append(1)
        raise io_error(winerror)
    monkeypatch.setattr(bridge.os, "replace", deny)
    with pytest.raises(bridge.HeartbeatWriteError) as caught:
        bridge._atomic_json(tmp_path / "heartbeat.json", {"token": "token-123"}, heartbeat=True)
    assert len(calls) == 1
    assert caught.value.diagnostic["stage"] == "heartbeat.replace.failed"
    assert caught.value.diagnostic["winerror"] == winerror
    assert "token-123" not in str(caught.value) and "sensitive-path" not in str(caught.value)
    assert diagnostics(capsys.readouterr().err) == []


def test_sharing_error_outside_replace_is_not_retried(tmp_path, monkeypatch):
    calls = []
    def broken_fsync(*args):
        calls.append(1)
        raise io_error(32)
    monkeypatch.setattr(bridge.os, "fsync", broken_fsync)
    with pytest.raises(bridge.HeartbeatWriteError) as caught:
        bridge._atomic_json(tmp_path / "heartbeat.json", {}, heartbeat=True)
    assert calls == [1]
    assert caught.value.diagnostic["stage"] == "heartbeat.fsync_temp.failed"


def test_access_denied_requires_positive_sharing_probe_to_retry(tmp_path, monkeypatch, capsys):
    original = bridge.os.replace
    calls = []
    monkeypatch.setattr(bridge, "_target_has_delete_sharing_conflict", lambda path: True)
    def confirmed_busy_once(source, destination):
        calls.append(1)
        if len(calls) == 1:
            raise io_error(5)
        return original(source, destination)
    monkeypatch.setattr(bridge.os, "replace", confirmed_busy_once)
    bridge._atomic_json(tmp_path / "heartbeat.json", {"tick": 1}, heartbeat=True)
    assert calls == [1, 1]
    assert diagnostics(capsys.readouterr().err)[-1]["stage"] == "heartbeat.replace.recovered"


def test_persistent_sharing_error_exhausts_subsecond_budget(tmp_path, monkeypatch, capsys):
    clock = [0.0]
    monkeypatch.setattr(bridge, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda delay: clock.__setitem__(0, clock[0] + delay)))
    def busy(*args):
        raise io_error(32)
    monkeypatch.setattr(bridge.os, "replace", busy)
    with pytest.raises(bridge.HeartbeatWriteError) as caught:
        bridge._atomic_json(tmp_path / "heartbeat.json", {}, heartbeat=True)
    assert clock[0] == pytest.approx(bridge.HEARTBEAT_REPLACE_RETRY_SECONDS)
    assert clock[0] < 1
    assert 1 < caught.value.diagnostic["attempts"] <= 15
    assert caught.value.diagnostic["winerror"] == 32
    assert not (tmp_path / "heartbeat.json").exists()
    assert list(tmp_path.glob("*.tmp")) == []
    diagnostics(capsys.readouterr().err)


def test_nonheartbeat_atomic_write_retains_immediate_error_semantics(tmp_path, monkeypatch):
    calls = []
    def busy(*args):
        calls.append(1)
        raise io_error(32)
    monkeypatch.setattr(bridge.os, "replace", busy)
    with pytest.raises(PermissionError):
        bridge._atomic_json(tmp_path / "result.json", {})
    assert calls == [1]


def test_temp_write_time_consumes_the_same_retry_budget(tmp_path, monkeypatch, capsys):
    clock = [0.0]
    monkeypatch.setattr(bridge, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda delay: clock.__setitem__(0, clock[0] + delay)))
    monkeypatch.setattr(bridge.os, "fsync", lambda fd: clock.__setitem__(0, 0.65))
    monkeypatch.setattr(bridge.os, "replace", lambda *args: (_ for _ in ()).throw(io_error(32)))
    with pytest.raises(bridge.HeartbeatWriteError):
        bridge._atomic_json(tmp_path / "heartbeat.json", {}, heartbeat=True)
    assert clock[0] == pytest.approx(0.7)
    diagnostics(capsys.readouterr().err)


def test_cleanup_failure_does_not_mask_original_stage(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "HEARTBEAT_REPLACE_RETRY_SECONDS", 0)
    monkeypatch.setattr(bridge.os, "replace", lambda *args: (_ for _ in ()).throw(io_error(32)))
    original_unlink = Path.unlink
    def bad_cleanup(path, *args, **kwargs):
        if path.name.endswith(".tmp"):
            raise io_error(5)
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(Path, "unlink", bad_cleanup)
        with pytest.raises(bridge.HeartbeatWriteError) as caught:
            bridge._atomic_json(tmp_path / "heartbeat.json", {}, heartbeat=True)
    assert caught.value.diagnostic["stage"] == "heartbeat.replace.failed"
    assert caught.value.diagnostic["winerror"] == 32
    assert diagnostics(capsys.readouterr().err)[-1]["stage"] == "heartbeat.cleanup_temp.failed"


@pytest.fixture
def windows_run_fixture(tmp_path, monkeypatch):
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps({"schema_version": "1.0", "job_id": "job-heartbeat-test", "attempt_id": "attempt-1"}), encoding="utf-8")
    args = argparse.Namespace(request=str(request), result=str(result), heartbeat_timeout=2,
                              distribution="Ubuntu", env_prefix="/mnt/d/video/runtime/models/env", repo="C:/fixture")
    monkeypatch.setattr(bridge, "exchange_paths", lambda *args: ("/controlled/request.json", "/controlled/result.json", "job-heartbeat-test", "attempt-1"))
    monkeypatch.setattr(bridge, "build_wsl_command", lambda *args: ["NO-PROCESS-EXECUTED"])
    processes = []
    class FakeProcess:
        returncode = None
        def __init__(self, *args, **kwargs):
            processes.append(self)
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            assert (tmp_path / "bridge-cancel.json").exists()
            self.returncode = 130
            return self.returncode
        def kill(self):
            pytest.fail("fixture must observe cancellation before kill fallback")
    monkeypatch.setattr(bridge.subprocess, "Popen", FakeProcess)
    return args, tmp_path, processes


def test_repeated_heartbeat_failure_cancels_running_launcher_and_fails_closed(windows_run_fixture, monkeypatch, capsys):
    args, directory, processes = windows_run_fixture
    original = bridge.os.replace
    monkeypatch.setattr(bridge, "HEARTBEAT_REPLACE_RETRY_SECONDS", 0.04)
    writes = []
    def broken_after_initial(source, destination):
        if Path(destination).name == "bridge-heartbeat.json":
            writes.append(1)
            if len(writes) > 1:
                raise io_error(32)
        return original(source, destination)
    monkeypatch.setattr(bridge.os, "replace", broken_after_initial)
    with pytest.raises(bridge.HeartbeatWriteError) as caught:
        bridge.run_windows(args)
    assert caught.value.diagnostic["stage"] == "heartbeat.replace.failed"
    assert len(processes) == 1 and processes[0].returncode == 130
    cancel = json.loads((directory / "bridge-cancel.json").read_text(encoding="utf-8"))
    assert cancel["cancel_requested"] is True
    assert (cancel["job_id"], cancel["attempt_id"]) == ("job-heartbeat-test", "attempt-1")
    assert not (directory / "bridge.done.json").exists(), "running Linux guardian owns stop proof"
    diagnostics(capsys.readouterr().err)


def test_initial_permanent_failure_never_launches_and_main_logs_safe_detail(windows_run_fixture, monkeypatch, capsys):
    args, directory, processes = windows_run_fixture
    original = bridge.os.replace
    def initial_denied(source, destination):
        if Path(destination).name == "bridge-heartbeat.json":
            raise io_error(5)
        return original(source, destination)
    monkeypatch.setattr(bridge.os, "replace", initial_denied)
    code = bridge.main(["--env-prefix", args.env_prefix, "--repo", args.repo, "run", "--request", args.request, "--result", args.result])
    assert code == 1 and processes == []
    done = json.loads((directory / "bridge.done.json").read_text(encoding="utf-8"))
    assert done["compute_stopped"] is True and done["reason"] == "launcher_not_started"
    captured = capsys.readouterr()
    assert captured.out == ""
    info = diagnostics(captured.err)
    assert info == [{"stage": "heartbeat.replace.failed", "type": "PermissionError", "errno": errno.EACCES, "winerror": 5, "attempts": 1}]
    assert "Traceback" not in captured.err


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows sharing modes")
def test_native_windows_deny_delete_reader_recovers_before_heartbeat_budget(tmp_path, capsys):
    path = tmp_path / "heartbeat.json"
    path.write_text('{"tick":0}', encoding="utf-8")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    # Allow concurrent reads/writes but deliberately deny FILE_SHARE_DELETE.
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x1 | 0x2, None, 3, 0, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    released = threading.Event()
    def release_reader():
        time.sleep(0.12)
        assert kernel.CloseHandle(handle)
        released.set()
    reader = threading.Thread(target=release_reader)
    reader.start()
    start = time.monotonic()
    try:
        bridge._atomic_json(path, {"tick": 1}, heartbeat=True)
    finally:
        reader.join(timeout=1)
        if not released.is_set():
            kernel.CloseHandle(handle)
    elapsed = time.monotonic() - start
    assert json.loads(path.read_text(encoding="utf-8")) == {"tick": 1}
    records = diagnostics(capsys.readouterr().err)
    assert any(row["stage"] == "heartbeat.replace.retry" and row["winerror"] in (5, 32, 33) for row in records)
    assert records[-1]["stage"] == "heartbeat.replace.recovered"
    assert elapsed < 1
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows read-only attributes")
def test_native_windows_readonly_destination_is_not_treated_as_sharing(tmp_path, capsys):
    path = tmp_path / "heartbeat.json"
    path.write_text('{"tick":0}', encoding="utf-8")
    path.chmod(stat.S_IREAD)
    try:
        with pytest.raises(bridge.HeartbeatWriteError) as caught:
            bridge._atomic_json(path, {"tick": 1}, heartbeat=True)
        assert caught.value.diagnostic["attempts"] == 1
        assert caught.value.diagnostic["winerror"] == 5
        assert json.loads(path.read_text(encoding="utf-8")) == {"tick": 0}
        assert diagnostics(capsys.readouterr().err) == []
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows sharing modes")
def test_native_windows_persistent_reader_fails_within_budget_preserving_old_tick(tmp_path, capsys):
    path = tmp_path / "heartbeat.json"
    path.write_text('{"tick":0}', encoding="utf-8")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x1 | 0x2, None, 3, 0, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    start = time.monotonic()
    try:
        with pytest.raises(bridge.HeartbeatWriteError) as caught:
            bridge._atomic_json(path, {"tick": 1}, heartbeat=True)
        elapsed = time.monotonic() - start
        assert 1 < caught.value.diagnostic["attempts"] <= 15
        assert 0.65 <= elapsed < 1
        assert json.loads(path.read_text(encoding="utf-8")) == {"tick": 0}
        assert diagnostics(capsys.readouterr().err)
    finally:
        kernel.CloseHandle(handle)


def heartbeat_publisher(tmp_path):
    publisher = bridge._HeartbeatPublisher(tmp_path / "bridge-heartbeat.json", {
        "schema_version": "1.0", "job_id": "job-test", "attempt_id": "attempt-1", "token": "token-123"})
    publisher.publish(-1)
    return publisher


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows DELETE access probes")
def test_prior_publisher_win5_with_available_delete_access_recovers(tmp_path, monkeypatch, capsys):
    publisher = heartbeat_publisher(tmp_path)
    original = bridge.os.replace
    calls = []
    def transient(source, destination):
        calls.append(1)
        if len(calls) == 1:
            raise io_error(5)
        return original(source, destination)
    monkeypatch.setattr(bridge.os, "replace", transient)
    publisher.publish(0)
    assert len(calls) == 2
    assert json.loads(publisher.path.read_text())["tick"] == 0
    records = diagnostics(capsys.readouterr().err)
    assert records[0]["stage"] == "heartbeat.replace.delete_probe.allowed"
    assert records[0]["winerror"] == 0
    assert records[-1]["stage"] == "heartbeat.replace.recovered"


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows DELETE access probes")
def test_prior_publisher_persistent_win5_fails_at_existing_deadline(tmp_path, monkeypatch, capsys):
    publisher = heartbeat_publisher(tmp_path)
    clock = [0.0]
    monkeypatch.setattr(bridge, "time", SimpleNamespace(time=lambda: 1, monotonic=lambda: clock[0],
                       sleep=lambda delay: clock.__setitem__(0, clock[0] + delay)))
    monkeypatch.setattr(bridge.os, "replace", lambda *args: (_ for _ in ()).throw(io_error(5)))
    with pytest.raises(bridge.HeartbeatWriteError) as caught:
        publisher.publish(0)
    assert clock[0] == pytest.approx(0.7)
    assert 1 < caught.value.diagnostic["attempts"] <= 15
    assert caught.value.diagnostic["winerror"] == 5
    assert json.loads(publisher.path.read_text())["tick"] == -1
    assert list(tmp_path.glob("*.tmp")) == []
    diagnostics(capsys.readouterr().err)


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows file identities")
@pytest.mark.parametrize("change", ["target_replaced", "target_readonly", "source_readonly", "delete_denied", "parent_changed"])
def test_prior_publisher_win5_rejects_invalid_proof_and_permissions(tmp_path, monkeypatch, capsys, change):
    publisher = heartbeat_publisher(tmp_path)
    if change == "target_replaced":
        replacement = tmp_path / "different.json"
        replacement.write_text(publisher.path.read_text(), encoding="utf-8")
        replacement.replace(publisher.path)
    if change == "target_readonly":
        publisher.path.chmod(stat.S_IREAD)
    if change == "delete_denied":
        monkeypatch.setattr(bridge, "_delete_access_error", lambda path: 5)
    if change == "parent_changed":
        monkeypatch.setattr(bridge, "_directory_identity", lambda path: (0, 0))
    calls = []
    def denied(source, destination):
        calls.append(1)
        if change == "source_readonly":
            Path(source).chmod(stat.S_IREAD)
        raise io_error(5)
    monkeypatch.setattr(bridge.os, "replace", denied)
    try:
        with pytest.raises(bridge.HeartbeatWriteError) as caught:
            publisher.publish(0)
        assert len(calls) == caught.value.diagnostic["attempts"] == 1
        assert caught.value.diagnostic["stage"] == "heartbeat.replace.failed"
        assert json.loads(publisher.path.read_text())["tick"] == -1
        records = diagnostics(capsys.readouterr().err)
        assert not any(row["stage"] == "heartbeat.replace.retry" for row in records)
        if change == "delete_denied":
            assert records[0]["stage"] == "heartbeat.replace.delete_probe.denied"
            assert records[0]["winerror"] == 5
    finally:
        for path in tmp_path.iterdir():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows sharing modes")
def test_native_win5_reader_released_between_replace_and_probe_recovers(tmp_path, monkeypatch, capsys):
    publisher = heartbeat_publisher(tmp_path)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(publisher.path), 0x80000000, 0x1 | 0x2, None, 3, 0, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    original = bridge.os.replace
    errors = []
    def real_conflict_then_release(source, destination):
        nonlocal handle
        try:
            return original(source, destination)
        except OSError as exc:
            errors.append(exc.winerror)
            if handle is not None:
                assert kernel.CloseHandle(handle)
                handle = None
            raise
    monkeypatch.setattr(bridge.os, "replace", real_conflict_then_release)
    start = time.monotonic()
    try:
        publisher.publish(0)
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
    assert errors == [5], "the real Windows rename, not injection, must reproduce error 5"
    assert time.monotonic() - start < 0.7
    records = diagnostics(capsys.readouterr().err)
    assert records[0]["stage"] == "heartbeat.replace.delete_probe.allowed"
    assert records[0]["winerror"] == 0
    assert records[-1]["stage"] == "heartbeat.replace.recovered"
    assert json.loads(publisher.path.read_text())["tick"] == 0


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows ACLs")
def test_native_delete_acl_denial_is_not_retried_for_prior_publisher(tmp_path, monkeypatch, capsys):
    publisher = heartbeat_publisher(tmp_path)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.GetFileSecurityW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    advapi.SetFileSecurityW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_void_p]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    size = ctypes.c_ulong()
    advapi.GetFileSecurityW(str(publisher.path), 4, None, 0, ctypes.byref(size))
    assert size.value > 0
    saved = ctypes.create_string_buffer(size.value)
    assert advapi.GetFileSecurityW(str(publisher.path), 4, saved, size.value, ctypes.byref(size))
    advapi.GetFileSecurityW(str(tmp_path), 4, None, 0, ctypes.byref(size))
    saved_parent = ctypes.create_string_buffer(size.value)
    assert advapi.GetFileSecurityW(str(tmp_path), 4, saved_parent, size.value, ctypes.byref(size))
    denied = ctypes.c_void_p()
    denied_parent = ctypes.c_void_p()
    # Only this new temporary file: deny Everyone DELETE, retain other access so
    # the test can restore its original DACL even after the denied probe.
    assert advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        "D:(D;;SD;;;WD)(A;;FA;;;WD)", 1, ctypes.byref(denied), None)
    # Windows can also grant DELETE through the parent's DELETE_CHILD right.
    # Deny that fallback only on this dedicated pytest directory.
    assert advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        "D:(D;;0x00000040;;;WD)(A;;FA;;;WD)", 1, ctypes.byref(denied_parent), None)
    try:
        assert advapi.SetFileSecurityW(str(tmp_path), 4, denied_parent)
        assert advapi.SetFileSecurityW(str(publisher.path), 4, denied)
        assert bridge._delete_access_error(publisher.path) == 5
        # ACL changes alter ctime. Retain the current identity only for this test
        # so it reaches the actual DELETE probe, not the earlier identity guard.
        publisher.prior = (publisher.prior[0], bridge._regular_identity(publisher.path), publisher.prior[2])
        calls = []
        def win5(source, destination):
            calls.append(1)
            raise io_error(5)
        monkeypatch.setattr(bridge.os, "replace", win5)
        with pytest.raises(bridge.HeartbeatWriteError) as caught:
            publisher.publish(0)
        assert calls == [1]
        assert caught.value.diagnostic["attempts"] == 1
        records = diagnostics(capsys.readouterr().err)
        assert records[0]["stage"] == "heartbeat.replace.delete_probe.denied"
        assert records[0]["winerror"] == 5
    finally:
        restored_file = advapi.SetFileSecurityW(str(publisher.path), 4, saved)
        restored_parent = advapi.SetFileSecurityW(str(tmp_path), 4, saved_parent)
        kernel.LocalFree(denied)
        kernel.LocalFree(denied_parent)
        assert restored_file and restored_parent
    assert bridge._delete_access_error(publisher.path) == 0
