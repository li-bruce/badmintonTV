"""Portable model-environment planner/doctor. Standard library, no model imports.

Installation is opt-in, serialized, new-prefix only, and WSL Ubuntu only.
Native Linux gets a plan/doctor; it is not silently promoted to supported training.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
PROFILE_FILE = REPO / "environments/models-device-profiles.json"
PROFILES = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))["profiles"]
GB = 1_000_000_000
LIMITS = {"data": 300*GB, "platform": 60*GB, "models": 180*GB,
          "render": 40*GB, "runtime": 70*GB}


def absolute_path(value, field):
    if not value or any(ord(c) < 32 for c in str(value)):
        raise ValueError(field + " must be a nonempty path without control characters")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(field + " must be an absolute path without '..'")
    # Do not normalize away a link before checking it. All configured output
    # ancestors must be real directories, so a moved root cannot redirect writes.
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError(field + " must not contain symlink ancestors")
    return path.resolve()


def build_plan(profile, storage_root, env_prefix=None, conda_executable=None):
    root = absolute_path(storage_root, "storage-root")
    if root == Path(root.anchor):
        raise ValueError("storage-root must be a dedicated data directory")
    owner = root / "runtime/models"
    prefix = absolute_path(env_prefix or owner / "envs" / profile, "env-prefix")
    if not prefix.is_relative_to(owner) or prefix == owner:
        raise ValueError("env-prefix must be below storage-root/runtime/models")
    cache = owner / "device-cache" / profile
    # The prefix must not overlap caches, lock or metadata directories.
    if prefix.is_relative_to(owner / "device-cache") or prefix.is_relative_to(owner / "device-reports"):
        raise ValueError("env-prefix overlaps reserved installer directories")
    for item in (owner, cache, root / "models/cache"):
        absolute_path(item, "derived output")
    conda = absolute_path(conda_executable, "conda-executable") if conda_executable else None
    if conda and (conda.name != "conda" or conda.parent.name != "bin"):
        raise ValueError("conda-executable must identify an existing <installation>/bin/conda")
    spec = PROFILES[profile]
    requirement = REPO / spec["requirements"]
    env = {
        "BTV_STORAGE_ROOT": str(root), "BTV_MODELS_ENV": str(prefix),
        "HF_HOME": str(root / "models/cache/huggingface"),
        "TORCH_HOME": str(root / "models/cache/torch"),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "CONDA_PKGS_DIRS": str(cache / "conda-pkgs"),
        "CONDA_ENVS_PATH": str(owner / "envs"),
        "CONDA_NO_PLUGINS": "true", "CONDA_AUTO_UPDATE_CONDA": "false",
        "CONDARC": os.devnull, "CONDA_REGISTER_ENVS": "false", "CONDA_NUMBER_CHANNEL_NOTICES": "0",
        "CONDA_NOTIFY_OUTDATED_CONDA": "false", "CONDA_REPORT_ERRORS": "false",
        "PIP_CACHE_DIR": str(cache / "pip"), "XDG_CACHE_HOME": str(cache / "xdg"),
        "TMPDIR": str(cache / "tmp"), "TMP": str(cache / "tmp"), "TEMP": str(cache / "tmp"),
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1", "PIP_INDEX_URL": "https://pypi.org/simple",
    }
    if not spec["gpu_required"]:
        env["CUDA_VISIBLE_DEVICES"] = ""
    python = str(prefix / "bin/python")
    pip = [python, "-s", "-B", "-m", "pip"]
    commands = [[str(conda) if conda else "<conda-executable-required>", "create", "--yes",
                 "--prefix", str(prefix), "--override-channels", "-c", "conda-forge",
                 "--solver", "classic", "python=3.11", "pip"]]
    if spec["torch"]:
        commands.append(pip + ["install", "--no-cache-dir", "--no-compile", "--only-binary=:all:",
                              "torch==" + spec["torch"], "torchvision==" + spec["torchvision"],
                              "--index-url", "https://download.pytorch.org/whl/cu128"])
    commands += [pip + ["install", "--no-cache-dir", "--no-compile", "--only-binary=:all:",
                       "--index-url", "https://pypi.org/simple", "-r", str(requirement)], pip + ["check"]]
    return {"schema_version": "1.0", "profile": profile, "status": "plan_only",
            "storage_root": str(root), "env_prefix": str(prefix), "conda_executable": str(conda) if conda else None,
            "environment": env, "commands": commands, "peak_bytes": spec["peak_bytes"],
            "requirements": spec["requirements"],
            "requirements_sha256": hashlib.sha256(requirement.read_bytes()).hexdigest(),
            "gpu_required": spec["gpu_required"], "training_loop": "not_implemented",
            "model_status": "unavailable", "model_reason": "Weights, model source locks and evaluation are separate handoffs.",
            "installation_verified_on_new_device": False}


def child_environment(plan):
    # Remove inherited interpreter/pip/Conda overrides and user package paths.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "PIP_", "CONDA_", "HF_", "TORCH_"))
           and k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "LD_PRELOAD", "LD_LIBRARY_PATH", "CONDARC")}
    env.update(plan["environment"])
    return env


def measure(path, exclude=None):
    if not path.exists():
        return 0
    argv = ["du", "-sb"]
    if exclude:
        argv.append("--exclude=" + str(exclude))
    argv += ["--", str(path)]
    result = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=90)
    return int(result.stdout.split("\t", 1)[0])


def capacity(plan, *, peak=None, measure_fn=measure, disk_fn=shutil.disk_usage):
    root = Path(plan["storage_root"])
    if not root.is_dir():
        raise ValueError("storage-root must already exist; create the intended data root explicitly")
    peak = plan["peak_bytes"] if peak is None else peak
    if measure_fn is measure:
        # One traversal: a large existing runtime must not be scanned repeatedly.
        scan = subprocess.run(["du", "-b", "--max-depth=2", "--", str(root)],
                              check=True, capture_output=True, text=True, timeout=180)
        sizes = {}
        for line in scan.stdout.splitlines():
            size, path = line.split("\t", 1)
            sizes[Path(path)] = int(size)
        measure_fn = lambda path, exclude=None: sizes.get(path, 0)
        external_measure = measure
    else:
        external_measure = measure_fn
    usage = {key: measure_fn(root / key) for key in LIMITS}
    total = measure_fn(root)
    model_runtime = measure_fn(root / "runtime/models")
    shared = measure_fn(root / "runtime/shared")
    external = 0
    conda = plan["conda_executable"]
    if conda:
        base = Path(conda).parents[1]
        if not base.is_relative_to(root):
            external = external_measure(base, base / "envs")
    free = disk_fn(root).free
    unowned = max(0, total - sum(usage.values()))
    checks = {key + "_quota": usage[key] + (peak + external if key == "runtime" else 0) <= limit
              for key, limit in LIMITS.items()}
    checks.update(models_runtime_35GB=model_runtime + peak <= 35*GB,
                  shared_conda_15GB=shared + external <= 15*GB,
                  global_actual_700GB=total + external + peak <= 700*GB,
                  global_allocations_700GB=sum(LIMITS.values()) + unowned <= 700*GB,
                  disk_free_margin=free >= peak + 5*GB)
    return {"passed": all(checks.values()), "checks": checks, "usage_bytes": usage,
            "models_runtime_bytes": model_runtime, "external_conda_base_bytes": external,
            "unowned_bytes": unowned, "total_bytes": total, "free_bytes": free, "reserved_peak_bytes": peak,
            "accounting": "Fixed disjoint owner quotas; external Conda base/packages count toward shared 15GB. No database access."}


def host_status():
    release = platform.release().lower()
    try:
        os_release = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        os_release = ""
    wsl = "microsoft" in release or "wsl" in release
    ubuntu = any(line in ('ID=ubuntu', 'ID="ubuntu"') for line in os_release.splitlines())
    return {"system": platform.system(), "machine": platform.machine(), "wsl": wsl,
            "ubuntu": ubuntu, "apply_supported": sys.platform == "linux" and wsl and ubuntu
            and platform.machine() == "x86_64"}


PROBE = """
import importlib.metadata as m, json, sys
result={}
for name in json.loads(sys.argv[1]):
    try: result[name]={'status':'installed','version':m.version(name)}
    except m.PackageNotFoundError: result[name]={'status':'not_installed'}
print(json.dumps({'packages':result,'prefix':sys.prefix,'base_prefix':sys.base_prefix,
                  'model_imported':'torch' in sys.modules,'python':list(sys.version_info[:2])}))
"""


def doctor(plan):
    result = {"host": host_status(), "conda": "not_installed", "environment": "not_installed",
              "gpu": "not_required" if not plan["gpu_required"] else "unavailable",
              "models": {"status": "unavailable", "reason": "Model weights/source locks and real inference must be checked separately."},
              "training_loop": "not_implemented"}
    conda = plan["conda_executable"]
    if conda and Path(conda).is_file() and os.access(conda, os.X_OK):
        result["conda"] = "available"
    python = Path(plan["env_prefix"]) / "bin/python"
    if python.is_file():
        try:
            proc = subprocess.run([str(python), "-s", "-B", "-c", PROBE, json.dumps(PROFILES[plan["profile"]]["packages"])],
                                  env=child_environment(plan), capture_output=True, text=True, timeout=30, check=True)
            result["environment_probe"] = json.loads(proc.stdout)
            probe = result["environment_probe"]
            pinned = {}
            for line in (REPO / plan["requirements"]).read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#"):
                    name, version = line.split("==", 1)
                    pinned[name.replace("_", "-").lower()] = version
            versions_match = all(p.get("version") == pinned.get(name.replace("_", "-").lower())
                                 for name, p in probe["packages"].items())
            good = (versions_match and all(p["status"] == "installed" for p in probe["packages"].values())
                    and Path(probe["prefix"]).resolve() == Path(plan["env_prefix"])
                    and probe["prefix"] == probe["base_prefix"] and probe["python"] == [3, 11])
            result["environment"] = "installed" if good else "unavailable"
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result["environment"] = "unavailable"
            result["environment_reason"] = type(exc).__name__
    smi = shutil.which("nvidia-smi")
    if plan["gpu_required"] and smi:
        proc = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=15, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            result["gpu"] = "visible_not_compute_tested"
            result["gpu_inventory"] = proc.stdout.strip().splitlines()
    return result


def stop_child(proc):
    # Only the process group created by this installer, never other GPU jobs.
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)


def installation_bytes(plan):
    return measure(Path(plan["env_prefix"])) + measure(Path(plan["environment"]["CONDA_PKGS_DIRS"]).parent)


def bounded_command(argv, plan, log, baseline):
    root = Path(plan["storage_root"])
    started = time.monotonic()
    with log.open("ab") as output:
        proc = subprocess.Popen(argv, env=child_environment(plan), stdout=output, stderr=subprocess.STDOUT,
                                start_new_session=True)  # argv only; never shell=True
        try:
            while True:
                try:
                    code = proc.wait(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    # Leave 10% of the reserved peak as a write/measurement margin.
                    used = installation_bytes(plan) - baseline
                    if (used >= int(plan["peak_bytes"] * .9) or log.stat().st_size > 8*1024*1024
                            or shutil.disk_usage(root).free < 5*GB or time.monotonic() - started > 7200):
                        raise RuntimeError("installation byte/log/time budget exceeded; partial files retained")
        finally:
            stop_child(proc)
    if code:
        raise RuntimeError("installer command failed; inspect retained log (exit " + str(code) + ")")
    if installation_bytes(plan) - baseline > plan["peak_bytes"]:
        raise RuntimeError("reserved installation peak exceeded; partial files retained")


def apply(plan):
    if not host_status()["apply_supported"]:
        raise ValueError("--apply requires WSL Ubuntu x86_64; native Linux migration is plan-only pending policy/validation")
    prefix = Path(plan["env_prefix"])
    if prefix.exists():
        raise FileExistsError("env-prefix already exists; use --doctor or choose a NEW prefix; no repair/overwrite")
    conda = plan["conda_executable"]
    if not conda or not Path(conda).is_file() or not os.access(conda, os.X_OK):
        raise ValueError("Conda not installed: supply --conda-executable; this script never installs or changes Conda base")
    root = Path(plan["storage_root"])
    owner = root / "runtime/models"
    preflight = capacity(plan)
    if not preflight["passed"]:
        raise ValueError("capacity preflight refused; inspect --dry-run checks, do not delete environments automatically")
    owner.mkdir(parents=True, exist_ok=True)
    lock = root / "runtime/shared/.models-bootstrap-lock"
    absolute_path(lock, "installer lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.mkdir()  # stale/active lock is an explicit refusal
    report_dir = owner / "device-reports" / uuid.uuid4().hex
    report = {"plan": plan, "status": "running", "before": preflight, "completed_commands": 0}
    try:
        # Check again after obtaining the single installer lock.
        locked = capacity(plan)
        if not locked["passed"] or prefix.exists():
            raise ValueError("capacity/prefix changed while acquiring installer lock")
        baseline = installation_bytes(plan)
        report_dir.mkdir(parents=True, exist_ok=False)
        (lock / "reservation.json").write_text(json.dumps({"pid": os.getpid(), "peak_bytes": plan["peak_bytes"],
                                                          "report": str(report_dir)}), encoding="utf-8")
        for key in ("CONDA_PKGS_DIRS", "PIP_CACHE_DIR", "XDG_CACHE_HOME", "TMPDIR"):
            Path(plan["environment"][key]).mkdir(parents=True, exist_ok=True)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        for argv in plan["commands"]:
            bounded_command(argv, plan, report_dir / "install.log", baseline)
            report["completed_commands"] += 1
        report["after"] = capacity(plan, peak=0)
        report["doctor"] = doctor(plan)
        if not report["after"]["passed"] or report["doctor"]["environment"] != "installed":
            raise RuntimeError("post-install capacity/environment validation failed")
        report["status"] = "installed_environment_only"
        # Reusable env values are data, not shell fragments. Keep within receipt.
        (report_dir / "environment.json").write_text(json.dumps(plan["environment"], indent=2), encoding="utf-8")
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        if report_dir.exists():
            (report_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        reservation = lock / "reservation.json"
        if reservation.exists():
            reservation.unlink()
        lock.rmdir()
    return {"status": report["status"], "report": str(report_dir / "report.json"), "models": "unavailable_until_verified"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="cpu-prep")
    parser.add_argument("--storage-root", required=True)
    parser.add_argument("--env-prefix")
    parser.add_argument("--conda-executable")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--dry-run", action="store_true", help="read-only capacity/host checks; never install")
    actions.add_argument("--doctor", action="store_true", help="read-only environment/host metadata, no model import")
    actions.add_argument("--apply", action="store_true", help="explicitly create a NEW isolated Conda environment")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.profile, args.storage_root, args.env_prefix, args.conda_executable)
        if args.apply:
            output = apply(plan)
        else:
            output = plan
            if args.dry_run or args.doctor:
                output["doctor"] = doctor(plan)
            if args.dry_run:
                output["capacity"] = capacity(plan)
                output["status"] = "dry_run_passed" if output["capacity"]["passed"] else "blocked_capacity"
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2 if output.get("status") == "blocked_capacity" else 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc), "exception": type(exc).__name__}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
