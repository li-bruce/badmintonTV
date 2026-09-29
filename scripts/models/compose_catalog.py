"""Read-only probes of three real interpreters; compose exactly 11 UI cards.

No installs, model imports, GPU calls, downloads or output-file writes. Redirect
stdout deliberately after reviewing the result; probe and merge are separate.
"""
import argparse
import copy
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import sys

REPO = Path(__file__).resolve().parents[2]
PREFIXES = {name: "/mnt/d/video/runtime/models/" + folder
            for name, folder in (("base", "env"), ("yolo", "yolo-env"), ("vl", "vl-env"))}
OWNERS = {
    "base": ("query-rule-v1", "query-endpoint-v1", "qwen3-0.6b", "torchvision-keypointrcnn",
             "clip-frame-mean", "skeleton-temporal-v1", "tracknetv3-reuse",
             "torchvision-continuous-pose", "bst-cg-ap-reuse"),
    "yolo": ("yolo11n-pose-bytetrack",),
    "vl": ("qwen3-vl-embedding-2b",),
}
IDS = tuple(mid for group in OWNERS.values() for mid in group)
DISTRIBUTIONS = ("torch", "torchvision", "transformers", "av", "numpy", "Pillow", "safetensors",
                 "positional-encodings", "torchinfo", "ultralytics", "opencv-python",
                 "opencv-python-headless", "lap", "scipy", "qwen-vl-utils", "accelerate")
MODULES = ("torch", "torchvision", "transformers", "av", "numpy", "PIL", "safetensors",
           "positional_encodings", "torchinfo", "ultralytics", "cv2", "lap", "scipy", "qwen_vl_utils")
BST_REASON = ("严格输入未满足：固定真实源窗口 [3016,3068) 的52帧中25帧连续缺球，"
              "远端人体/匿名轨迹不完整；需真实连续双人COCO17、球观测、明确审阅的场地H与前/当前/后击球边界。"
              "未生成pack或执行BST；禁止补零、删失败帧、把匿名ID当姓名。")
MAX_JSON = 32_000_000


def need(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    path = Path(path)
    need(path.is_file() and path.stat().st_size <= MAX_JSON, "Missing or oversized JSON: " + str(path))
    raw = path.read_bytes()
    need(len(raw) <= MAX_JSON, "JSON grew beyond bound")
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON"))), raw


def file_reference(path, relative):
    raw = Path(path).read_bytes()
    return {"relative_path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def probe(environment):
    """Must run in the actual owning interpreter; find_spec never imports ML."""
    need(sys.platform == "linux" and os.path.isfile("/proc/sys/kernel/osrelease")
         and "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower(), "Use the actual WSL interpreter")
    need(sys.prefix == PREFIXES[environment], "Wrong interpreter prefix for " + environment)
    need(sys.flags.no_user_site and os.environ.get("PYTHONNOUSERSITE") == "1", "Use -s and PYTHONNOUSERSITE=1")
    need(not os.environ.get("PYTHONPATH"), "Clear PYTHONPATH for an interpreter-owned dependency probe")
    need(not any(name in sys.modules for name in MODULES), "Probe must start without imported ML modules")
    sys.path.insert(0, str(REPO))
    from packages.models.registry import catalog, storage_root
    import packages.models.registry as registry
    import packages.models.reuse_catalog as reuse_registry
    need(Path(registry.__file__).resolve() == REPO / "packages/models/registry.py"
         and Path(reuse_registry.__file__).resolve() == REPO / "packages/models/reuse_catalog.py", "Registry imported from another checkout")
    need(str(storage_root().resolve()) == "/mnt/d/video", "Probe requires the actual shared storage root")
    cards = catalog()["models"]
    need(len(cards) == len(IDS) and {m["model_id"] for m in cards} == set(IDS), "Registry ID set changed; update ownership explicitly")
    distributions = {}
    for name in DISTRIBUTIONS:
        try:
            dist = importlib.metadata.distribution(name)
            distributions[name] = {"version": dist.version, "location": str(dist.locate_file("").resolve())}
        except importlib.metadata.PackageNotFoundError:
            distributions[name] = None
    origins = {}
    for name in MODULES:
        spec = importlib.util.find_spec(name)
        origins[name] = spec.origin if spec is not None else None
    permitted = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
    need(all(any(Path(item["location"]).is_relative_to(parent) for parent in permitted)
             for item in distributions.values() if item), "Package metadata came from outside this interpreter or its base")
    need(all(any(Path(origin).resolve().is_relative_to(parent) for parent in permitted)
             for origin in origins.values() if origin), "ML module came from outside this interpreter or its base")
    sources = [file_reference(REPO / relative, relative) for relative in
               ("packages/models/registry.py", "packages/models/reuse_catalog.py", "scripts/models/compose_catalog.py")]
    observation = {"environment_id": environment, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
                   "storage_root": str(storage_root().resolve()),
                   "executable": sys.executable, "python": platform.python_version(), "platform": sys.platform,
                   "no_user_site": bool(sys.flags.no_user_site), "checked_at": datetime.now(timezone.utc).isoformat(),
                   "check_method": "importlib.metadata + top-level find_spec + registry manifest presence/size; no ML imports/GPU/weight hash recheck",
                   "distributions": distributions, "module_origins": origins, "source_files": sources}
    need(not any(name in sys.modules for name in MODULES), "Probe unexpectedly imported an ML module")
    selected = []
    for card in cards:
        if card["model_id"] in OWNERS[environment]:
            card = copy.deepcopy(card)
            card["environment"] = {**(card.get("environment") or {}), **observation,
                                   "kind": "wsl-venv" if environment == "yolo" else "wsl-conda"}
            selected.append(card)
    return {"schema_version": "1.0", "environment_id": environment, "observation": observation, "models": selected}


def contracts_from(repo):
    """Import the selected main contract first in a fresh merge process."""
    repo = Path(repo).resolve()
    sys.path.insert(0, str(repo))
    import packages.contracts as contracts
    need(Path(contracts.__file__).resolve().is_relative_to(repo), "Contract import cache points at another checkout; use a fresh process")
    need(Path(sys.modules["packages.contracts.models"].__file__).resolve().is_relative_to(repo), "Contract models import cache mismatch")
    return contracts


def contained(root, relative):
    need(isinstance(relative, str) and relative and "\\" not in relative, "Expected a POSIX storage-relative path")
    path = Path(relative)
    need(not path.is_absolute() and ":" not in relative and all(part not in {".", ".."} for part in relative.split("/")), "Unsafe evidence path")
    resolved = (Path(root).resolve() / path).resolve()
    need(resolved.is_relative_to(Path(root).resolve()), "Evidence path escapes storage root")
    return resolved


def job_evidence(root, relative, model_id, contracts):
    """A real platform attempt: independent request, result, exit receipt, hashes.

    Does not expose bridge token/argv/secrets, invent an exit code, or equate
    succeeded inference with accuracy. No raw feature vectors go into the card.
    """
    documents, refs = {}, {}
    for name in ("request.json", "result.json", "bridge.done.json"):
        rel = relative.rstrip("/") + "/" + name
        documents[name], raw = read_json(contained(root, rel))
        refs[name] = {"relative_path": rel, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
    request = contracts.JobRequest.model_validate(documents["request.json"]).model_dump(mode="json")
    result = contracts.JobResult.model_validate(documents["result.json"]).model_dump(mode="json")
    receipt = documents["bridge.done.json"]
    need(request["parameters"].get("model_id") == model_id and request["parameters"].get("model_version") == "0.1.0", "Evidence model/version mismatch")
    need(result["status"] == "succeeded" and result["error"] is None, "Evidence attempt did not succeed")
    need(receipt.get("compute_stopped") is True and type(receipt.get("exit_code")) is int and receipt["exit_code"] == 0
         and receipt.get("reason") == "completed", "Missing independent successful exit receipt")
    for key in ("job_id", "attempt_id"):
        need(request[key] == result[key] == receipt.get(key), "Evidence job/attempt mismatch")
    artifacts, payloads = [], {}
    for artifact in result["artifacts"]:
        producer = artifact["producer"]
        need(isinstance(producer, dict) and producer.get("model_id") == model_id and producer.get("version") == "0.1.0"
             and all(producer.get(k) == request[k] for k in ("job_id", "attempt_id")), "Artifact producer mismatch")
        artifact_path = contained(root, artifact["relative_path"])
        need(artifact_path.is_relative_to(contained(root, request["output_dir"])), "Artifact outside requested output directory")
        need(artifact["kind"] not in payloads, "Duplicate artifact kind")
        data, raw = read_json(artifact_path)
        need(len(raw) == artifact["size_bytes"] and hashlib.sha256(raw).hexdigest() == artifact["sha256"], "Artifact hash/size mismatch")
        inner = data.get("producer")
        need((isinstance(inner, dict) and all(inner.get(k) == producer[k] for k in ("model_id", "version", "job_id", "attempt_id")))
             or (inner is None and data.get("model_id") == model_id and model_id != OWNERS["vl"][0]), "Internal artifact identity mismatch")
        need(data.get("model_id", model_id) == model_id, "Internal model_id mismatch")
        artifacts.append({k: artifact[k] for k in ("kind", "relative_path", "sha256", "size_bytes")})
        payloads[artifact["kind"]] = data
    need(artifacts, "Succeeded evidence has no artifacts")
    evidence = {"job_id": result["job_id"], "attempt_id": result["attempt_id"], "status": "succeeded",
                "exit_code": 0, "compute_stopped": True, "checked_artifact_hashes": True,
                "files": refs, "artifacts": artifacts, "accuracy_validated": False}
    if model_id == OWNERS["vl"][0]:
        report, features = payloads.get("evaluation_report", {}), payloads.get("video_embedding", {})
        windows, vectors = features.get("windows", []), features.get("video_vectors", [])
        sources = {a["asset_id"]: a for a in request["assets"]}
        need(report.get("status") == "succeeded" and report.get("model_id") == model_id
             and windows and len(windows) == len(vectors) and features.get("dimension") == 2048, "VL lacks successful real video features")
        need(all(len(v) == 2048 and all(type(x) in (int, float) and math.isfinite(x) for x in v) for v in vectors), "VL video vectors malformed")
        expected = request["parameters"].get("windows", [])
        count = request["parameters"].get("num_frames", 6)
        need(type(count) is int and count in {2, 4, 6, 8} and len(expected) == len(windows)
             and report.get("windows") == windows, "VL report/request window mismatch")
        for window, wanted in zip(windows, expected):
            need(window.get("asset_id") in sources and all(window.get(k) == wanted.get(k) for k in ("asset_id", "start_ms", "end_ms")), "VL window/source mismatch")
            source = sources[window["asset_id"]]
            need(window.get("source_sha256") == source["sha256"], "VL source hash mismatch")
            start, end = Fraction(wanted["start_ms"], 1000), Fraction(wanted["end_ms"], 1000)
            points = window.get("source_points")
            need(0 <= start < end <= Fraction(source["duration_ms"], 1000)
                 and isinstance(points, list) and len(points) == count, "VL source point count/range mismatch")
            previous = None
            for index, point in enumerate(points):
                need(isinstance(point, dict) and type(point.get("pts")) is int
                     and (point.get("stream_start_pts") is None or type(point["stream_start_pts"]) is int), "VL invalid source PTS")
                try:
                    tb, stream_tb = Fraction(point["time_base"]), Fraction(point["stream_time_base"])
                    stamp = point["pts"] * tb - (point["stream_start_pts"] or 0) * stream_tb
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    raise ValueError("VL invalid source time base") from None
                need(tb > 0 and stream_tb == Fraction(source["time_base"])
                     and (previous is None or stamp > previous)
                     and start + index * (end-start)/count <= stamp < start + (index+1) * (end-start)/count,
                     "VL nonmonotonic/out-of-window PTS")
                need(point.get("original_size") == [source["width"], source["height"]]
                     and type(point.get("source_seconds")) in (int, float)
                     and abs(point["source_seconds"] - float(stamp)) < 1e-6
                     and type(point.get("window_seconds")) in (int, float)
                     and abs(point["window_seconds"] - float(stamp-start)) < 1e-6, "VL source timestamp/dimension mismatch")
                previous = stamp
        evidence["reported_versions"] = report.get("versions", {})
        evidence["real_video_window_count"] = len(windows)
    return evidence


def compose(snapshots, evidence=None):
    """Pure metadata composition; never asks the merge Python about ML packages."""
    evidence = evidence or {}
    need(set(snapshots) == set(OWNERS), "Require base, yolo and vl snapshots; never borrow another environment's status")
    need(set(evidence) <= set(IDS), "Unknown evidence model ID")
    cards, source_signature = [], None
    for owner, expected in OWNERS.items():
        snapshot = snapshots[owner]
        observation = snapshot["observation"]
        need(snapshot.get("environment_id") == observation.get("environment_id") == owner
             and observation.get("prefix") == PREFIXES[owner] and observation.get("platform") == "linux"
             and observation.get("storage_root") == "/mnt/d/video"
             and observation.get("no_user_site") is True, "Snapshot interpreter identity mismatch")
        signature = observation.get("source_files")
        need(signature and (source_signature is None or signature == source_signature), "Probe code differs between environments")
        source_signature = signature
        raw = snapshot["models"]
        need(len(raw) == len(expected) and {m["model_id"] for m in raw} == set(expected), "Duplicate/missing/wrong-owner cards")
        for model in raw:
            card = copy.deepcopy(model)
            need(all(card["environment"].get(k) == v for k, v in observation.items()), "Card did not originate in the claimed interpreter")
            mid = card["model_id"]
            card["evaluation_report"] = {"documentation": card.get("evaluation_report"), "execution_evidence": evidence.get(mid),
                                         "accuracy_validated": False}
            if mid == "bst-cg-ap-reuse":
                card["environment"]["registry_status_before_input_gate"] = card["status"]
                card["status"], card["reason"] = "unavailable", BST_REASON
                card["evaluation_report"]["input_review"] = "docs/experiments/models-bst-new-source-review-001.md"
            elif mid == OWNERS["yolo"][0] and card["status"] == "experimental":
                version = (observation["distributions"].get("ultralytics") or {}).get("version")
                if version != "8.3.203":
                    card["status"], card["reason"] = "unavailable", "真实yolo-env的Ultralytics版本不是固定8.3.203；需要重新验证环境"
            elif mid == OWNERS["vl"][0]:
                need(card["status"] in {"experimental", "not_installed", "unavailable"}, "VL cannot enter catalog as ready")
                packages = observation["distributions"]
                actual = {key: (packages.get(key) or {}).get("version") for key in ("torch", "torchvision", "transformers", "qwen-vl-utils")}
                pinned = bool(actual["torch"] and actual["torch"].split("+")[0] == "2.8.0"
                              and actual["torchvision"] and actual["torchvision"].split("+")[0] == "0.23.0"
                              and actual["transformers"] == "4.57.3" and actual["qwen-vl-utils"] == "0.0.14")
                execution = evidence.get(mid)
                if card["status"] == "experimental" and not pinned:
                    card["status"], card["reason"] = "unavailable", "真实vl-env依赖版本不满足固定适配器；不得用旧env或Windows状态替代"
                elif card["status"] == "experimental" and not execution:
                    card["status"], card["reason"] = "unavailable", "真实vl-env仅完成元数据检查；尚无已核验request/result/exit/产物hash的真实视频前向证据"
                elif card["status"] == "experimental":
                    need(execution.get("real_video_window_count", 0) > 0 and all(execution.get("reported_versions", {}).get(k) == v for k, v in actual.items()), "VL run and current environment versions differ")
                    card["reason"] = "真实vl-env及有界视频前向证据已核验；中文排序/细动作准确率与完整比赛吞吐未经真值验证"
            cards.append(card)
    need(len(cards) == 11 and {c["model_id"] for c in cards} == set(IDS), "Expected exactly 11 cards")
    return {"schema_version": "1.0", "models": cards}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--environment", required=True, choices=PREFIXES)
    m = sub.add_parser("merge")
    for owner in PREFIXES:
        m.add_argument("--" + owner, type=Path, required=True)
    m.add_argument("--storage-root", type=Path, required=True)
    m.add_argument("--contracts-repo", type=Path, required=True)
    m.add_argument("--evidence", action="append", default=[], metavar="MODEL_ID=PLATFORM_ATTEMPT_RELATIVE_DIR")
    args = parser.parse_args(argv)
    if args.command == "probe":
        output = probe(args.environment)
    else:
        contracts = contracts_from(args.contracts_repo)
        evidence = {}
        for item in args.evidence:
            mid, separator, relative = item.partition("=")
            need(separator and mid in IDS and mid not in evidence, "Malformed/duplicate evidence option")
            evidence[mid] = job_evidence(args.storage_root, relative, mid, contracts)
        output = compose({owner: read_json(getattr(args, owner))[0] for owner in PREFIXES}, evidence)
        contract_source = file_reference(Path(args.contracts_repo) / "packages/contracts/models.py", "packages/contracts/models.py")
        for card in output["models"]:
            card["environment"]["validation_contract"] = {"checkout": str(Path(args.contracts_repo).resolve()), **contract_source}
            contracts.ModelManifest.model_validate(card)
    print(json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
