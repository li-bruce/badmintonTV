"""R-02a assertions. Real media cases are opt-in and keep evidence under D:/video."""

import hashlib
import io
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from packages.runtime import Queue
from packages.runtime.media_proxy import (
    MAX_PAGE, MAX_PROXY_BYTES, _connect, _metadata, _options, _select_frames,
    _set_metadata, create_proxy, estimate_peak_bytes, exact_frame,
    read_frame_map, read_source_frames, _stream_index, _output,
)
from packages.runtime.storage import CapacityLedger, resolve_owner_path
from packages.runtime.worker import JobCancelled, WorkerContext
from docs.platform.prepare_preview_validation import refresh_fixture_asset


def snapshot(**overrides):
    return {"asset_id": "asset-test", "relative_path": "data/source.mp4", "duration_ms": 1000,
            "size_bytes": 100, "width": 1920, "height": 1080, "sha256": "a" * 64, **overrides}


def indexed(tmp_path, pts, time_base="1/1000", final_duration=20):
    path = tmp_path / "frames.sqlite3"
    with _connect(path) as db:
        db.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE source_frames(source_frame_index INTEGER PRIMARY KEY,source_pts INTEGER NOT NULL,
                source_pts_ms REAL NOT NULL,source_end_ms REAL NOT NULL,key_frame INTEGER NOT NULL);
            CREATE TABLE proxy_frames(proxy_frame_index INTEGER PRIMARY KEY,proxy_pts_ms REAL NOT NULL,
                source_frame_index INTEGER NOT NULL,source_pts INTEGER NOT NULL,source_pts_ms REAL NOT NULL,
                coverage_start_ms REAL NOT NULL,coverage_end_ms REAL NOT NULL);
        """)
        for n, pts_ms in enumerate(pts):
            db.execute("INSERT INTO source_frames VALUES(?,?,?,?,?)", (n, pts_ms, pts_ms, pts[n + 1] if n + 1 < len(pts) else pts_ms + final_duration, n == 0))
        _set_metadata(db, {"source_end_ms": pts[-1] + final_duration, "source_time_base": time_base, "source_frame_count": len(pts)})
    return path


@pytest.mark.parametrize("values", [
    {"end_ms": 120_001, "asset": snapshot(duration_ms=200_000)},
    {"max_height": 2160}, {"max_fps": 60}, {"max_fps": True}, {"start_ms": -1},
    {"start_ms": 1000}, {"end_ms": 0}, {"asset": snapshot(size_bytes=20_000_000_001)},
    {"asset": snapshot(width=7680, height=4320)}, {"asset": snapshot(duration_ms=14_400_001)},
])
def test_limits_reject_before_any_media_write(values):
    with pytest.raises(ValueError):
        estimate_peak_bytes({"asset": snapshot(), **values})


def test_extra_reservation_includes_index_journal_muxer_and_thumbnail_peak():
    assert estimate_peak_bytes({"asset": snapshot()}) == 880_000_000
    assert estimate_peak_bytes({"asset": snapshot()}, "exact_frame") == 72_000_000


def test_vfr_mapping_preserves_each_source_pts_and_full_interval_coverage(tmp_path):
    path = indexed(tmp_path, [0, 16, 34, 49, 71, 105, 171], final_duration=60)
    first, stop, start, end, count = _select_frames(path, 20, 200, 30)
    assert (first, stop, start, end) == (1, 7, 16, 200)
    frames = read_frame_map(path)["frames"]
    assert [item["source_frame_index"] for item in frames] == [1, 4, 5, 6]
    assert len(frames) == count == 4
    assert frames[0]["coverage_start_ms"] == 16
    assert frames[-1]["coverage_end_ms"] == 200
    assert all(left["coverage_end_ms"] == right["coverage_start_ms"] for left, right in zip(frames, frames[1:]))
    assert len(read_source_frames(path)["source_frames"]) == 7
    assert read_source_frames(path, at_ms=50, limit=1)["source_frames"][0]["source_frame_index"] == 3
    assert read_frame_map(path, at_ms=60, limit=1)["frames"][0]["source_pts_ms"] == 71
    assert read_frame_map(path, offset_frame=999)["frames"] == []


def test_passthrough_vfr_map_has_identical_pts_deltas(tmp_path):
    path = indexed(tmp_path, [0, 13, 33, 80, 83, 200], final_duration=50)
    _select_frames(path, 0, 250, None)
    frames = read_frame_map(path)["frames"]
    assert [frame["proxy_pts_ms"] for frame in frames] == [0, 13, 33, 80, 83, 200]


def test_paginated_index_connection_closes_on_exit(tmp_path):
    path = indexed(tmp_path, [0, 20], final_duration=20)
    with _connect(path, True) as db:
        assert db.execute("SELECT COUNT(*) FROM source_frames").fetchone()[0] == 2
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        db.execute("SELECT 1")


@pytest.mark.parametrize("kwargs", [{"limit": MAX_PAGE + 1}, {"limit": 0}, {"offset_frame": -1}, {"at_ms": float("nan")}, {"at_ms": -1}])
def test_index_queries_are_bounded(tmp_path, kwargs):
    for reader in (read_frame_map, read_source_frames):
        with pytest.raises(ValueError):
            reader(tmp_path / "not-opened.sqlite3", **kwargs)


def test_cancel_before_source_read_does_not_start_decoder(tmp_path, monkeypatch):
    # Test only the context boundary here; real child-tree cancellation belongs
    # to WorkerContext tests and is not represented as real video evidence.
    root = tmp_path
    (root / "data").mkdir()
    source = root / "data/source.mp4"
    source.write_bytes(b"original")
    asset = snapshot(size_bytes=8, sha256=hashlib.sha256(b"original").hexdigest())
    queue = Queue(root / "queue.sqlite3")
    job = queue.enqueue("media_proxy", {"asset": asset})
    claimed = queue.claim("test", lease_seconds=120)
    queue.request_cancel(job["job_id"])
    context = WorkerContext(queue, claimed, "test", root, 120)
    with pytest.raises(JobCancelled):
        create_proxy(context, root / "platform/jobs/test/attempt-1")
    assert not (root / "platform/jobs").exists()


def test_source_hash_mismatch_never_encodes(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/source.mp4").write_bytes(b"original")
    queue = Queue(tmp_path / "queue.sqlite3")
    queue.enqueue("media_proxy", {"asset": snapshot(size_bytes=8)})
    context = WorkerContext(queue, queue.claim("test", lease_seconds=120), "test", tmp_path, 120)
    with pytest.raises(ValueError, match="SHA-256"):
        create_proxy(context, tmp_path / "platform/jobs/test/attempt-1")


def test_active_cancellation_releases_extra_reservation_and_preserves_cancel_request(tmp_path, monkeypatch):
    monkeypatch.setattr("packages.runtime.media_proxy._binary", lambda name: name)
    (tmp_path / "data").mkdir()
    data = b"original"
    (tmp_path / "data/source.mp4").write_bytes(data)
    queue = Queue(tmp_path / "queue.sqlite3")
    job = queue.enqueue("media_proxy", {"asset": snapshot(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())})
    context = WorkerContext(queue, queue.claim("test", lease_seconds=120), "test", tmp_path, 120)
    def cancel_at_decoder(*args, **kwargs):
        queue.request_cancel(job["job_id"])
        context.check()
        pytest.fail("cancelled context must raise before decoder continues")
    context.execute = cancel_at_decoder
    with pytest.raises(JobCancelled):
        create_proxy(context, tmp_path / "platform/jobs/test/attempt-1")
    with queue.connection() as db:
        rows = db.execute("SELECT released_at FROM reservations").fetchall()
    assert len(rows) == 1 and rows[0][0] is not None
    assert queue.get(job["job_id"])["cancel_requested"]


@pytest.mark.parametrize("pts,expected_error", [([900, 920, 980], None), ([900, 900], "strictly increasing"), ([900, 920, 930, 940], "frame count")])
def test_stream_index_uses_actual_pts_and_bounded_batches(tmp_path, monkeypatch, pts, expected_error):
    import packages.runtime.media_proxy as module
    (tmp_path / "data").mkdir()
    (tmp_path / "data/source.mp4").write_bytes(b"source")
    (tmp_path / "platform").mkdir()
    class FakeProbe:
        def __init__(self):
            self.stdout = io.BytesIO(b"".join(f"pts={p}|duration=20|key_frame=0|width=32|height=32\n".encode() for p in pts))
        def wait(self):
            return 0
        def poll(self):
            return 0
    monkeypatch.setattr(module, "_binary", lambda name: name)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: FakeProbe())
    monkeypatch.setattr(module, "MAX_SOURCE_FRAMES", 3)
    config = {"storage_root": str(tmp_path), "source_relative_path": "data/source.mp4", "index_relative_path": "platform/index.sqlite3",
              "time_base": "1/1000", "duration_ms": 100, "job_id": "test"}
    if expected_error:
        with pytest.raises(ValueError, match=expected_error):
            _stream_index(config)
    else:
        _stream_index(config)
        frames = read_source_frames(tmp_path / "platform/index.sqlite3")["source_frames"]
        assert [row["source_pts"] for row in frames] == pts
        assert [row["source_pts_ms"] for row in frames] == [0, 20, 80]
        assert frames[-1]["source_end_ms"] == 100


def test_window_frame_count_bound_rejects_excess_before_encode(tmp_path, monkeypatch):
    import packages.runtime.media_proxy as module
    path = indexed(tmp_path, list(range(10)), final_duration=1)
    monkeypatch.setattr(module, "MAX_WINDOW_FRAMES", 3)
    with pytest.raises(ValueError, match="window frame count"):
        _select_frames(path, 0, 10, None)


def test_media_job_rejects_training_even_for_research_preview(tmp_path):
    from packages.contracts import UsageScopeError
    queue = Queue(tmp_path / "queue.sqlite3")
    queue.enqueue("media_proxy", {"asset": snapshot(usage_scope="training_only"), "research_preview": True})
    context = WorkerContext(queue, queue.claim("test", lease_seconds=120), "test", tmp_path, 120)
    with pytest.raises(UsageScopeError):
        create_proxy(context, tmp_path / "platform/jobs/test/attempt-1")


def test_attempt_outputs_are_never_overwritten_and_stay_platform_owned(tmp_path):
    queue = Queue(tmp_path / "queue.sqlite3")
    queue.enqueue("media_proxy", {"asset": snapshot()})
    context = WorkerContext(queue, queue.claim("test", lease_seconds=120), "test", tmp_path, 120)
    output = _output(context, tmp_path / "platform/jobs/test/attempt-1", "preview.mp4")
    output.write_bytes(b"previous failed attempt remains reviewable")
    with pytest.raises(ValueError, match="already exists"):
        _output(context, output.parent, output.name)
    assert output.read_bytes() == b"previous failed attempt remains reviewable"
    with pytest.raises(ValueError, match="owner"):
        _output(context, tmp_path / "data/bad-output", "preview.mp4")
    assert _output(context, tmp_path / "platform/jobs/test/attempt-2", "preview.mp4") != output


REAL_ROOT = os.environ.get("BTV_MEDIA_REAL_TEST_ROOT")


def test_derivative_fixture_discards_parent_probe_and_uses_actual_rational_metadata(tmp_path, monkeypatch):
    media = tmp_path / 'platform/derived.mp4'
    media.parent.mkdir()
    media.write_bytes(b'explicit test bytes; ffprobe response below is a fixture')
    source = snapshot(relative_path='platform/derived.mp4', size_bytes=media.stat().st_size,
                      sha256=hashlib.sha256(media.read_bytes()).hexdigest(), fps_num=30, fps_den=1,
                      probe={'pts_index': {'frame_count': 139, 'relative_path': 'data/old.jsonl'},
                             'thumbnail_relative_path': 'data/old.jpg'},
                      provenance={'publisher_sha256': 'f'*64, 'test_derivative': 'derived_60_to_30',
                                  'source_asset_id': 'asset-parent', 'source_sha256': 'f'*64,
                                  'usage_scope': 'training_only'})
    before = json.loads(json.dumps(source))
    calls = []

    def probe(argv, timeout):
        calls.append(argv)
        assert timeout == 30 and argv[-1] == str(media.resolve())
        return json.dumps({'streams': [{'index': 0, 'codec_type': 'video', 'codec_name': 'h264',
                           'width': 1280, 'height': 720, 'avg_frame_rate': '60000/1001',
                           'r_frame_rate': '60/1', 'time_base': '1/60000', 'duration': '4.633333'}]})

    monkeypatch.setattr(subprocess, 'check_output', probe)
    actual = refresh_fixture_asset(source, tmp_path, 'fixed-ffprobe')
    assert len(calls) == 1 and source == before
    assert (actual['fps_num'], actual['fps_den'], actual['time_base']) == (60000, 1001, '1/60000')
    assert (actual['width'], actual['height'], actual['duration_ms']) == (1280, 720, 4633)
    assert 'pts_index' not in actual['probe'] and 'thumbnail_relative_path' not in actual['probe']
    assert actual['probe']['source_sha256'] == source['sha256']
    assert 'publisher_sha256' not in actual['provenance']
    assert actual['provenance']['source_sha256'] == 'f'*64
    assert actual['provenance']['usage_scope'] == 'training_only'


def test_fixture_bytes_changed_refuses_before_ffprobe(tmp_path, monkeypatch):
    media = tmp_path / 'source.mp4'
    media.write_bytes(b'changed')
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: pytest.fail('must refuse before ffprobe'))
    with pytest.raises(ValueError, match='preserved report'):
        refresh_fixture_asset(snapshot(relative_path=media.name), tmp_path, 'fixed-ffprobe')


def test_browser_fixture_setup_refuses_preserved_state_before_queue(tmp_path, monkeypatch):
    from docs.platform import prepare_preview_validation as setup
    state = tmp_path / 'platform/prior-evidence'
    state.mkdir(parents=True)
    (state / 'setup.json').write_text('preserved', encoding='utf-8')
    monkeypatch.setattr(setup, 'ROOT', tmp_path)
    monkeypatch.setattr(setup, 'Queue', lambda *a: pytest.fail('must not open an existing queue'))
    with pytest.raises(FileExistsError, match='never overwritten'):
        setup.main(['--state', 'platform/prior-evidence', '--evidence-root', 'platform'])
    assert (state / 'setup.json').read_text(encoding='utf-8') == 'preserved'


@pytest.mark.skipif(not REAL_ROOT, reason="opt-in CPU FFmpeg evidence; requires bounded D:/video/platform test directory")
@pytest.mark.parametrize("case", ["real_cfr", "derived_vfr", "derived_ffv1", "derived_60_to_30"])
def test_real_ffmpeg_proxy_and_original_frame(case):
    root = Path("D:/video")
    test_root = Path(REAL_ROOT).resolve()
    relative = test_root.relative_to(root.resolve()).as_posix()
    resolve_owner_path(root, relative, "platform")
    assert "test" in relative.lower()
    test_root.mkdir(parents=True, exist_ok=True)
    case_dir = test_root / case
    case_dir.mkdir(exist_ok=False)
    queue = Queue(case_dir / "test-runtime.sqlite3")
    ledger = CapacityLedger(queue.db_path, root)
    # Explicit reservation before derived inputs, including their temporary peaks.
    setup_reservation = ledger.reserve("platform", 256_000_000, job_id="media-test-input-" + case)
    asset = json.loads((root / "data/handoff/assets.v1.json").read_text(encoding="utf-8"))["assets"][0]
    asset = json.loads(json.dumps(asset))
    ffmpeg, ffprobe = os.environ["BTV_FFMPEG"], os.environ["BTV_FFPROBE"]
    source = root / asset["relative_path"]
    commands = []
    try:
        if case != "real_cfr":
            parent_asset_id, parent_sha256 = asset["asset_id"], asset["sha256"]
            derivative = case_dir / ("explicit-vfr-derivative.mkv" if case == "derived_vfr" else "ffv1-source.mkv" if case == "derived_ffv1" else "explicit-60fps-derivative.mp4")
            filters = "select='not(mod(n,3))+gt(t,2)*eq(mod(n,3),1)'" if case == "derived_vfr" else "fps=60" if case == "derived_60_to_30" else "null"
            argv = [ffmpeg, "-nostdin", "-v", "error", "-i", str(source), "-an", "-vf", filters, "-fps_mode", "vfr", "-threads", "2",
                    "-c:v", "libx264" if case == "derived_60_to_30" else "ffv1", "-fs", "200000000", "-n", str(derivative)]
            subprocess.run(argv, check=True, timeout=120)
            commands.append(argv)
            assert derivative.stat().st_size < 200_000_000
            with derivative.open('rb') as handle:
                derivative_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
            asset.update(asset_id="asset-media-test-" + case, relative_path=derivative.relative_to(root).as_posix(),
                         size_bytes=derivative.stat().st_size, sha256=derivative_hash)
            asset["provenance"] = {**asset.get("provenance", {}), "test_derivative": case, "source_asset_id": parent_asset_id, "source_sha256": parent_sha256,
                                   "derivation": "Explicit timestamp/frame-rate test derivative, not native VFR capture"}
            asset = refresh_fixture_asset(asset, root, ffprobe)
            if case == 'derived_60_to_30':
                assert (asset['fps_num'], asset['fps_den']) == (60, 1)
            assert 'pts_index' not in asset['probe']
        payload = {"asset": asset, "start_ms": 0, "end_ms": asset["duration_ms"], "max_height": 720,
                   "max_fps": 30 if case == "derived_60_to_30" else None}
        job = queue.enqueue("media_proxy", payload)
        claimed = queue.claim("media-actual", lease_seconds=300)
        context = WorkerContext(queue, claimed, "media-actual", root, 300)
        started = time.perf_counter()
        result = create_proxy(context, root / 'platform/jobs' / job['job_id'] / 'attempt-1')
        elapsed = time.perf_counter() - started
        queue.finish(job["job_id"], "media-actual", "succeeded", result=result,artifact_identities=context.artifact_identities)
        preview = result["preview"]
        proxy = root / preview["relative_path"]
        index_path = root / preview["index_relative_path"]
        frames = read_frame_map(index_path)["frames"]
        source_frames = read_source_frames(index_path)["source_frames"]
        assert proxy.stat().st_size <= MAX_PROXY_BYTES
        assert preview["source_sha256"] == asset["sha256"]
        assert preview["source_index_scope"] == "full_source"
        assert frames[0]["coverage_start_ms"] == preview["window_start_ms"]
        assert frames[-1]["coverage_end_ms"] == preview["window_end_ms"]
        assert all(left["coverage_end_ms"] == right["coverage_start_ms"] for left, right in zip(frames, frames[1:]))
        info = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(proxy)], timeout=30))
        assert info["streams"][0]["codec_name"] == "h264"
        assert info["streams"][0]["pix_fmt"] == "yuv420p"
        # Atom order proves faststart without decoding the file into memory.
        atoms = []
        with proxy.open("rb") as handle:
            while True:
                header = handle.read(8)
                if len(header) != 8:
                    break
                size = int.from_bytes(header[:4], "big")
                atoms.append(header[4:].decode("ascii"))
                assert size >= 8
                handle.seek(size - 8, 1)
        assert atoms.index("moov") < atoms.index("mdat")
        points = []
        for point in range(30):
            selected = frames[round(point * (len(frames) - 1) / 29)]
            actual = read_frame_map(index_path, at_ms=selected["proxy_pts_ms"], limit=1)["frames"][0]
            error = abs(actual["source_pts_ms"] - (actual["proxy_pts_ms"] + preview["window_start_ms"]))
            assert error < 0.01
            points.append({"point": point, "proxy_pts_ms": actual["proxy_pts_ms"], "source_pts_ms": actual["source_pts_ms"], "source_frame_index": actual["source_frame_index"], "error_ms": error})
        if case == "derived_vfr":
            assert len({round(b["source_pts_ms"]-a["source_pts_ms"], 3) for a, b in zip(source_frames, source_frames[1:])}) > 1
            assert len(frames) == len(source_frames)
        if case == "derived_60_to_30":
            assert len(source_frames) >= 2 * len(frames) - 1
            assert len(source_frames) > len(frames)
        frame_number = len(source_frames) // 2
        frame_job = queue.enqueue("exact_frame", {"asset": asset, "preview_job_id":job['job_id'], "index_relative_path": preview["index_relative_path"], "source_frame_index": frame_number})
        frame_context = WorkerContext(queue, queue.claim("media-actual", lease_seconds=300), "media-actual", root, 300)
        exact = exact_frame(frame_context, root / 'platform/jobs' / frame_job['job_id'] / 'attempt-1')
        queue.finish(frame_job["job_id"], "media-actual", "succeeded", result=exact,artifact_identities=frame_context.artifact_identities)
        image = root / exact["frame"]["relative_path"]
        jpeg_info = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(image)], timeout=30))["streams"][0]
        assert (jpeg_info["width"], jpeg_info["height"]) == (asset["width"], asset["height"])
        report = {"case_id": "R-02a", "case": case, "status": "PASS", "synthetic_or_derived_timestamps": case != "real_cfr",
                  "source": asset, "commands_for_derived_input": commands, "preview_result": result, "exact_frame_result": exact,
                  "fixed_30_point_mapping": points, "encode_index_thumbnail_elapsed_s": elapsed,
                  "source_frames": len(source_frames), "proxy_frames": len(frames), "browser_seek_status": "NOT_RUN: R-02b is separate browser acceptance",
                  "ffmpeg_version": subprocess.check_output([ffmpeg, "-version"], text=True).splitlines()[0]}
        (case_dir / "R-02a-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        ledger.release(setup_reservation)


@pytest.mark.skipif(not REAL_ROOT, reason="requires reports from the opt-in real CPU tests")
def test_real_existing_evidence_independent_pts_frame_selection():
    """A second selector uses raw source PTS, independent of the ordinal handler."""
    root = Path("D:/video")
    test_root = Path(REAL_ROOT).resolve()
    ffmpeg = os.environ["BTV_FFMPEG"]
    checks = []
    for case_dir in sorted(test_root.iterdir()):
        report_path = case_dir / "R-02a-report.json"
        if not report_path.is_file():
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "PASS"
        asset = report["source"]
        frame = report["exact_frame_result"]["frame"]
        ledger = CapacityLedger(case_dir / "test-runtime.sqlite3", root)
        reservation = ledger.reserve("platform", 40_000_000, job_id="independent-exact-" + case_dir.name)
        try:
            reference = resolve_owner_path(root, (case_dir / "pts-selected-reference.jpg").relative_to(root).as_posix(), "platform")
            argv = [ffmpeg, "-nostdin", "-v", "error", "-copyts", "-noautorotate", "-threads", "2", "-i", str(root / asset["relative_path"]),
                    "-map", "0:v:0", "-an", "-vf", f"select='eq(pts,{frame['source_pts']})'", "-frames:v", "1", "-fps_mode", "vfr",
                    "-q:v", "2", "-threads", "1", "-fs", "31000000", "-n", str(reference)]
            subprocess.run(argv, check=True, timeout=120)
            with reference.open("rb") as handle:
                reference_sha = hashlib.file_digest(handle, "sha256").hexdigest()
            with (root / frame["relative_path"]).open("rb") as handle:
                actual_sha = hashlib.file_digest(handle, "sha256").hexdigest()
            assert reference_sha == actual_sha
            with _connect(case_dir / "proxy-attempt-1/encoded-index.sqlite3", True) as db:
                keys = [row[0] for row in db.execute("SELECT source_frame_index FROM source_frames WHERE key_frame=1 ORDER BY source_frame_index")]
            assert keys and keys[0] == 0
            assert all(right - left <= 30 for left, right in zip(keys, keys[1:]))
            check = {"case_id": "R-02a", "case": case_dir.name, "status": "PASS", "source_pts": frame["source_pts"],
                     "source_frame_index": frame["source_frame_index"], "reference_sha256": reference_sha, "actual_sha256": actual_sha,
                     "independent_selection_command": argv, "gop_keyframe_indices": keys}
            (case_dir / "R-02a-independent-frame-check.json").write_text(json.dumps(check, indent=2), encoding="utf-8")
            checks.append(check)
        finally:
            ledger.release(reservation)
    assert len(checks) == 4
