"""Offline Qwen QuerySpec diagnostic, not user-query or video-truth evaluation.

From the repository, in the isolated WSL model environment:
  python scripts/models/query_benchmark.py \
    --output-dir models/handoff/query-diagnostic-001
  python scripts/models/query_benchmark.py \
    --output-dir models/handoff/query-diagnostic-002 \
    --prompt-file configs/models/query-fewshot-prompt.txt

BTV_STORAGE_ROOT selects the controlled data root (default /mnt/d/video on
Linux). Outputs are exclusively created, never overwritten. Install/download
weights separately; this program cannot implicitly fetch missing components.
It loads one bf16 CUDA model and records all 24 authored probes, including
failures. A matching JSON schema is not video recognition accuracy.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import signal
import statistics
import sys
import time
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from packages.models.inference import get_torch, weights_dir
from packages.models.protocol import InvalidRequest, ModelBlocked, atomic_write_json, resolve_relative, storage_root
from packages.models.query import QUERY_SYSTEM_PROMPT, QueryParseError, parse_rule, validate_query, validate_semantics
from packages.models.storage import reserve

PROBES_PATH = REPO / "configs/models/query-probes.json"
MODEL_ID = "qwen3-0.6b"
MODEL_SOURCE = "https://huggingface.co/Qwen/Qwen3-0.6B"
CATEGORIES = frozenset({"single_stroke", "footwork", "combination", "sequence", "unknown"})
RESERVATION_BYTES = 100_000_000
MAX_NEW_TOKENS = 768


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def read_json(path: Path, limit: int = 2_000_000) -> dict[str, Any]:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("JSON input exceeds bounded size")
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)


def load_probes() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build references from explicit authored conditions, then check grammar."""
    dataset = read_json(PROBES_PATH, 200_000)
    if set(dataset) != {"schema_version", "dataset_id", "provenance", "probes"} or dataset["schema_version"] != "1.0":
        raise ValueError("invalid diagnostic dataset schema")
    provenance = dataset["provenance"]
    if provenance.get("origin") != "developer_authored_diagnostic" or provenance.get("is_user_corpus") is not False or provenance.get("is_video_ground_truth") is not False:
        raise ValueError("diagnostic provenance must explicitly exclude user corpus and video truth")
    probes = dataset["probes"]
    if not isinstance(probes, list) or not 20 <= len(probes) <= 24:
        raise ValueError("diagnostic must contain 20 to 24 probes")
    prepared, ids, categories = [], set(), set()
    for probe in probes:
        if set(probe) != {"probe_id", "category", "text", "expected"}:
            raise ValueError("invalid diagnostic probe fields")
        probe_id, category = probe["probe_id"], probe["category"]
        if not isinstance(probe_id, str) or not re.fullmatch(r"[a-z]+-[0-9]{2}", probe_id) or probe_id in ids or category not in CATEGORIES:
            raise ValueError("invalid probe ID or category")
        ids.add(probe_id)
        categories.add(category)
        expected = probe["expected"]
        if set(expected) != {"steps", "relations", "include_uncertain"}:
            raise ValueError("invalid authored expected conditions")
        steps = []
        for index, step in enumerate(expected["steps"]):
            if set(step) != {"kind", "labels"}:
                raise ValueError("invalid authored step")
            steps.append({"step_id": f"step-{index + 1}", **step})
        relations = []
        for relation in expected["relations"]:
            if set(relation) != {"from_index", "to_index", "relation", "max_gap_ms"}:
                raise ValueError("invalid authored relation")
            a, b = relation["from_index"], relation["to_index"]
            if type(a) is not int or type(b) is not int or not 0 <= a < len(steps) or not 0 <= b < len(steps):
                raise ValueError("authored relation index outside steps")
            relations.append({"from_step": steps[a]["step_id"], "to_step": steps[b]["step_id"],
                              "relation": relation["relation"], "max_gap_ms": relation["max_gap_ms"],
                              "same_player": True, "same_rally": True})
        reference = validate_query({"schema_version": "1.0", "query_id": probe_id, "text": probe["text"],
                                    "player_id": None, "scope": {key: [] for key in ("library_ids", "asset_ids", "match_ids", "source_types")},
                                    "steps": steps, "relations": relations, "include_uncertain": expected["include_uncertain"]})
        rule, warnings = parse_rule(probe["text"], query_id=probe_id)
        validate_semantics(rule, reference)
        prepared.append({"probe_id": probe_id, "category": category, "text": probe["text"],
                         "reference": reference, "rule_warnings": warnings})
    if categories != CATEGORIES:
        raise ValueError("all five diagnostic categories must be represented")
    return dataset, prepared


def load_prompt(prompt_file: str | None, probes: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Read only bounded repository-owned text; keep the baseline unchanged."""
    baseline_hash = hashlib.sha256(QUERY_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    if prompt_file is None:
        return QUERY_SYSTEM_PROMPT, {"mode": "baseline", "relative_path": None, "file_sha256": None,
                                     "baseline_prompt_sha256": baseline_hash, "fewshot_inputs": [],
                                     "development_note": "Fixed developer-authored diagnostic; not an independent real-user evaluation"}
    if not isinstance(prompt_file, str) or not prompt_file.startswith("configs/models/"):
        raise InvalidRequest("prompt-file must be a relative text file under repository configs/models/", "invalid_prompt_file")
    path = resolve_relative(REPO, prompt_file)
    try:
        path.relative_to((REPO / "configs/models").resolve())
    except ValueError:
        raise InvalidRequest("prompt-file resolves outside repository configs/models/", "invalid_prompt_file") from None
    if path.suffix.lower() != ".txt" or not path.is_file():
        raise InvalidRequest("prompt-file must be an existing .txt file", "invalid_prompt_file")
    with path.open("rb") as stream:
        data = stream.read(32_769)
    if len(data) > 32_768:
        raise InvalidRequest("prompt-file exceeds 32 KiB", "invalid_prompt_file")
    try:
        prompt = data.decode("utf-8")
    except UnicodeError:
        raise InvalidRequest("prompt-file must be UTF-8 text", "invalid_prompt_file") from None
    if not prompt.strip() or "\x00" in prompt:
        raise InvalidRequest("prompt-file must contain nonempty text without NUL", "invalid_prompt_file")
    examples = re.findall(r"^示例输入：([^\r\n]+)$", prompt, re.MULTILINE)
    normalize = lambda value: re.sub(r"[\s，,、；;。.]", "", value)
    probe_texts = {normalize(probe["text"]) for probe in probes}
    if any(normalize(example) in probe_texts for example in examples):
        raise InvalidRequest("A few-shot example duplicates a scored diagnostic probe; use disjoint examples", "fewshot_probe_overlap")
    return prompt, {"mode": "explicit_prompt_file", "relative_path": prompt_file,
                    "file_sha256": hashlib.sha256(data).hexdigest(), "baseline_prompt_sha256": baseline_hash,
                    "fewshot_inputs": examples, "fewshot_probe_overlap": False,
                    "development_note": "Prompt-debugging experiment after baseline inspection; this diagnostic set is a development set, not an independent held-out evaluation. Exact few-shot inputs are excluded from scored probes."}


class Writer:
    """Bound permanent JSON to 40 MB, leaving space for atomic publication."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.written_bytes = 0

    def write(self, name: str, payload: Any) -> None:
        size = len((json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8"))
        if size > 2_000_000 or self.written_bytes + size > 40_000_000:
            raise OSError("diagnostic JSON output exceeds reserved writer bound")
        atomic_write_json(self.folder / name, payload)
        self.written_bytes += size


def offline_environment(root: Path) -> None:
    # No dependency/model fetches; cache paths are controlled even if a library
    # writes local metadata. No torch.compile/JIT path is enabled in this test.
    cache = resolve_relative(root, "models/cache/query-diagnostic", owner="models")
    settings = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "TOKENIZERS_PARALLELISM": "false",
                "CUDA_CACHE_DISABLE": "1", "HF_HOME": str(cache / "huggingface"),
                "TORCH_HOME": str(cache / "torch"), "TMPDIR": str(cache / "tmp"),
                "TEMP": str(cache / "tmp"), "TMP": str(cache / "tmp"),
                "TORCHINDUCTOR_CACHE_DIR": str(cache / "inductor"), "TRITON_CACHE_DIR": str(cache / "triton")}
    cache.joinpath("tmp").mkdir(parents=True, exist_ok=True)
    for key, value in settings.items():
        os.environ[key] = value


def package_versions() -> dict[str, Any]:
    versions = {"python": sys.version.split()[0], "platform": sys.platform}
    for package in ("torch", "transformers", "tokenizers", "safetensors", "huggingface-hub", "accelerate"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def verified_source(root: Path) -> tuple[Path, dict[str, Any]]:
    folder = weights_dir(root, MODEL_ID)  # validates every required local hash
    manifest_path = folder / "weights-manifest.json"
    manifest = read_json(manifest_path)
    revision = manifest.get("revision")
    if manifest.get("source") != MODEL_SOURCE or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ModelBlocked("WEIGHT_SOURCE_UNPINNED", "Expected official Qwen source and fixed 40-character commit revision")
    prefix = MODEL_SOURCE + "/resolve/" + revision + "/"
    if any(not isinstance(item.get("source_url"), str) or not item["source_url"].startswith(prefix) for item in manifest["files"]):
        raise ModelBlocked("WEIGHT_SOURCE_UNPINNED", "Every model file must refer to the same fixed official revision")
    return folder, {"source": manifest["source"], "revision": revision, "license_url": manifest.get("license_url"),
                    "manifest_relative_path": manifest_path.relative_to(root).as_posix(),
                    "manifest_sha256": digest(manifest_path), "files": manifest["files"]}


def empty_record(probe: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "1.0", **probe, "outcome": "blocked", "error": None,
            "raw_generation": None, "parsed_query": None, "schema_valid": False, "semantic_match": False,
            "inference_attempted": False, "input_tokens": None, "generated_tokens": None,
            "reached_token_limit": None, "generation_seconds": None, "elapsed_seconds": None,
            "peak_allocated_bytes": None, "peak_reserved_bytes": None,
            "environment_reference": "run-metadata.json", "is_video_evidence": False}


def run_probe(probe: dict[str, Any], tokenizer: Any, model: Any, torch: Any,
              system_prompt: str = QUERY_SYSTEM_PROMPT) -> dict[str, Any]:
    record = empty_record(probe)
    record["started_at"] = now()
    started = time.perf_counter()
    inputs = generated = output_ids = None
    try:
        torch.cuda.reset_peak_memory_stats()
        prompt = tokenizer.apply_chat_template(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": probe["text"]}],
            tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
        record["input_tokens"] = int(inputs["input_ids"].shape[1])
        torch.cuda.synchronize()
        generation_started = time.perf_counter()
        record["inference_attempted"] = True
        with torch.inference_mode():
            generated = model.generate(**inputs, do_sample=False, max_new_tokens=MAX_NEW_TOKENS)
        torch.cuda.synchronize()
        record["generation_seconds"] = time.perf_counter() - generation_started
        output_ids = generated[0, record["input_tokens"]:]
        record["generated_tokens"] = int(output_ids.shape[0])
        record["reached_token_limit"] = record["generated_tokens"] >= MAX_NEW_TOKENS
        raw = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
        record["raw_generation"] = raw
        try:
            candidate = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
        except (ValueError, RecursionError):
            raise QueryParseError("invalid_generated_json", "Generated text is not one complete strict JSON object") from None
        parsed = validate_query(candidate)
        record["schema_valid"] = True
        record["parsed_query"] = parsed
        validated = validate_semantics(parsed, probe["reference"])
        record.update(outcome="passed", semantic_match=True, parsed_query=validated)
    except QueryParseError as error:
        record.update(outcome="failed", error={"code": error.code, "message": str(error)})
    except torch.cuda.OutOfMemoryError:
        record.update(outcome="failed", error={"code": "CUDA_OUT_OF_MEMORY", "message": "CUDA allocation failed during this probe"})
    except KeyboardInterrupt:
        record.update(outcome="failed", error={"code": "CANCELLED", "message": "This probe was interrupted; no completed generation is asserted"})
    except Exception as error:
        # Avoid dumping library exceptions, host paths, environment or secrets.
        record.update(outcome="failed", error={"code": "INFERENCE_FAILED", "message": "Local generation failed", "exception_type": type(error).__name__})
    finally:
        record["elapsed_seconds"] = time.perf_counter() - started
        record["finished_at"] = now()
        try:
            record["peak_allocated_bytes"] = int(torch.cuda.max_memory_allocated())
            record["peak_reserved_bytes"] = int(torch.cuda.max_memory_reserved())
        except Exception:
            pass
        del output_ids, generated, inputs
    if record["error"] and record["error"]["code"] == "CUDA_OUT_OF_MEMORY":
        torch.cuda.empty_cache()
    return record


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(record["outcome"] for record in records)
    attempted = sum(record["inference_attempted"] for record in records)
    categories = {}
    for category in sorted(CATEGORIES):
        selected = [record for record in records if record["category"] == category]
        categories[category] = {"total": len(selected), **{key: sum(r["outcome"] == key for r in selected) for key in ("passed", "failed", "blocked")}}
    elapsed = [r["elapsed_seconds"] for r in records if r["elapsed_seconds"] is not None]
    tokens = sum(r["generated_tokens"] or 0 for r in records)
    generation_seconds = sum(r["generation_seconds"] or 0 for r in records)
    return {"total": len(records), "passed": counts["passed"], "failed": counts["failed"], "blocked": counts["blocked"],
            "inference_attempted": attempted, "by_category": categories,
            "schema_valid": sum(r["schema_valid"] for r in records),
            "semantic_matches": sum(r["semantic_match"] for r in records),
            "diagnostic_exact_match_fraction": counts["passed"] / attempted if attempted else None,
            "exact_match_denominator": "inference_attempted",
            "generated_tokens": tokens, "generation_seconds": generation_seconds,
            "tokens_per_generation_second": tokens / generation_seconds if generation_seconds else None,
            "median_probe_seconds": statistics.median(elapsed) if elapsed else None,
            "peak_allocated_bytes": max((r["peak_allocated_bytes"] or 0 for r in records), default=0) or None,
            "peak_reserved_bytes": max((r["peak_reserved_bytes"] or 0 for r in records), default=0) or None,
            "video_accuracy": None, "retrieval_accuracy": None, "general_language_accuracy": None,
            "metric_caveat": "Exact agreement on these authored grammar probes only; blocked probes are not inference trials. No estimate of real-user or video performance."}


def run(output_relative: str, prompt_file: str | None = None) -> int:
    root = storage_root()
    output = resolve_relative(root, output_relative, owner="models")
    dataset, probes = load_probes()
    system_prompt, prompt_source = load_prompt(prompt_file, probes)
    if output.exists():
        raise FileExistsError("output directory already exists; choose a new diagnostic attempt")
    started, started_at = time.perf_counter(), now()
    records, fatal_error, model_load_seconds = [], None, None
    cancelled = False
    with reserve(root, RESERVATION_BYTES):
        output.mkdir(parents=True, exist_ok=False)
        writer = Writer(output)
        metadata = {"schema_version": "1.0", "model_id": MODEL_ID, "started_at": started_at,
                    "dataset_id": dataset["dataset_id"], "provenance": dataset["provenance"],
                    "probe_count": len(probes), "probe_manifest_sha256": digest(PROBES_PATH),
                    "script_sha256": digest(Path(__file__)), "query_module_sha256": digest(REPO / "packages/models/query.py"),
                    "system_prompt": system_prompt, "system_prompt_source": prompt_source,
                    "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
                    "generation": {"dtype": "bfloat16", "device": "cuda", "enable_thinking": False,
                                   "do_sample": False, "max_new_tokens": MAX_NEW_TOKENS, "seed": 0,
                                   "label": "greedy reproducibility diagnostic; not best-possible decoding",
                                   "reproducibility_caveat": "Greedy config is fixed; bitwise determinism across CUDA/hardware/library versions is not asserted"},
                    "official_non_thinking_recommendation": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0,
                                                              "source": MODEL_SOURCE + "#best-practices", "checked_at": "2026-09-28", "used_in_this_run": False},
                    "local_files_only": True, "trust_remote_code": False, "versions": package_versions(),
                    "source_manifest": None, "reservation_bytes": RESERVATION_BYTES, "gpu_lease_note": "Run only during models-owned GPU schedule; this script does not terminate other GPU processes"}
        try:
            offline_environment(root)
            folder, source = verified_source(root)
            metadata["source_manifest"] = source
            torch = get_torch()
            if not torch.cuda.is_bf16_supported():
                raise ModelBlocked("BF16_UNAVAILABLE", "This fixed diagnostic requires CUDA bf16 support")
            from transformers import AutoModelForCausalLM, AutoTokenizer
            torch.manual_seed(0)
            metadata["versions"].update(torch=str(torch.__version__), cuda_build=torch.version.cuda,
                                         gpu_name=torch.cuda.get_device_name(), compute_capability=list(torch.cuda.get_device_capability()))
            load_started = time.perf_counter()
            tokenizer = AutoTokenizer.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False)
            model = AutoModelForCausalLM.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False,
                                                        use_safetensors=True, torch_dtype=torch.bfloat16).to("cuda").eval()
            torch.cuda.synchronize()
            model_load_seconds = time.perf_counter() - load_started
            metadata.update(model_load_seconds=model_load_seconds,
                            load_peak_allocated_bytes=int(torch.cuda.max_memory_allocated()),
                            load_peak_reserved_bytes=int(torch.cuda.max_memory_reserved()))
            writer.write("run-metadata.json", metadata)
            for index, probe in enumerate(probes):
                record = run_probe(probe, tokenizer, model, torch, system_prompt=system_prompt)
                writer.write(probe["probe_id"] + ".json", record)
                records.append(record)
                print(json.dumps({"probe_id": probe["probe_id"], "current": index + 1, "total": len(probes),
                                  "outcome": record["outcome"], "error_code": record["error"]["code"] if record["error"] else None}), flush=True)
                if record["error"] and record["error"]["code"] == "CANCELLED":
                    cancelled = True
                    fatal_error = record["error"]
                    break
                if record["error"] and record["error"]["code"] == "INFERENCE_FAILED":
                    fatal_error = {"code": "GENERATION_RUNTIME_UNAVAILABLE", "message": "Stopped further trials after a generation runtime error; completed results are retained"}
                    break
        except ModelBlocked as error:
            fatal_error = {"code": error.code, "message": error.message}
        except ImportError:
            fatal_error = {"code": "DEPENDENCY_NOT_INSTALLED", "message": "Use the isolated model environment with torch and transformers installed"}
        except KeyboardInterrupt:
            cancelled = True
            fatal_error = {"code": "CANCELLED", "message": "Diagnostic interrupted; completed probe files are retained"}
        except Exception as error:
            fatal_error = {"code": "DIAGNOSTIC_EXECUTION_FAILED", "message": "Model loading or diagnostic execution failed", "exception_type": type(error).__name__}
        if not (output / "run-metadata.json").exists():
            metadata.update(model_load_seconds=model_load_seconds, setup_error=fatal_error)
            writer.write("run-metadata.json", metadata)
        # Not attempted is distinct from a generated but invalid prediction.
        for probe in probes[len(records):]:
            record = empty_record(probe)
            record["error"] = fatal_error or {"code": "NOT_ATTEMPTED", "message": "Probe was not executed"}
            writer.write(probe["probe_id"] + ".json", record)
            records.append(record)
        totals = summary(records)
        status = "cancelled" if cancelled else "blocked" if fatal_error and not totals["inference_attempted"] else "completed_with_failures" if fatal_error or totals["failed"] or totals["blocked"] else "completed"
        report = {"schema_version": "1.0", "model_id": MODEL_ID, "dataset_id": dataset["dataset_id"],
                  "status": status, "started_at": started_at, "finished_at": now(),
                  "wall_seconds": time.perf_counter() - started, "model_load_seconds": model_load_seconds,
                  "overall_peak_allocated_bytes": max(metadata.get("load_peak_allocated_bytes", 0), totals["peak_allocated_bytes"] or 0) or None,
                  "overall_peak_reserved_bytes": max(metadata.get("load_peak_reserved_bytes", 0), totals["peak_reserved_bytes"] or 0) or None,
                  "provenance": dataset["provenance"], "summary": totals, "fatal_error": fatal_error,
                  "system_prompt_source": prompt_source, "system_prompt_sha256": metadata["system_prompt_sha256"],
                  "run_metadata": "run-metadata.json", "probe_records": [r["probe_id"] + ".json" for r in records],
                  "raw_generation_policy": "Only this local authored query set was used; raw generations remain in this controlled local output directory",
                  "interpretation": "No fallback to rules when Qwen fails. This run measures exact condition fidelity for the fixed prompt and greedy configuration; it is not a best-possible model score, real-user benchmark or video-ground-truth evaluation."}
        writer.write("report.json", report)
        print(json.dumps({"status": status, "report": output_relative + "/report.json", "summary": totals}, ensure_ascii=False), flush=True)
    return 130 if cancelled else 2 if status == "blocked" else 1 if status == "completed_with_failures" else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", required=True, help="New relative directory under models/, e.g. models/handoff/query-diagnostic-001")
    parser.add_argument("--prompt-file", help="Optional repository-relative UTF-8 .txt under configs/models/; default retains the original baseline prompt")
    args = parser.parse_args(argv)
    def cancel(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, cancel)
    try:
        return run(args.output_dir, prompt_file=args.prompt_file)
    except InvalidRequest as error:
        print(json.dumps({"status": "failed", "error": {"code": error.code, "message": str(error)}}), file=sys.stderr)
        return 1
    except FileExistsError:
        print(json.dumps({"status": "blocked", "error": {"code": "OUTPUT_OR_RESERVATION_EXISTS", "message": "Existing outputs or active writer reservation were preserved"}}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(json.dumps({"status": "failed", "error": {"code": "DIAGNOSTIC_SETUP_FAILED", "message": "Invalid diagnostic fixture, unavailable storage or output publication failure", "exception_type": type(error).__name__}}), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
