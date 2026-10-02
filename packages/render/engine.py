"""FFmpeg executor. All subprocess calls use argv; stdout is protocol only."""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import uuid

from .storage import atomic_json, directory_bytes, reservation, sha256, utcnow
from .timeline import RenderError, assets_by_id, export_timeline, normalize_timeline, require, safe_path, selection_review_summary, text
from .backends import encoder_args, mp4_faststart, verify_gpu_lease
from .presets import resolve_preset, validate_duration
from .usage import check_usage, referenced_assets, verify_source_bytes


@dataclass
class RenderConfig:
    storage_root: Path = Path("D:/video" if os.name == "nt" else "/mnt/d/video")
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    threads: int = 4
    font_dir: str | None = None
    font_name: str = "Microsoft YaHei" if os.name == "nt" else "Noto Sans CJK SC"
    cancel_file: Path | None = None
    owner_limit: int = 40_000_000_000
    backend: str = "cpu"
    runtime_db: Path | None = None
    gpu_lease_id: str | None = None


class Runner:
    def __init__(self, cfg, job, emit, cancelled, attempt="unknown"):
        self.cfg, self.job, self.emit_callback, self.cancelled = cfg, job, emit, cancelled
        self.seq, self.output, self.peak, self.last_capacity_check = 0, None, None, 0
        self.attempt = attempt
        self.timings = []
        self.gpu_required = False
        self.last_lease_check = 0
        self.lease = None

    def emit(self, event, stage, current=None, total=None, unit=None, message="", **extra):
        self.seq += 1
        self.emit_callback(dict(schema_version="1.0", job_id=self.job, seq=self.seq, event=event,
                                stage=stage, current=current, total=total, unit=unit, message=message))

    def check(self):
        if self.cancelled() or (self.cfg.cancel_file and self.cfg.cancel_file.exists()):
            raise RenderError("cancelled", "Render was cancelled", "cancelled")
        if self.gpu_required and time.monotonic() - self.last_lease_check > 1:
            self.lease = verify_gpu_lease(self.cfg.runtime_db, self.cfg.gpu_lease_id, self.job, self.attempt)
            self.last_lease_check = time.monotonic()
        if self.output and self.peak and time.monotonic() - self.last_capacity_check > 1:
            self.last_capacity_check = time.monotonic()
            require(directory_bytes(self.output) <= self.peak, "render exceeded reserved bytes", "quota_exceeded")
            require(shutil.disk_usage(self.output).free >= 128_000_000, "disk free space exhausted", "disk_full")

    def capture(self, args, timeout=30):
        self.check()
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (FileNotFoundError, PermissionError) as exc:
            raise RenderError("not_installed", f"Executable unavailable: {args[0]}", "blocked") from exc
        started = time.monotonic()
        try:
            while True:
                self.check()
                try:
                    out, err = proc.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    require(time.monotonic()-started < timeout, "media probe timed out", "probe_timeout")
            require(proc.returncode == 0, err.decode("utf-8", "replace")[-3000:], "probe_failed")
            return out.decode("utf-8", "replace")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

    def probe(self, path):
        return json.loads(self.capture([self.cfg.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))

    def ffmpeg(self, args, stage, duration_ms, log_name):
        self.check()
        q = queue.Queue()
        command = [self.cfg.ffmpeg, "-hide_banner", "-nostdin", "-n", "-loglevel", "warning",
                   "-progress", "pipe:1", "-stats_period", "0.25", "-filter_threads", str(self.cfg.threads), *args]
        log_path = self.output / log_name
        started = time.perf_counter()
        with log_path.open("xb") as log:
            proc = subprocess.Popen(command, cwd=self.output, stdout=subprocess.PIPE, stderr=log,
                                    text=True, encoding="utf-8", errors="replace",
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            def read_progress():
                for line in proc.stdout:
                    q.put(line.strip())
                q.put(None)
            thread = threading.Thread(target=read_progress, daemon=True)
            thread.start()
            try:
                done = False
                while not done:
                    self.check()
                    try:
                        line = q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if line is None:
                        done = True
                    elif line.startswith("out_time_us="):
                        value = line.partition("=")[2]
                        if value.lstrip("-").isdigit():
                            current = max(0, int(value) / 1000)
                            self.emit("progress", stage, min(round(current, 3), duration_ms), duration_ms, "ms")
                returncode = proc.wait()
                require(returncode == 0, f"FFmpeg failed at {stage}; see {log_name}", "encode_failed")
                self.check()
                self.emit("progress", stage, duration_ms, duration_ms, "ms")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                thread.join(timeout=3)
                proc.stdout.close()
                self.timings.append(dict(stage=stage, elapsed_seconds=round(time.perf_counter()-started, 6),
                                         returncode=proc.returncode, argv=command, log=log_name))
                atomic_json(self.output / "stage_timings.json", self.timings)


def tempo_filters(speed):
    filters = []
    while speed < 0.5:
        filters.append("atempo=0.5")
        speed /= 0.5
    while speed > 2:
        filters.append("atempo=2")
        speed /= 2
    filters.append(f"atempo={speed:.12g}")
    return ",".join(filters)


def ass_time(milliseconds):
    cs = max(0, round(milliseconds / 10))
    return f"{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}"


def ass_text(value):
    # ASS override syntax is never executable from supplied plain text.
    return value.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\r", "").replace("\n", "\\N").replace("\t", " ")


def wrap_title(value, width=21):
    lines = []
    for line in value.splitlines():
        lines.extend(line[i:i+width] for i in range(0, len(line), width))
    return "\n".join(lines[:3])


def write_ass(path, timeline, segment, index, count, font_name):
    require(not any(c in font_name for c in ",\n\r"), "invalid configured font name")
    area = timeline["render_metadata"]["preset"]["safe_area"]
    left, right = math.ceil(area["x"]*1080), math.ceil((1-area["x"]-area["width"])*1080)
    top, bottom = math.ceil(area["y"]*1920), math.ceil((1-area["y"]-area["height"])*1920)
    scale = min(1, area["width"]/.82, area["height"]/.78)
    title_size, sub_size, info_size = (max(1, round(x*scale)) for x in (58, 44, 30))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{font_name},{title_size},&H00FFFFFF,&H00FFFFFF,&H00221812,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,8,{left},{right},{top+round(24*scale)},1
Style: Subtitle,{font_name},{sub_size},&H00FFFFFF,&H00FFFFFF,&H00221812,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,{left},{right},{bottom+round(120*scale)},1
Style: Info,{font_name},{info_size},&H00D1C8B5,&H00D1C8B5,&H00221812,&H80000000,0,0,0,0,100,100,0,0,1,1,0,2,{left},{right},{bottom+round(24*scale)},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    end = ass_time(segment["output_duration_ms"])
    title = segment.get("title") or timeline.get("title", "")
    info = f"{index + 1} / {count}   ·   {segment['speed']:g}x   ·   {segment['in_ms']/1000:.2f}–{segment['out_ms']/1000:.2f}s"
    if timeline["render_metadata"].get("research_preview"):
        info += "\n待人工确认 · 本地研究样片"
    rows = [f"Dialogue: 0,0:00:00.00,{end},Title,,0,0,0,,{ass_text(wrap_title(title, max(1, int(area['width']*1080/title_size))))}",
            f"Dialogue: 0,0:00:00.00,{end},Info,,0,0,0,,{ass_text(info)}"]
    for sub in segment["subtitles"]:
        rows.append(f"Dialogue: 1,{ass_time(sub['start_ms'])},{ass_time(sub['end_ms'])},Subtitle,,0,0,0,,{ass_text(sub['text'])}")
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def artifact(path, kind, root, runner):
    return dict(schema_version="1.0", artifact_id=f"render-{uuid.uuid4().hex}", kind=kind,
                relative_path=path.relative_to(root).as_posix(), sha256=sha256(path, runner.check),
                size_bytes=path.stat().st_size, created_at=utcnow(), producer="badmintonTV.render/0.1.0")


def render(request, config=None, emit=None, cancelled=None):
    """Return v1.0 result; external config is trusted, request paths are validated."""
    cfg = config or RenderConfig()
    started = time.perf_counter()
    cfg.storage_root = Path(cfg.storage_root).resolve()
    r = Runner(cfg, request.get("job_id", "unknown") if isinstance(request, dict) else "unknown", emit or (lambda event: None), cancelled or (lambda: False), request.get("attempt_id", "unknown") if isinstance(request, dict) else "unknown")
    result = dict(schema_version="1.0", job_id=r.job, attempt_id=request.get("attempt_id", "unknown") if isinstance(request, dict) else "unknown", status="failed", artifacts=[], events=[], error=None)
    try:
        require(isinstance(request, dict) and request.get("schema_version") == "1.0", "request schema_version must be 1.0")
        require(text(request.get("job_id"), "job_id", 200), "job_id required")
        require(text(request.get("attempt_id"), "attempt_id", 200), "attempt_id required")
        require(request.get("operation") == "render", "operation must be render")
        require(isinstance(request.get("assets"), list), "top-level assets must be an Asset array")
        params = request.get("parameters", {})
        require(isinstance(params, dict) and "assets" not in params, "parameters must not contain assets")
        for option in ("merge_overlaps", "deduplicate_replays", "preview", "research_preview"):
            require(type(params.get(option, False)) is bool, f"{option} must be boolean")
        assets = assets_by_id(request["assets"])
        input_timeline = deepcopy(params.get("timeline"))
        require(isinstance(input_timeline, dict), "timeline must be an object")
        from .usage import reject_training_timeline
        reject_training_timeline(input_timeline)
        original_assets = referenced_assets(input_timeline, assets)
        check_usage(original_assets, assets, cfg.storage_root, params.get("research_preview", False))
        preset = resolve_preset(params, input_timeline.get("output"))
        input_timeline["output"] = preset["output"]
        options = params.get("segment_options", {})
        require(isinstance(options, dict), "segment_options must be a segment_id mapping")
        if isinstance(input_timeline, dict) and isinstance(input_timeline.get("segments"), list):
            for segment in input_timeline["segments"]:
                extension = options.get(segment.get("segment_id"), {})
                require(isinstance(extension, dict) and set(extension) <= {"subtitles", "replay_group_id", "editorial_review"}, "unsupported segment option")
                segment.update(extension)
        output = safe_path(cfg.storage_root, request.get("output_dir"))
        require(output.is_relative_to(cfg.storage_root / "render") and output != cfg.storage_root / "render", "output_dir must be below render/", "unsafe_path")
        require(not output.exists(), "output directory already exists; choose a new job output", "output_exists")
        require(type(cfg.threads) is int and 1 <= cfg.threads <= 16, "threads must be 1..16")
        require(cfg.backend in ("cpu", "nvenc", "auto"), "backend must be cpu, nvenc or auto")
        r.gpu_required = cfg.backend in ("nvenc", "auto")
        r.check()
        for exe in (cfg.ffmpeg, cfg.ffprobe):
            require(shutil.which(exe) is not None, f"Executable unavailable: {exe}", "not_installed")
        verified_paths = verify_source_bytes(original_assets, assets, cfg.storage_root, r.check, params.get("research_preview", False))
        t = normalize_timeline(input_timeline, assets, **{k: params.get(k, False) for k in ("merge_overlaps", "deduplicate_replays", "preview", "research_preview")})
        t["render_metadata"]["preset"] = preset
        total_ms = sum(s["output_frames"] for s in t["segments"]) * 1000 / t["output"]["fps"]
        validate_duration(total_ms, preset["platform_profile"])
        version = r.capture([cfg.ffmpeg, "-version"])
        filters = r.capture([cfg.ffmpeg, "-hide_banner", "-filters"])
        require(" subtitles " in filters and " atempo " in filters, "FFmpeg needs libass subtitles and atempo", "missing_filter")
        # Three bounded copies; PCM stereo48k16bit intermediate exceeds AAC160k.
        peak = math.ceil(total_ms / 1000 * (preset["video_bitrate_bps"]/8 + 192_000 + 128_000) * 3 + 64_000_000)
        r.emit("progress", "preflight", 0, len({s['asset_id'] for s in t['segments']}), "assets")
        with reservation(cfg.storage_root, r.job, peak, cfg.owner_limit) as ledger:
            r.check()
            probes, paths = {}, {}
            for i, aid in enumerate(dict.fromkeys(s["asset_id"] for s in t["segments"])):
                a = assets[aid]
                path = verified_paths[aid]
                probe = r.probe(path)
                videos = [s for s in probe["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")]
                require(videos, f"Asset has no video stream: {aid}", "invalid_media")
                require(videos[0]["width"] == a["width"] and videos[0]["height"] == a["height"], "Asset dimensions differ from probe", "asset_mismatch")
                actual_ms = float(videos[0].get("duration") or probe["format"]["duration"]) * 1000
                require(all(s["out_ms"] <= actual_ms + 1 for s in t["segments"] if s["asset_id"] == aid), "boundary exceeds probed video duration", "invalid_boundary")
                probes[aid], paths[aid] = probe, path
                r.emit("progress", "preflight", i+1, len(set(s['asset_id'] for s in t['segments'])), "assets")
            output.mkdir(parents=True, exist_ok=False)
            r.output, r.peak = output, peak
            atomic_json(output / "reservation.json", ledger)
            atomic_json(output / "request.json", request)
            (output / "ffmpeg-version.txt").write_text(version, encoding="utf-8")
            backend = dict(requested=cfg.backend, effective="cpu" if cfg.backend == "cpu" else "unavailable",
                           encoder="libx264" if cfg.backend == "cpu" else None, fallback_reason=None,
                           decode="cpu", filters="cpu", nvdec="not_requested", gpu_lease=r.lease)
            atomic_json(output / "backend.json", backend)
            if cfg.backend in ("nvenc", "auto"):
                try:
                    effective = t["render_metadata"]["effective_output"]
                    probe_filter = f"scale={effective['width']}:{effective['height']},fps={effective['fps']},format=yuv420p"
                    r.ffmpeg(["-threads", str(cfg.threads), "-t", "0.1", "-i", str(next(iter(paths.values()))), "-an", "-vf", probe_filter,
                              *encoder_args("nvenc", preset), "-f", "null", "-"], "nvenc_probe", 100, "nvenc-probe.log")
                    backend.update(effective="nvenc", encoder="h264_nvenc")
                except RenderError as exc:
                    if exc.code != "encode_failed":
                        raise
                    backend["unavailable_reason"] = str(exc)
                    if cfg.backend != "auto":
                        atomic_json(output / "backend.json", backend)
                        raise RenderError("backend_unavailable", backend["unavailable_reason"], "blocked") from exc
                    backend.update(effective="cpu", encoder="libx264", fallback_reason=backend["unavailable_reason"])
                    r.emit("progress", "backend", message="auto fallback to CPU: " + backend["fallback_reason"])
            atomic_json(output / "backend.json", backend)
            mapping, cursor_frames = [], 0
            w, h, fps = (t["render_metadata"]["effective_output"][k] for k in ("width", "height", "fps"))
            for index, s in enumerate(t["segments"]):
                r.check()
                aid, speed = s["asset_id"], s["speed"]
                probe, path = probes[aid], paths[aid]
                videos = [v for v in probe["streams"] if v["codec_type"] == "video" and not v.get("disposition", {}).get("attached_pic")]
                video = videos[0]
                audio = next((v for v in probe["streams"] if v["codec_type"] == "audio"), None)
                use_audio = bool(audio and s["audio"] == "source")
                duration = s["output_duration_ms"] / 1000
                ass_name = f"segment-{index:03}.ass"
                write_ass(output / ass_name, t, s, index, len(t["segments"]), cfg.font_name)
                vf = f"bwdif=mode=send_frame:parity=auto:deint=interlaced,setpts=PTS/{speed:.12g},scale=trunc(iw*sar/2)*2:ih,setsar=1"
                if s["fit"] == "crop":
                    require(not any(sd.get("rotation", 0) for sd in video.get("side_data_list", [])), "crop for rotated media is not supported")
                    require(video.get("sample_aspect_ratio", "1:1") in ("1:1", "N/A"), "crop requires square pixels")
                    c = s["crop"]
                    cx,cy = round(c['x']*video['width']),round(c['y']*video['height'])
                    cw,ch = max(1,round(c['width']*video['width'])),max(1,round(c['height']*video['height']))
                    cw,ch = min(cw,video['width']-cx),min(ch,video['height']-cy)
                    vf += f",crop={cw}:{ch}:{cx}:{cy}:exact=1"
                # Full source frame stays inside middle 58% band, including portrait sources.
                band = (int(h * 0.58) // 2) * 2
                vf += f",scale={w}:{band}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x121a26,setsar=1,fps={fps}:start_time=0,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={s['output_frames']},setpts=N/({fps}*TB),subtitles={ass_name}"
                if cfg.font_dir:
                    # A trusted directory can still contain FFmpeg punctuation; use a copied local font instead in v1.
                    raise RenderError("unsupported_config", "font_dir is reserved; configure installed system fonts")
                vf += ",format=yuv420p,setfield=prog"
                args = ["-threads", str(cfg.threads), "-ss", f"{s['in_ms']/1000:.6f}", "-t", f"{(s['out_ms']-s['in_ms'])/1000:.6f}", "-i", str(path)]
                if not use_audio:
                    args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                args += ["-map", f"0:{video['index']}", "-map", f"0:{audio['index']}" if use_audio else "1:a:0", "-vf", vf]
                # first_pts=0 inserts source leading silence BEFORE tempo, preserving source A/V offset.
                af = (f"aresample=48000:async=1:first_pts=0,{tempo_filters(speed)}," if use_audio else "") + f"aresample=48000,apad,atrim=duration={duration:.9f},asetpts=N/SR/TB"
                args += ["-af", af, "-t", f"{duration:.9f}", *encoder_args(backend["effective"], preset), "-threads", str(cfg.threads), "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-video_track_timescale", "90000", "-map_metadata", "-1", "-fs", str(peak // 2), f"segment-{index:03}.partial.mov"]
                r.ffmpeg(args, f"segment:{index+1}", s["output_duration_ms"], f"segment-{index:03}.log")
                mapping.append(dict(segment_id=s["segment_id"], source_segment_ids=s["source_segment_ids"], asset_id=aid,
                                    relative_path=assets[aid]["relative_path"], source_sha256=assets[aid]["sha256"],
                                    source_in_ms=s["in_ms"], source_out_ms=s["out_ms"], source_time_base=video["time_base"],
                                    source_start_pts=video.get("start_pts"), source_start_time=video.get("start_time"),
                                    source_pts_index=assets[aid].get("probe", {}).get("pts_index"), source_provenance=assets[aid].get("provenance", {}),
                                    source_probe=probe, event_ids=s["event_ids"], speed=speed,
                                    output_in_frame=cursor_frames, output_out_frame=cursor_frames+s["output_frames"],
                                    output_in_ms=round(cursor_frames * 1000/fps, 6), output_out_ms=round((cursor_frames+s["output_frames"]) * 1000/fps, 6),
                                    timing_error_ms=round(s["output_duration_ms"]-(s["out_ms"]-s["in_ms"])/speed, 6),
                                    audio_strategy="source_atempo" if use_audio else "silence", fit=s["fit"], crop=s.get("crop")))
                cursor_frames += s["output_frames"]
            (output / "concat.txt").write_text("".join(f"file 'segment-{i:03}.partial.mov'\nduration {s['output_frames']/fps:.9f}\n" for i,s in enumerate(t["segments"])), encoding="utf-8")
            # Copy video; recode continuous PCM timing to one AAC stream (avoids repeated priming packets).
            r.ffmpeg(["-f", "concat", "-safe", "1", "-i", "concat.txt", "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", f"aresample=48000:async=1:first_pts=0,apad,atrim=duration={cursor_frames/fps:.9f}", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-t", f"{cursor_frames/fps:.9f}", "-movflags", "+faststart", "-map_metadata", "-1", "-fs", str(peak//2), "export.partial.mp4"], "assemble", total_ms, "assemble.log")
            final_probe = r.probe(output / "export.partial.mp4")
            vs = next((v for v in final_probe["streams"] if v["codec_type"] == "video"), {})
            aus = next((v for v in final_probe["streams"] if v["codec_type"] == "audio"), {})
            actual_duration = float(final_probe["format"]["duration"])*1000
            checks = {"dimensions": vs.get("width") == w and vs.get("height") == h,
                      "codecs": vs.get("codec_name") == "h264" and aus.get("codec_name") == "aac",
                      "pixel_format": vs.get("pix_fmt") == "yuv420p", "audio": aus.get("sample_rate") == "48000" and aus.get("channels") == 2,
                      "duration": abs(actual_duration-total_ms) <= 1000/fps+50,
                      "frame_count": int(vs.get("nb_frames", -1)) == cursor_frames,
                      "fps": Fraction(vs.get("avg_frame_rate", "0")) == fps and Fraction(vs.get("r_frame_rate", "0")) == fps,
                      "progressive": vs.get("field_order") == "progressive",
                      "faststart": mp4_faststart(output / "export.partial.mp4"),
                      "zero_start_pts": abs(float(vs.get("start_time", -1))) < 0.001 and abs(float(aus.get("start_time", -1))) < 0.001,
                      "av_end_alignment": abs(float(vs.get("duration", 0))-float(aus.get("duration", 0))) <= 0.1}
            r.ffmpeg(["-xerror", "-err_detect", "explode", "-threads", str(cfg.threads), "-i", "export.partial.mp4", "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], "decode_qa", total_ms, "decode-qa.log")
            checks["full_decode"] = True
            qa = dict(schema_version="1.0", job_id=r.job, checks=checks, technical_pass=all(checks.values()),
                      expected_duration_ms=total_ms, actual_duration_ms=actual_duration, probe=final_probe,
                      preset=preset, backend=backend, stage_timings=r.timings,
                      elapsed_through_decode_qa_seconds=round(time.perf_counter()-started, 6),
                      source_frame_rates=[dict(asset_id=aid, fps_num=assets[aid]["fps_num"], fps_den=assets[aid]["fps_den"]) for aid in paths],
                      frame_rate_note="Frame duplication at higher output fps adds no genuine source action information",
                      platform_upload_acceptance="not_tested",
                      preview=params.get("preview", False), effective_output=t["render_metadata"]["effective_output"], research_preview=params.get("research_preview", False), **selection_review_summary(t["segments"]), source_types=sorted({assets[s['asset_id']]['source_type'] for s in t['segments']}),
                      manual_review={"status": "pending", "note": "Source context, identity, shuttle visibility and perceived A/V sync need viewing"},
                      rights=[dict(asset_id=aid, rights=assets[aid].get("rights", {})) for aid in paths],
                      publication_clearance="not_verified", ffmpeg_version=version, storage=ledger)
            atomic_json(output / "qa.json", qa)
            require(all(checks.values()), f"QA failed: {[k for k,v in checks.items() if not v]}", "qa_failed")
            atomic_json(output / "timeline.json", export_timeline(t))
            atomic_json(output / "source_map.json", dict(schema_version="1.0", timeline_id=t["timeline_id"], output_fps=fps, effective_output=t["render_metadata"]["effective_output"], segments=mapping,
                                                        editorial_metadata=t["render_metadata"], segment_options={s["segment_id"]:{k:s[k] for k in ("subtitles","replay_group_id","editorial_review") if k in s} for s in t["segments"]}, excluded_replays=t["render_metadata"]["excluded_replays"],
                                                        time_mapping="source_ms = source_in_ms + (output_ms-output_in_ms)*speed; clamp to source interval at quantized last frame"))
            r.check()
            (output / "export.partial.mp4").rename(output / "preview.mp4" if params.get("preview") else output / "export.mp4")
            names = [("preview.mp4" if params.get("preview") else "export.mp4", "video/mp4"), ("timeline.json", "timeline"), ("source_map.json", "source_map"), ("qa.json", "qa_report")]
            artifacts = [artifact(output/name, kind, cfg.storage_root, r) for name,kind in names]
            result.update(status="succeeded", artifacts=artifacts)
            for a in artifacts:
                r.emit("artifact", "complete", message=a["relative_path"], artifact=a)
    except RenderError as exc:
        status = "blocked" if exc.code in ("not_installed", "missing_filter") else exc.status
        result.update(status=status, artifacts=[], error=dict(code=exc.code, message=str(exc)))
        r.emit("error", "cancelled" if status == "cancelled" else "failed", message=str(exc), error=result["error"])
    except Exception as exc:
        result.update(status="failed", artifacts=[], error=dict(code="render_error", message=f"{type(exc).__name__}: {exc}"))
        r.emit("error", "failed", message=result["error"]["message"], error=result["error"])
    return result
