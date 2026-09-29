"""Internal worker hash proofs; synthetic bytes and simulated media probing."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.runtime import worker
from packages.runtime import Queue


IDENTITY_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")


@pytest.fixture
def source_proof(tmp_path, monkeypatch):
    source = tmp_path / "data/synthetic.bin"
    source.parent.mkdir()
    raw = b"synthetic source hash identity proof"
    source.write_bytes(raw)
    asset = {"asset_id": "identity-source", "relative_path": "data/synthetic.bin",
             "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw), "duration_ms": 1000,
             "width": 16, "height": 16, "fps_num": 1, "fps_den": 1, "time_base": "1/1000",
             "match_id": "synthetic-match", "source_type": "synthetic"}
    exchange = tmp_path / "platform/jobs/identity-job/attempt-1"
    exchange.mkdir(parents=True)
    monkeypatch.setenv("BTV_DB_PATH", str(tmp_path / "missing-business.sqlite3"))
    monkeypatch.setattr(worker, "_binary", lambda *args: "synthetic-no-subprocess")

    def execute(argv, stage, **kwargs):
        if stage == "ffprobe":
            return 0, json.dumps({"streams": [{"codec_type": "video", "width": 16, "height": 16,
                        "duration": "1", "avg_frame_rate": "1/1", "time_base": "1/1000"}], "format": {}}), ""
        assert stage == "ffmpeg"
        Path(argv[-1]).write_bytes(b"synthetic thumbnail")
        return 0, "", ""

    context = SimpleNamespace(storage_root=tmp_path, queue=Queue(tmp_path / "runtime.sqlite3"),
        job={"job_id": "identity-job", "attempt": 1, "operation": "probe", "payload": {
            "relative_path": asset["relative_path"], "asset_metadata": {"asset_id": asset["asset_id"], "source_type": "synthetic"}}},
        check=lambda: None, log=lambda *args, **kwargs: None, execute=execute)
    return source, asset, context, exchange


def test_probe_internal_result_carries_hash_time_identity_outside_asset(source_proof):
    source, asset, context, exchange = source_proof
    before = source.stat()
    result = worker.probe(context, exchange)
    assert result["source_identities"] == {asset["asset_id"]: [getattr(before, name) for name in IDENTITY_FIELDS]}
    assert result["asset"]["sha256"] == asset["sha256"]
    assert "source_identities" not in result["asset"]
    assert "source_identities" not in result["asset"]["probe"]


@pytest.mark.parametrize("handler", ["probe", "verify_manifest"])
def test_hash_rejects_changed_ctime_even_when_other_identity_fields_match(source_proof, monkeypatch, handler):
    source, asset, context, exchange = source_proof
    if handler == "verify_manifest":
        context.job.update(operation=handler, payload={"assets": [asset], "library_id": "synthetic-library"})
    original_fd, original_path, calls = os.fstat, Path.stat, []
    def count_reads(fd):
        actual = original_fd(fd)
        calls.append(fd)
        return actual
    def changed_after_read(path, *args, **kwargs):
        actual = original_path(path, *args, **kwargs)
        if path == source and len(calls) == 2:
            return SimpleNamespace(**{name: getattr(actual, name) + (1 if name == "st_ctime_ns" else 0) for name in IDENTITY_FIELDS})
        return actual
    monkeypatch.setattr(os, "fstat", count_reads)
    monkeypatch.setattr(Path, "stat", changed_after_read)
    with pytest.raises(ValueError, match="changed"):
        getattr(worker, handler)(context, exchange)
    assert len(calls) == 2


def test_probe_does_not_refresh_proof_when_source_changes_after_hash(source_proof):
    source, asset, context, exchange = source_proof
    original = context.execute
    def mutate_source(argv, stage, **kwargs):
        result = original(argv, stage, **kwargs)
        if stage == "ffmpeg":
            before = source.stat()
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        return result
    context.execute = mutate_source
    with pytest.raises(ValueError, match="source changed after hashing"):
        worker.probe(context, exchange)
