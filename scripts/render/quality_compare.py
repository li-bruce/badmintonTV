"""CPU-only, bounded A/R and B/R comparison for one 30/60 fps render pair.

R is lossless FFV1/yuv420p with the recorded CPU segment input/filter timing.
Three segments yield nine fixed review points (30%, 60%, 85% of each segment).
Media is written only to a new D:/video/render/quality-* directory. Existing
render outputs are read only. Invoke separately for the 30 and 60 fps pairs.
This script measures technical quality; it does not grant human acceptance.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.render.storage import atomic_json, directory_bytes, reservation, sha256, utcnow
from packages.render.timeline import RenderError, assets_by_id, require, safe_path
from packages.render.usage import check_usage, referenced_assets, verify_source_bytes

BUDGET = 1_000_000_000  # Decimal bytes, including references, PNGs and logs.
HEADROOM = 64_000_000
PTS_TOLERANCE = Fraction(1, 90000)
ROI = {"x": 0, "y": 656, "width": 1080, "height": 608}
THREADS = 4


def require_matching_pts(primary, secondary, label):
    require(len(primary) == len(secondary) and len(primary) > 0,
            f"{label}: actual frame PTS counts differ or are empty", "pts_mismatch")
    difference = max(abs(a-b) for a, b in zip(primary, secondary))
    require(difference <= PTS_TOLERANCE,
            f"{label}: actual per-frame PTS differ by more than 1/90000 s", "pts_mismatch")
    return difference


def read_json(path, limit=32_000_000):
    require(path.is_file() and path.stat().st_size <= limit, f"Missing/oversized JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def under(path, root):
    result = Path(path).resolve()
    require(result.is_relative_to(root), f"Path escapes {root}: {path}", "unsafe_path")
    return result


def option(argv, name, *, before=None, after=None):
    indexes = [i for i, value in enumerate(argv[:-1]) if value == name
               and (before is None or i < before) and (after is None or i > after)]
    require(len(indexes) == 1, f"Expected one {name} in the recorded command")
    return argv[indexes[0] + 1]


def segment_commands(directory, count):
    timings = read_json(directory / "stage_timings.json")
    require(isinstance(timings, list), "stage_timings.json must be a list")
    result = []
    for i in range(count):
        rows = [row for row in timings if row.get("stage") == f"segment:{i+1}"]
        require(len(rows) == 1 and rows[0].get("returncode") == 0, "Missing successful segment command")
        argv = rows[0].get("argv")
        require(isinstance(argv, list) and all(isinstance(v, str) for v in argv), "Invalid recorded argv")
        require("-i" in argv, "Recorded input is missing")
        first_input = argv.index("-i")
        maps = [argv[n+1] for n, v in enumerate(argv[:-1]) if v == "-map"]
        require(maps and re.fullmatch(r"0:\d+", maps[0]), "Unsupported video stream map")
        vf = option(argv, "-vf")
        ass = f"segment-{i:03}.ass"
        require(f",subtitles={ass}," in vf and vf.count("subtitles=") == 1,
                "Reference requires the original local ASS filter")
        # The engine uses this exact CPU-only chain. Never replay arbitrary
        # filters/inputs or encoder options from the recorded command.
        prefix = r"bwdif=mode=send_frame:parity=auto:deint=interlaced,setpts=PTS/[0-9.eE+-]+,scale=trunc\(iw\*sar/2\)\*2:ih,setsar=1"
        suffix = (r",scale=1080:1112:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                  r"pad=1080:1920:\(ow-iw\)/2:\(oh-ih\)/2:color=0x121a26,setsar=1,"
                  r"fps=(30|60):start_time=0,tpad=stop_mode=clone:stop_duration=1,"
                  r"trim=end_frame=\d+,setpts=N/\((30|60)\*TB\),subtitles="
                  + re.escape(ass) + r",format=yuv420p,setfield=prog")
        require(re.fullmatch(prefix + suffix, vf) is not None,
                "Unsupported filter chain: this comparison requires current 1080p contain layout")
        result.append(dict(input=argv[first_input+1], ss=option(argv, "-ss", before=first_input),
                           input_t=option(argv, "-t", before=first_input),
                           output_t=option(argv, "-t", after=first_input), video_map=maps[0], vf=vf,
                           ass=ass, ass_sha256=sha256(under(directory / ass, directory))))
    return result


def original_request_sources(directory, root):
    """Use the same gate as render, on every original reference before editing.

    source_map is an alignment artifact, not a substitute for canonical Asset
    usage/provenance. verify_source_bytes also rechecks the shared gate using
    actual digests, including source references later discarded as replays.
    """
    request = read_json(under(directory / "request.json", directory))
    require(request.get("operation") == "render", "Original request must be a render operation")
    require(isinstance(request.get("assets"), list), "Original request requires top-level canonical assets array")
    params = request.get("parameters", {})
    require(isinstance(params, dict) and "assets" not in params, "Invalid original request parameters")
    research_preview = params.get("research_preview", False)
    require(type(research_preview) is bool, "Original research_preview must be boolean")
    assets = assets_by_id(request["assets"])
    selected = referenced_assets(params.get("timeline"), assets)
    check_usage(selected, assets, root, research_preview)
    paths = verify_source_bytes(selected, assets, root, lambda: None, research_preview)
    return assets, paths


def preflight(args):
    root = args.storage_root.resolve()
    allowed = Path("D:/video" if os.name == "nt" else "/mnt/d/video").resolve()
    require(root == allowed, "storage-root must be D:/video (or /mnt/d/video)", "unsafe_path")
    cpu, nvenc = (under(p, root / "render") for p in (args.cpu_output, args.nvenc_output))
    require(cpu != nvenc, "CPU and NVENC outputs must differ")
    # Shared metadata and actual-byte gates precede every reservation and
    # FFmpeg/ffprobe invocation, including the runtime version query below.
    original_a = original_request_sources(cpu, root)
    original_b = original_request_sources(nvenc, root)
    qa_a, qa_b = (read_json(p / "qa.json") for p in (cpu, nvenc))
    sm_a, sm_b = (read_json(p / "source_map.json") for p in (cpu, nvenc))
    for qa, backend in ((qa_a, "cpu"), (qa_b, "nvenc")):
        require(qa.get("technical_pass") is True and all(qa.get("checks", {}).values()), "Both QA reports must pass")
        require(qa.get("backend", {}).get("effective") == backend, f"Expected actual {backend} backend")
        require(qa.get("effective_output") == sm_a.get("effective_output"), "QA/output geometry mismatch")
    require(sm_a.get("effective_output") == sm_b.get("effective_output"), "A/B geometry differs")
    output = sm_a["effective_output"]
    fps = output["fps"]
    require(output["width"] == 1080 and output["height"] == 1920 and fps in (30, 60), "Only portrait 1080p30/60 supported")
    require(sm_a.get("output_fps") == sm_b.get("output_fps") == fps, "A/B fps differs")
    require(qa_a.get("ffmpeg_version") == qa_b.get("ffmpeg_version"), "A/B FFmpeg versions differ")
    require(sm_a.get("segment_options") == sm_b.get("segment_options"), "A/B editorial options differ")
    segments, other = sm_a.get("segments"), sm_b.get("segments")
    require(isinstance(segments, list) and len(segments) == 3 and isinstance(other, list) and len(other) == 3,
            "Initial protocol requires three segments and nine screenshot points")
    keys = ("segment_id", "source_segment_ids", "asset_id", "relative_path", "source_sha256",
            "source_in_ms", "source_out_ms", "source_time_base", "source_start_pts", "source_start_time",
            "source_pts_index", "source_provenance", "speed", "output_in_frame", "output_out_frame",
            "output_in_ms", "output_out_ms", "fit", "crop", "audio_strategy", "event_ids")
    cursor = 0
    for a, b in zip(segments, other):
        require(all(a.get(key) == b.get(key) for key in keys), "A/B source maps differ")
        require(a["output_in_frame"] == cursor and type(a["output_out_frame"]) is int and a["output_out_frame"] > cursor,
                "Non-contiguous or empty segment frame range")
        cursor = a["output_out_frame"]
        require(a.get("fit") == "contain" and not a.get("crop"), "Active-picture ROI requires contain, without crop")
        video = next(v for v in a["source_probe"]["streams"] if v.get("codec_type") == "video"
                     and not v.get("disposition", {}).get("attached_pic"))
        require(video["width"] * 9 == video["height"] * 16 and video.get("sample_aspect_ratio", "1:1") in ("1:1", "N/A")
                and not any(d.get("rotation", 0) for d in video.get("side_data_list", [])),
                "Fixed active-picture ROI requires unrotated square-pixel 16:9 sources")
    require(cursor / fps <= 30, "Comparison duration exceeds 30 seconds")
    commands_a, commands_b = segment_commands(cpu, 3), segment_commands(nvenc, 3)
    require(commands_a == commands_b, "A/B input/filter/ASS/timing differs")
    for segment, command in zip(segments, commands_a):
        source = safe_path(root, segment["relative_path"])
        require(under(command["input"], root) == source, "Recorded input differs from source map")
        aid = segment["asset_id"]
        for original_assets, verified_paths in (original_a, original_b):
            require(aid in verified_paths and verified_paths[aid] == source,
                    "Source map input was not verified from the original request")
            require(original_assets[aid]["sha256"].lower() == segment["source_sha256"].lower(),
                    "Source map hash differs from the verified original Asset")
        require(abs(Fraction(command["ss"]) - Fraction(str(segment["source_in_ms"])) / 1000) <= Fraction(1, 1000000), "Input seek differs")
        require(abs(Fraction(command["input_t"]) - Fraction(str(segment["source_out_ms"] - segment["source_in_ms"])) / 1000) <= Fraction(1, 1000000), "Input duration differs")
        count = segment["output_out_frame"] - segment["output_in_frame"]
        require(abs(Fraction(command["output_t"]) - Fraction(count, fps)) <= Fraction(1, 1000000000), "Output duration differs")
        require(f"trim=end_frame={count}," in command["vf"] and f"fps={fps}:" in command["vf"], "Filter/frame map differs")
    env = read_json(args.environment)["checks"]
    binaries = {}
    for name in ("ffmpeg", "ffprobe"):
        binary = under(env[name], root / "runtime" / "render")
        require(binary.is_file() and sha256(binary) == env[name + "_sha256"], f"Runtime hash differs: {name}")
        binaries[name] = str(binary)
    # The environment records the banner; QA records full `ffmpeg -version`
    # stdout. Check both the declaration and actual binary against the two QA
    # reports, so a different reference renderer cannot silently enter A/B.
    expected_version = qa_a.get("ffmpeg_version", "")
    require(isinstance(expected_version, str) and expected_version.strip(), "QA lacks FFmpeg version")
    require(env.get("version") == expected_version.splitlines()[0], "Environment FFmpeg version differs from A/B QA")
    version_probe = subprocess.run([binaries["ffmpeg"], "-version"], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)
    require(version_probe.returncode == 0, "FFmpeg version query failed", "runtime_version_failed")
    actual_version = version_probe.stdout.decode("utf-8", "replace")
    require(actual_version.splitlines() == expected_version.splitlines(),
            "Actual reference FFmpeg version differs from A/B QA", "runtime_version_mismatch")
    media = [under(folder / ("preview.mp4" if qa.get("preview") else "export.mp4"), folder)
             for folder, qa in ((cpu, qa_a), (nvenc, qa_b))]
    require(all(path.is_file() for path in media), "Completed output video missing")
    return root, cpu, nvenc, fps, segments, commands_a, media, binaries


class Runner:
    def __init__(self, root, output, binaries):
        self.root, self.output, self.binaries = root, output, binaries
        self.records = []

    def check(self):
        used = directory_bytes(self.output)
        require(used < BUDGET - HEADROOM, "Quality experiment reached its 1 GB budget headroom; files retained", "quota_exceeded")
        require(shutil.disk_usage(self.root).free >= 128_000_000, "Physical free-space safety margin reached", "disk_full")
        return used

    def run(self, name, argv, cwd=None, timeout=600):
        self.check()
        started = time.perf_counter()
        proc = None
        stdout = self.output / (name + ".stdout")
        stderr = self.output / (name + ".stderr")
        record = dict(stage=name, argv=argv, cwd=str(cwd or self.output), stdout=stdout.name, stderr=stderr.name)
        try:
            with stdout.open("xb") as out, stderr.open("xb") as err:
                proc = subprocess.Popen(argv, cwd=cwd or self.output, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
                while proc.poll() is None:
                    self.check()
                    require(time.perf_counter() - started <= timeout, f"Stage timed out: {name}", "timeout")
                    time.sleep(0.1)
                record["returncode"] = proc.returncode
                require(proc.returncode == 0, f"{name} failed; inspect {stderr.name}", "process_failed")
            self.check()
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            record.update(elapsed_seconds=round(time.perf_counter()-started, 6),
                          returncode=proc.returncode if proc else None)
            self.records.append(record)
        return stdout

    def ffmpeg(self, name, args, cwd=None, *, loglevel="warning"):
        return self.run(name, [self.binaries["ffmpeg"], "-hide_banner", "-nostdin", "-n", "-loglevel", loglevel,
                               "-filter_threads", str(THREADS), "-filter_complex_threads", str(THREADS), *args], cwd)

    def probe(self, name, inputs, expected):
        path = self.run(name, [self.binaries["ffprobe"], "-v", "error", "-threads", str(THREADS),
                              *inputs, "-select_streams", "v:0", "-show_streams", "-show_frames", "-show_entries",
                              "stream=codec_name,width,height,pix_fmt,time_base,nb_frames,duration:frame=pts,best_effort_timestamp",
                              "-of", "json"])
        data = read_json(path)
        require(len(data.get("streams", [])) == 1, "Expected one selected video stream")
        stream = data["streams"][0]
        require((stream.get("width"), stream.get("height"), stream.get("pix_fmt")) == (1080, 1920, "yuv420p"), "Actual decoded geometry differs")
        frames = data.get("frames", [])
        require(len(frames) == expected, f"{name}: decoded frame count {len(frames)} != {expected}")
        tb = Fraction(stream["time_base"])
        # Decoder display-order timestamps, before any setpts normalization.
        require(all("pts" in frame for frame in frames), f"{name}: actual frame PTS unavailable")
        pts = [int(frame["pts"]) * tb for frame in frames]
        require(all(a < b for a, b in zip(pts, pts[1:])), f"{name}: non-monotonic/duplicate frame PTS")
        return pts, dict(stream=stream, frame_count=len(frames), first_pts_seconds=str(pts[0]),
                         last_pts_seconds=str(pts[-1]), frames_file=path.name,
                         min_delta_seconds=str(min(b-a for a, b in zip(pts, pts[1:]))) if len(pts) > 1 else None,
                         max_delta_seconds=str(max(b-a for a, b in zip(pts, pts[1:]))) if len(pts) > 1 else None)


def metric_summary(path, metric, expected, summary_path):
    values = []
    pattern = re.compile(r"([A-Za-z_]+):\s*([+-]?(?:inf|nan|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("n:"):
            continue
        row = {key: float(value) for key, value in pattern.findall(line)}
        require(row.get("n") == len(values)+1, "Metric frame indexes are not contiguous")
        values.append(row)
    require(len(values) == expected, f"{metric} compared {len(values)} != {expected} frames")
    summary_lines = [line for line in summary_path.read_text(encoding="utf-8", errors="replace").splitlines()
                     if re.search(r"\b" + metric.upper() + r"\s+[A-Za-z]+:", line)]
    require(len(summary_lines) == 1, f"Expected one authoritative {metric} final summary")
    final = {key: float(value) for key, value in pattern.findall(summary_lines[0])}
    require(all(not math.isnan(value) for value in final.values()), "NaN metric final summary")
    authority = dict(source=summary_path.name, raw_line=summary_lines[0],
                     values={key: value if math.isfinite(value) else str(value) for key, value in final.items()},
                     note="Authoritative FFmpeg final summary, computed before per-frame log rounding")
    if metric == "ssim":
        score = sum(row["All"] for row in values) / expected
        require(math.isfinite(score) and math.isfinite(final.get("All", float("nan"))), "Nonfinite SSIM result")
        return dict(frame_count=expected, all_mean=final["All"], authoritative_ffmpeg_summary=authority,
                    frame_all_mean_approx=score, all_min=min(row["All"] for row in values),
                    all_max=max(row["All"] for row in values), frame_stats=path.name)
    mse = sum(row["mse_avg"] for row in values) / expected
    require(math.isfinite(mse) and mse >= 0, "Invalid PSNR MSE")
    # Aggregate MSE first; averaging per-frame dB gives a different quantity.
    psnr = "inf" if mse == 0 else 10 * math.log10(255 * 255 / mse)
    require("average" in final, "Missing authoritative PSNR average")
    return dict(frame_count=expected, psnr_db=authority["values"]["average"], authoritative_ffmpeg_summary=authority,
                mse_mean_approx=mse, psnr_db_from_mean_mse_approx=psnr, peak=255, frame_stats=path.name,
                note="Per-frame rounded MSE reconstruction is approximate; use authoritative FFmpeg summary")


def compare(runner, fps, segments, commands, media, cpu):
    expected = segments[-1]["output_out_frame"]
    report = dict(schema_version="1.0", status="running", created_at=utcnow(), fps=fps, expected_frame_count=expected,
                  active_picture_roi=ROI, budget_bytes=BUDGET, manual_review="pending",
                  ball_and_feet_roi="NOT_RUN: select spatial ROIs after reviewing the fixed full-frame PNGs")
    atomic_json(runner.output / "request.json", {**report, "cpu_output": str(cpu), "media": [str(p) for p in media],
                                               "recorded_cpu_segment_inputs": commands})
    pts_a, info_a = runner.probe("probe-cpu", ["-i", str(media[0])], expected)
    pts_b, info_b = runner.probe("probe-nvenc", ["-i", str(media[1])], expected)
    pair_difference = require_matching_pts(pts_a, pts_b, "A/B")
    for name, pts in (("cpu", pts_a), ("nvenc", pts_b)):
        require(max(abs(value-Fraction(i, fps)) for i, value in enumerate(pts)) <= PTS_TOLERANCE,
                f"{name}: actual frame clock differs from the source-map frame clock", "pts_mismatch")
    report["input_pts"] = dict(cpu=info_a, nvenc=info_b, tolerance_seconds=str(PTS_TOLERANCE),
                               max_pair_difference_seconds=str(pair_difference), checked_before_setpts=True)
    atomic_json(runner.output / "ab_pts_check.json", report["input_pts"])
    reference_segments = []
    concat_lines = ["ffconcat version 1.0\n"]
    for i, (segment, command) in enumerate(zip(segments, commands)):
        count = segment["output_out_frame"] - segment["output_in_frame"]
        target = runner.output / f"reference-{i:03}.nut"
        cap = BUDGET - HEADROOM - runner.check()
        require(cap > HEADROOM, "Insufficient reserved space for another reference segment", "quota_exceeded")
        runner.ffmpeg(f"reference-{i:03}", ["-threads", str(THREADS), "-ss", command["ss"], "-t", command["input_t"],
                      "-i", command["input"], "-map", command["video_map"], "-an", "-sn", "-dn", "-vf", command["vf"],
                      "-t", command["output_t"], "-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv420p",
                      "-threads", str(THREADS), "-enc_time_base", "1/90000", "-fps_mode", "passthrough",
                      "-map_metadata", "-1", "-fs", str(cap), "-f", "nut", str(target)], cwd=cpu)
        _, info = runner.probe(f"probe-reference-{i:03}", ["-i", str(target)], count)
        info.update(path=target.name, segment_id=segment["segment_id"], bytes=target.stat().st_size,
                    sha256=sha256(target, runner.check))
        reference_segments.append(info)
        concat_lines.append(f"file '{target.name}'\nduration {count/fps:.9f}\n")
    concat = runner.output / "reference.ffconcat"
    with concat.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("".join(concat_lines))
    reference_input = ["-f", "concat", "-safe", "1", "-i", str(concat)]
    pts_r, info_r = runner.probe("probe-reference-concat", reference_input, expected)
    reference_difference = require_matching_pts(pts_a, pts_r, "R/A")
    report["reference"] = dict(format="FFV1/yuv420p NUT segments, logical concat (no duplicate assembled video)",
                               requested_encoder_time_base="1/90000", concat=concat.name, segments=reference_segments,
                               decoded=info_r, max_vs_cpu_pts_difference_seconds=str(reference_difference),
                               tolerance_seconds=str(PTS_TOLERANCE), timestamp_check_passed=True,
                               timestamp_note="Actual R/A PTS checked before metrics pair decoded frames by index")
    # Only now normalize both sides to n/fps. Counts and original A/B PTS passed.
    report["metrics"] = {}
    for arm, path in zip(("cpu", "nvenc"), media):
        report["metrics"][arm] = {}
        for region in ("full", "active_picture"):
            report["metrics"][arm][region] = {}
            crop = ",crop=1080:608:0:656" if region == "active_picture" else ""
            for metric in ("ssim", "psnr"):
                name = f"{arm}-{region}-{metric}"
                stats = name + ".frames.log"
                options = f"stats_file={stats}:eof_action=endall:repeatlast=0"
                if metric == "psnr":
                    options += ":stats_version=2"
                graph = (f"[0:v:0]settb=1/{fps},setpts=N,format=yuv420p{crop}[a];"
                         f"[1:v:0]settb=1/{fps},setpts=N,format=yuv420p{crop}[r];"
                         f"[a][r]{metric}={options}[v]")
                runner.ffmpeg(name, ["-threads", str(THREADS), "-i", str(path), "-threads", str(THREADS), *reference_input,
                                     "-filter_complex", graph, "-map", "[v]", "-an", "-fps_mode", "passthrough", "-f", "null", "-"], loglevel="info")
                report["metrics"][arm][region][metric] = metric_summary(runner.output / stats, metric, expected,
                                                                       runner.output / (name + ".stderr"))
    points = []
    for segment in segments:
        count = segment["output_out_frame"] - segment["output_in_frame"]
        for fraction in (Fraction(3, 10), Fraction(3, 5), Fraction(17, 20)):
            local = min(count-1, int(count * fraction))
            frame = segment["output_in_frame"] + local
            source_ms = segment["source_in_ms"] + local * 1000 / fps * segment["speed"]
            points.append(dict(segment_id=segment["segment_id"], segment_fraction=str(fraction), frame_index=frame,
                               output_time_seconds=str(Fraction(frame, fps)),
                               approximate_source_ms=min(source_ms, segment["source_out_ms"]),
                               source_time_note="Timeline mapping only; source PTS index determines actual selected source frame"))
    selected = sorted({point["frame_index"] for point in points})
    expression = "+".join(f"eq(n\\,{frame})" for frame in selected)
    for arm, inputs in (("cpu", ["-i", str(media[0])]), ("nvenc", ["-i", str(media[1])]), ("reference", reference_input)):
        runner.ffmpeg(f"screenshots-{arm}", ["-threads", str(THREADS), *inputs, "-map", "0:v:0", "-an",
                      "-vf", f"select={expression}", "-fps_mode", "passthrough", "-frames:v", str(len(selected)),
                      "-c:v", "png", "-threads", str(THREADS), "-start_number", "0", str(runner.output / f"{arm}-%03d.png")])
        pictures = sorted(runner.output.glob(f"{arm}-[0-9][0-9][0-9].png"))
        require(len(pictures) == len(selected) and all(p.stat().st_size > 0 for p in pictures), "Screenshot count mismatch")
        for point in points:
            point.setdefault("images", {})[arm] = pictures[selected.index(point["frame_index"])].name
    report.update(status="succeeded", finished_at=utcnow(), screenshot_points=points,
                  metrics_alignment="decoded display frame index; setpts only after actual A/B PTS and A/B/R frame counts passed")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-output", type=Path, required=True)
    parser.add_argument("--nvenc-output", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, default=Path("D:/video" if os.name == "nt" else "/mnt/d/video"))
    parser.add_argument("--environment", type=Path, default=Path("environments/render-runtime.json"))
    args = parser.parse_args()
    runner, output = None, None
    report = {"schema_version": "1.0", "status": "failed", "created_at": utcnow()}
    code = 1

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        root, cpu, nvenc, fps, segments, commands, media, binaries = preflight(args)
        job = "quality-" + uuid.uuid4().hex[:16]
        with reservation(root, job, BUDGET) as ledger:
            output = root / "render" / job
            output.mkdir(exist_ok=False)
            runner = Runner(root, output, binaries)
            try:
                report = compare(runner, fps, segments, commands, media, cpu)
                code = 0
            except KeyboardInterrupt:
                report.update(status="cancelled", error={"code": "cancelled", "message": "Interrupted; generated files retained"})
                code = 130
            except Exception as exc:
                code = 2 if isinstance(exc, RenderError) and exc.status == "blocked" else 1
                report.update(status="blocked" if code == 2 else "failed", error={"code": getattr(exc, "code", "comparison_failed"), "message": str(exc)})
            finally:
                report.update(finished_at=utcnow(), output_dir=str(output), storage=ledger,
                              bytes_before_report=directory_bytes(output), stages=runner.records,
                              cpu_output=str(cpu), nvenc_output=str(nvenc), human_acceptance="pending")
                atomic_json(output / "quality_report.json", report)
    except KeyboardInterrupt:
        report.update(status="cancelled", error={"code": "cancelled", "message": "Interrupted before comparison"})
        code = 130
    except Exception as exc:
        code = 2 if isinstance(exc, RenderError) and exc.status == "blocked" else 1
        report.update(status="blocked" if code == 2 else "failed", error={"code": getattr(exc, "code", "preflight_failed"), "message": str(exc)})
    print(json.dumps({"status": report["status"], "report": str(output / "quality_report.json") if output else None,
                      "error": report.get("error")}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
