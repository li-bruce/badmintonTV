"""Build a reviewable real-source research preview, without claiming human labels."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.render.storage import atomic_json, reservation, utcnow


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--storage-root", type=Path, default=Path("D:/video"))
    p.add_argument("--environment", type=Path, default=Path("environments/render-runtime.json"))
    args = p.parse_args()
    root = args.storage_root.resolve()
    env = json.loads(args.environment.read_text(encoding="utf-8"))
    raw = json.loads((root/"data/handoff/assets.v1.json").read_text(encoding="utf-8"))["assets"]
    by_uid = {a.get("provenance", {}).get("video_uid"): a for a in raw}
    selected = [by_uid[x] for x in ("video_001951", "video_000002", "video_000003")]
    job = "real-research-" + uuid.uuid4().hex[:10]
    request = dict(schema_version="1.0", job_id=job, attempt_id="attempt-01", operation="render", assets=selected,
                   output_dir=f"render/jobs/{job}/attempt-01", parameters={"research_preview": True, "timeline": {
                       "schema_version":"1.0", "timeline_id":job, "title":"网前与攻防衔接 · 流程演示", "segments":[],
                       "output":{"width":1080,"height":1920,"fps":30,"video_codec":"h264","audio_codec":"aac"}}})
    for i, asset in enumerate(selected):
        speed = 0.75 if i == 1 else 1.0
        request["parameters"]["timeline"]["segments"].append(dict(segment_id=f"source-{i+1:02}",asset_id=asset["asset_id"],in_ms=0,out_ms=asset["duration_ms"],speed=speed,event_ids=[],fit="contain",audio="source",review_status="unreviewed",
                title=["网前往返 · 保留完整原片窗口","攻防衔接 · 0.75倍慢放","网前到后场 · 原速片段"][i],subtitles=[{"start_ms":0,"end_ms":3000,"text":"细手法未知 · 球员身份待确认"}],
                editorial_review={"reviewer_type":"assistant_visual_review","method":"2fps source contact sheet", "human_review":"pending", "hand_technique":"unknown"}))
    # Extra editorial controls stay outside the strict canonical Timeline schema.
    request["parameters"]["segment_options"] = {}
    for segment in request["parameters"]["timeline"]["segments"]:
        request["parameters"]["segment_options"][segment["segment_id"]] = {key:segment.pop(key) for key in ("subtitles", "editorial_review")}
    handoff = root / "render/handoff" / job
    with reservation(root, job+"-request", 1_000_000):
        handoff.mkdir(parents=True, exist_ok=False)
        atomic_json(handoff/"request.json", request)
    command=[sys.executable,"-m","packages.render","run","--request",str(handoff/"request.json"),"--result",str(handoff/"result.json"),"--storage-root",str(root),"--ffmpeg",env["checks"]["ffmpeg"],"--ffprobe",env["checks"]["ffprobe"]]
    with (handoff/"progress.jsonl").open("x",encoding="utf-8") as progress:
        proc=subprocess.run(command,stdout=progress,check=False)
    result=json.loads((handoff/"result.json").read_text(encoding="utf-8"))
    atomic_json(handoff/"handoff.json",{"schema_version":"1.0","created_at":utcnow(),"job_id":job,"request":(handoff/"request.json").relative_to(root).as_posix(),"result":(handoff/"result.json").relative_to(root).as_posix(),"render_output":request["output_dir"],"status":result["status"],"kind":"real_source_research_preview","human_acceptance":"pending","source_rights":"unknown; not for publication","command":command})
    print(json.dumps({"handoff":str(handoff),"result":result},ensure_ascii=False,indent=2))
    return proc.returncode


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
