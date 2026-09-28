"""Reproducible synthetic checks, never a badminton business acceptance test."""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.render import RenderConfig, render
from packages.render.storage import atomic_json, reservation, sha256, utcnow


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", type=Path, default=Path("environments/render-runtime.json"))
    parser.add_argument("--storage-root", type=Path, default=Path("D:/video"))
    args = parser.parse_args()
    env = json.loads(args.environment.read_text(encoding="utf-8"))
    ffmpeg, ffprobe = env["checks"]["ffmpeg"], env["checks"]["ffprobe"]
    root = args.storage_root.resolve()
    uid = "smoke-" + uuid.uuid4().hex[:10]
    inputs = root / "render" / "smoke-inputs" / uid
    with reservation(root, uid+"-inputs", 50_000_000):
        inputs.mkdir(parents=True)
        assets = []
        for index, (size, fps, sound) in enumerate([("640x360", "25", True), ("480x360", "30000/1001", False)]):
            file = inputs / f"source-{index}.mp4"
            command = [ffmpeg,"-hide_banner","-nostdin","-n","-loglevel","error","-f","lavfi","-i",f"testsrc2=size={size}:rate={fps}:duration=4"]
            if sound:
                # Brief 1kHz pulse aligns with a white flash at source time 1s for sync measurement.
                command += ["-f","lavfi","-i","aevalsrc=if(between(t\\,1\\,1.1)\\,0.5*sin(2*PI*1000*t)\\,0):s=48000:d=4"]
            command += ["-vf","drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,1,1.08)'", "-c:v","libx264","-preset","veryfast","-threads","2","-pix_fmt","yuv420p"]
            if sound:
                command += ["-c:a","aac","-ac","2"]
            command += ["-t","4","-fs","10000000",str(file)]
            subprocess.run(command, check=True)
            p = json.loads(subprocess.check_output([ffprobe,"-v","error","-show_format","-show_streams","-of","json",str(file)]))
            v = next(s for s in p["streams"] if s["codec_type"] == "video")
            rate = Fraction(v["avg_frame_rate"])
            assets.append(dict(schema_version="1.0", asset_id=f"synthetic-{index}", relative_path=file.relative_to(root).as_posix(),sha256=sha256(file),size_bytes=file.stat().st_size,
                               duration_ms=round(float(p["format"]["duration"])*1000),width=v["width"],height=v["height"],fps_num=rate.numerator,fps_den=rate.denominator,time_base=v["time_base"],
                               title="合成技术测试",match_id=uid,source_type="synthetic",source_url=None,source_page=None,acquired_at=utcnow(),camera_type="unknown",discipline="unknown",players=[],
                               rights={"status":"owned","license_url":None,"evidence":"FFmpeg lavfi generated test only","allowed_uses":["technical_test"]},split="unassigned",probe=p,provenance={"generator":"FFmpeg lavfi"}))
        request = dict(schema_version="1.0",job_id=uid,attempt_id="attempt-01",operation="render",assets=assets,output_dir=f"render/jobs/{uid}/attempt-01",
                       parameters={"timeline":dict(schema_version="1.0",timeline_id=uid,title="合成技术测试 · 非真实比赛",segments=[
                           dict(segment_id="audio-slow",asset_id="synthetic-0",in_ms=0,out_ms=2000,speed=0.5,event_ids=[],fit="contain",title="有声 · 0.5倍慢放",audio="source",review_status="confirmed",subtitles=[{"start_ms":0,"end_ms":3800,"text":"脉冲与白闪用于音画同步测试"}]),
                           dict(segment_id="silent",asset_id="synthetic-1",in_ms=500,out_ms=2500,speed=1,event_ids=[],fit="contain",title="无音轨 · 不同帧率",audio="source",review_status="confirmed"),
                           dict(segment_id="muted-crop",asset_id="synthetic-0",in_ms=2000,out_ms=3000,speed=1,event_ids=[],fit="crop",crop={"x":0.15625,"y":0,"width":0.625,"height":1},title="显式裁切 · 静音",audio="mute",review_status="confirmed")],output={"width":1080,"height":1920,"fps":30,"video_codec":"h264","audio_codec":"aac"})})
        atomic_json(inputs/"request.json",request)
    cfg = RenderConfig(root,ffmpeg,ffprobe)
    events=[]
    def emit(event):
        events.append(event)
        print(json.dumps(event,ensure_ascii=False),flush=True)
    result=render(request,cfg,emit)
    atomic_json(inputs/"result.json",result)
    atomic_json(inputs/"progress.json",events)
    checks={"synthetic_only":True,"render":result["status"]=="succeeded","progress_sequential": [e["seq"] for e in events]==list(range(1,len(events)+1))}
    missing=deepcopy(request)
    missing["job_id"]+="-blocked"
    missing["output_dir"]+="-blocked"
    blocked=render(missing,RenderConfig(root,"definitely-not-a-real-ffmpeg-command",ffprobe))
    checks["missing_ffmpeg_blocked"]=blocked["status"]=="blocked"
    cancel=deepcopy(missing)
    cancel["output_dir"]+="-cancel"
    cancelled=render(cancel,cfg,cancelled=lambda:True)
    checks["cancelled"]=cancelled["status"]=="cancelled"
    if result["status"]=="succeeded":
        qa=json.loads((root/request["output_dir"]/"qa.json").read_text(encoding="utf-8"))
        checks.update(qa["checks"])
        checks["expected_7_seconds"]=abs(qa["actual_duration_ms"]-7000)<80
    report=dict(schema_version="1.0",kind="synthetic_technical_test",created_at=utcnow(),job_id=uid,checks=checks,result=result,request_path=str(inputs/"request.json"))
    atomic_json(inputs/"report.json",report)
    print(json.dumps({"report":str(inputs/"report.json"),"checks":checks},ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(run())
