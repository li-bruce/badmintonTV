"""Exercise canonical contracts through actual CLI, including in-flight cancellation."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--contracts-root",type=Path,required=True)
    p.add_argument("--smoke-request",type=Path,required=True)
    p.add_argument("--storage-root",type=Path,default=Path("D:/video"))
    p.add_argument("--environment",type=Path,default=Path("environments/render-runtime.json"))
    args=p.parse_args()
    repo=Path(__file__).resolve().parents[2]
    sys.path[:0]=[str(repo),str(args.contracts_root)]
    from packages.contracts import JobRequest,JobResult,Timeline,ProgressEvent,validate_job_result
    from packages.render.storage import atomic_json,reservation,utcnow
    root=args.storage_root.resolve()
    env=json.loads(args.environment.read_text(encoding="utf-8"))
    source=json.loads(args.smoke_request.read_text(encoding="utf-8"))["assets"][0]
    fixture=json.loads((args.contracts_root/"packages/contracts/fixtures/render-request.json").read_text(encoding="utf-8"))
    source["asset_id"]=fixture["assets"][0]["asset_id"]
    fixture["assets"]=[source]
    uid="contracts-"+uuid.uuid4().hex[:10]
    parent=root/"render/handoff"/uid
    with reservation(root,uid+"-requests",2_000_000):
        parent.mkdir(parents=True,exist_ok=False)
    outcomes=[]
    for case in ("success","preview","blocked","failed","cancelled"):
        request=deepcopy(fixture)
        request["job_id"]=uid+"-"+case
        request["output_dir"]=f"render/jobs/{request['job_id']}/attempt-01"
        if case=="preview":
            request["parameters"]["preview"]=True
        if case=="failed":
            request["parameters"]["timeline"]["segments"][0]["out_ms"]=9000
        if case=="cancelled":
            request["parameters"]["timeline"]["segments"][0]["speed"]=0.125
        request_path=parent/(case+".request.json")
        result_path=parent/(case+".result.json")
        atomic_json(request_path,request)
        cancel_rel=f"render/handoff/{uid}/{case}.cancel"
        command=[sys.executable,"-B","-m","packages.render","run","--request",str(request_path),"--result",str(result_path),"--storage-root",str(root),"--ffmpeg",env["checks"]["ffmpeg"] if case!="blocked" else "missing-ffmpeg-test", "--ffprobe",env["checks"]["ffprobe"],"--cancel-file",cancel_rel]
        proc=subprocess.Popen(command,cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
        events=[];cancel_sent=False
        for line in proc.stdout:
            event=json.loads(line)
            ProgressEvent.model_validate(event)
            events.append(event)
            if case=="cancelled" and str(event.get("stage","")).startswith("segment:") and not cancel_sent:
                (root/cancel_rel).write_text("integration test cancellation after measured encoding progress",encoding="utf-8")
                cancel_sent=True
        stderr=proc.stderr.read()
        returncode=proc.wait(timeout=30)
        result=json.loads(result_path.read_text(encoding="utf-8"))
        parsed_request=JobRequest.model_validate(request)
        parsed_result=JobResult.model_validate(result)
        validate_job_result(parsed_request,parsed_result,returncode)
        expected={"success":"succeeded","preview":"succeeded","blocked":"blocked","failed":"failed","cancelled":"cancelled"}[case]
        assert result["status"]==expected,(case,result)
        assert [e["seq"] for e in events]==list(range(1,len(events)+1))
        if result["status"]=="succeeded":
            for artifact in result["artifacts"]:
                if artifact["kind"]=="timeline":
                    Timeline.model_validate_json((root/artifact["relative_path"]).read_text(encoding="utf-8"))
        if case=="cancelled":
            assert cancel_sent and not result["artifacts"]
            assert not (root/request["output_dir"]/"export.mp4").exists()
            assert not (root/"render/.render.lock").exists()
        atomic_json(parent/(case+".progress.json"),events)
        outcomes.append({"case":case,"status":result["status"],"returncode":returncode,"progress_events":len(events),"inflight_cancel_sent":cancel_sent,"stderr":stderr,"request_path":str(request_path),"result_path":str(result_path)})
    report={"schema_version":"1.0","created_at":utcnow(),"contract_commit":"8900958 / 6a3e3deb4ff34bf4eb22f18d20e995f9e8d28e1d", "canonical_fixture":"packages/contracts/fixtures/render-request.json (same timeline and top-level shape; source asset instantiated from existing synthetic test)","checks":outcomes,"passed":True}
    atomic_json(parent/"report.json",report)
    print(json.dumps({"report":str(parent/"report.json"),"checks":outcomes},ensure_ascii=False,indent=2))


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
