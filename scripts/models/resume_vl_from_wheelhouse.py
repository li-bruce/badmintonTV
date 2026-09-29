"""Validate or explicitly resume the existing Linux VL environment.

Default is read-only validation. On WSL, after the original bootstrap/pip has
exited and released its lock, run the existing vl-env Python with --execute.
This never creates an environment, calls conda, signals another process, or
removes a wheel/partial. CPU imports do not load model weights or use a GPU.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import uuid


REPO = Path(__file__).resolve().parents[2]
RUNTIME = Path("/mnt/d/video/runtime/models")
ENVIRONMENT = RUNTIME / "vl-env"
WHEELHOUSE = RUNTIME / "vl-wheelhouse"
SHARED_LOCK = Path("/mnt/d/video/runtime/shared/.models-bootstrap-lock")
MANIFEST = REPO / "docs/models/vl-linux-cp311-wheels.json"
MANIFEST_SHA256 = "e80d83e7a002bd8849a5a5a0ee257943ffe2cfc25af566fa8e7cb2a2f7f267c0"
CORE_VERSIONS = {
    "torch": "2.8.0+cu128", "torchvision": "0.23.0+cu128",
    "nvidia-cuda-nvrtc-cu12": "12.8.93", "nvidia-cuda-runtime-cu12": "12.8.90",
    "nvidia-cuda-cupti-cu12": "12.8.90", "nvidia-cudnn-cu12": "9.10.2.21",
    "nvidia-cublas-cu12": "12.8.4.1", "nvidia-cufft-cu12": "11.3.3.83",
    "nvidia-curand-cu12": "10.3.9.90", "nvidia-cusolver-cu12": "11.7.3.90",
    "nvidia-cusparse-cu12": "12.5.8.93", "nvidia-cusparselt-cu12": "0.7.1",
    "nvidia-nccl-cu12": "2.27.3", "nvidia-nvtx-cu12": "12.8.90",
    "nvidia-nvjitlink-cu12": "12.8.93", "nvidia-cufile-cu12": "1.13.1.3",
    "triton": "3.4.0",
}
PHASE2_VERSIONS = {
    "transformers": "4.57.3", "qwen-vl-utils": "0.0.14", "accelerate": "1.6.0",
    "safetensors": "0.5.3", "av": "15.0.0", "pillow": "11.2.1",
}
# Direct Python requirements from the verified Torch/vision METADATA, cp311.
SMALL_REQUIREMENTS = (
    "filelock", "typing-extensions>=4.10.0", "sympy>=1.13.3", "networkx",
    "jinja2", "fsspec", "numpy",
)


def no_links(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink path is refused: " + str(path))
    return path


def load_manifest():
    raw = MANIFEST.read_bytes()
    # Git's Windows checkout may change CRLF/LF only. The original evidence
    # digest remains the LF file's hash; no other content normalization occurs.
    if len(raw) > 64_000 or hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Reviewed core manifest hash changed; review before resuming")
    data = json.loads(raw)
    if (set(data) != {"schema_version", "platform", "python", "files"}
            or data["schema_version"] != "1.0" or data["platform"] != "linux_x86_64"
            or data["python"] != "cp311" or len(data["files"]) != 17):
        raise ValueError("Expected the reviewed 17-wheel Linux cp311 manifest")
    found = {}
    for entry in data["files"]:
        if set(entry) != {"filename", "url", "size_bytes", "sha256"}:
            raise ValueError("Unexpected manifest wheel fields")
        parts = entry["filename"].split("-")
        name, version = parts[0].replace("_", "-"), parts[1]
        if (name in found or CORE_VERSIONS.get(name) != version
                or Path(entry["filename"]).name != entry["filename"]
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or type(entry["size_bytes"]) is not int or entry["size_bytes"] <= 0):
            raise ValueError("Core wheel identity/version is not the reviewed version")
        found[name] = version
    if found != CORE_VERSIONS:
        raise ValueError("Incomplete core version set")
    return data["files"]


def verify_wheels(entries, directory):
    """All wheels must pass before the caller may start any installation."""
    directory = no_links(directory)
    verified = []
    for entry in entries:
        path = no_links(directory / entry["filename"])
        digest, consumed = hashlib.sha256(), 0
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size != entry["size_bytes"]:
                raise ValueError("Incomplete/oversize wheel preserved: " + path.name)
            while block := stream.read(1024 * 1024):
                consumed += len(block)
                if consumed > entry["size_bytes"]:
                    raise ValueError("Wheel grew during verification; preserved")
                digest.update(block)
            after = os.fstat(stream.fileno())
        snapshot = (before.st_size, before.st_mtime_ns, before.st_ino)
        if (snapshot != (after.st_size, after.st_mtime_ns, after.st_ino)
                or consumed != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]):
            raise ValueError("Wheel SHA mismatch/concurrent change; preserved: " + path.name)
        verified.append({"filename": path.name, "size_bytes": consumed,
                         "sha256": digest.hexdigest(), "snapshot": snapshot})
    return verified


def active_environment_pip(environment=None, proc=Path("/proc")):
    """Includes stopped processes; never sends a signal or reads their env."""
    prefix = str((environment or ENVIRONMENT) / "bin") + os.sep
    found = []
    for directory in proc.iterdir():
        if not directory.name.isdigit() or int(directory.name) == os.getpid():
            continue
        try:
            argv = (directory / "cmdline").read_bytes().decode("utf-8", errors="replace").split("\0")
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise RuntimeError("Cannot establish whether another installer is active") from exc
        if argv:
            module_pip = argv[0].startswith(prefix) and any(
                argv[i:i+2] == ["-m", "pip"] for i in range(len(argv)-1))
            direct_pip = any(arg.startswith(prefix) and Path(arg).name in {"pip", "pip3", "pip3.11"}
                             for arg in argv[:2])
            if module_pip or direct_pip:
                found.append(int(directory.name))
    return sorted(found)


@contextmanager
def installation_locks(shared=None, wheelhouse=None):
    """Reuse bootstrap mkdir lock and acquisition's exclusive writer filename."""
    shared, wheelhouse = no_links(shared or SHARED_LOCK), no_links(wheelhouse or WHEELHOUSE)
    try:
        shared.mkdir()
    except FileExistsError as exc:
        raise RuntimeError("Shared bootstrap lock exists; preserve it and wait for its owner") from exc
    writer = wheelhouse / ".wheelhouse-writer.json"
    token = uuid.uuid4().hex
    owned_writer = False
    try:
        with writer.open("x", encoding="utf-8") as stream:
            owned_writer = True
            json.dump({"token": token, "pid": os.getpid()}, stream)
        yield
    finally:
        if owned_writer:
            # Only this invocation's lock may be removed, never wheels/partials.
            if not writer.is_symlink() and json.loads(writer.read_text())["token"] == token:
                writer.unlink()
        shared.rmdir()


def controlled_environment():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PIP_") and k not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1", "PIP_CACHE_DIR": str(RUNTIME / "vl-pip-cache"),
        "TMPDIR": str(RUNTIME / "vl-tmp"), "TMP": str(RUNTIME / "vl-tmp"),
        "TEMP": str(RUNTIME / "vl-tmp"), "CUDA_VISIBLE_DEVICES": "",
        "HF_HOME": "/mnt/d/video/models/cache/huggingface",
        "TORCH_HOME": "/mnt/d/video/models/cache/torch",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false",
    })
    return env


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run_step(label, argv, run_dir, env, timeout=3600):
    """Keep stdout/stderr even on timeout/failure, without printing env/secrets."""
    write_json(run_dir / (label + ".command.json"), argv)
    out, err = run_dir / (label + ".stdout.txt"), run_dir / (label + ".stderr.txt")
    print(json.dumps({"step": label, "state": "running"}), flush=True)
    with out.open("xb") as stdout, err.open("xb") as stderr:
        result = subprocess.run(argv, cwd=REPO, env=env, stdout=stdout, stderr=stderr,
                                timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(label + " failed; retained stdout/stderr in " + str(run_dir))
    print(json.dumps({"step": label, "state": "complete"}), flush=True)
    return out


def install_commands(python, entries, wheelhouse, constraints):
    pip = [str(python), "-I", "-m", "pip", "--disable-pip-version-check", "--no-input"]
    common = ["install", "--no-cache-dir", "--no-compile", "--only-binary=:all:",
              "--progress-bar", "off", "--timeout", "30", "--retries", "2"]
    core = pip + common + ["--report", str(constraints.parent / "core-pip-report.json"), "--no-index", "--no-deps"] + [
        str(wheelhouse / entry["filename"]) for entry in entries]
    phase2 = pip + common + ["--report", str(constraints.parent / "phase2-pip-report.json"),
                            "--index-url", "https://pypi.org/simple", "--constraint", str(constraints)]
    phase2 += [name + "==" + version for name, version in PHASE2_VERSIONS.items()]
    phase2 += list(SMALL_REQUIREMENTS)
    return core, phase2


def cpu_probe():
    expected = CORE_VERSIONS | PHASE2_VERSIONS
    return "\n".join([
        "import importlib.metadata as md, json, sys, platform",
        "from pathlib import Path",
        "import torch, torchvision, transformers, qwen_vl_utils, accelerate, safetensors, av, PIL, tokenizers",
        "from transformers import Qwen3VLModel, Qwen3VLPreTrainedModel, Qwen3VLForConditionalGeneration, Qwen3VLProcessor",
        "expected = " + repr(expected),
        "versions = {name: md.version(name) for name in expected}",
        "assert versions == expected, (versions, expected)",
        "assert sys.version_info[:2] == (3, 11)",
        "assert Path(sys.prefix).resolve() == Path(" + repr(str(ENVIRONMENT)) + ").resolve()",
        "assert torch.version.cuda == '12.8'",
        "assert int(torch.tensor([1, 2], device='cpu').sum()) == 3",
        "assert list(torchvision.transforms.functional.resize(torch.zeros(3, 4, 4), [2, 2]).shape) == [3, 2, 2]",
        "assert not torch.cuda.is_initialized(), 'CPU probe unexpectedly initialized CUDA'",
        "print(json.dumps({'versions': versions, 'python': platform.python_version(), 'prefix': sys.prefix, 'torch_cuda_build': torch.version.cuda, 'cuda_initialized': False, 'model_weights_loaded': False, 'qwen3_vl_classes_imported': True}))",
    ])


def resume(entries):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Execution is restricted to the existing WSL Linux x86_64 environment")
    environment, wheelhouse = no_links(ENVIRONMENT), no_links(WHEELHOUSE)
    python = environment / "bin/python"
    if not environment.is_dir() or not python.is_file():
        raise RuntimeError("The existing vl-env is required; this script cannot create it")
    if not python.resolve().is_relative_to(environment.resolve()):
        raise RuntimeError("vl-env Python resolves outside the required environment")
    with installation_locks():
        active = active_environment_pip()
        if active:
            raise RuntimeError("Existing VL pip is still alive (including paused): " + repr(active))
        verified = verify_wheels(entries, wheelhouse)
        env = controlled_environment()
        for key in ("TMPDIR", "PIP_CACHE_DIR"):
            no_links(env[key]).mkdir(parents=True, exist_ok=True)
        run_dir = RUNTIME / "vl-resume-runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
        no_links(run_dir.parent).mkdir(exist_ok=True)
        run_dir.mkdir()
        write_json(run_dir / "start.json", {"schema_version": "1.0", "manifest_lf_sha256": MANIFEST_SHA256,
                                           "manifest_observed_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
                                           "environment": str(environment), "wheels": verified})
        try:
            identity_code = ("import sys,json; from pathlib import Path; "
                             "assert sys.version_info[:2] == (3,11); "
                             "assert Path(sys.prefix).resolve() == Path(" + repr(str(environment)) + ").resolve(); "
                             "print(json.dumps({'python':sys.version,'prefix':sys.prefix}))")
            run_step("00-existing-python", [str(python), "-I", "-c", identity_code], run_dir, env, 60)
            preflight = [str(python), "-I", str(REPO / "scripts/models/runtime_preflight_reuse.py")]
            run_step("01-capacity-before", preflight + ["--models-peak", "20000000000", "--shared-peak", "2000000000"], run_dir, env, 180)
            constraints = run_dir / "core-constraints.txt"
            with constraints.open("x", encoding="utf-8") as stream:
                stream.write("\n".join(name + "==" + version for name, version in sorted(CORE_VERSIONS.items())) + "\n")
            core, phase2 = install_commands(python, entries, wheelhouse, constraints)
            run_step("02-core-offline", core, run_dir, env)
            run_step("03-phase2-pypi", phase2, run_dir, env)
            run_step("04-pip-check", [str(python), "-I", "-m", "pip", "check"], run_dir, env, 120)
            run_step("05-cpu-import-versions", [str(python), "-I", "-c", cpu_probe()], run_dir, env, 180)
            run_step("06-pip-freeze", [str(python), "-I", "-m", "pip", "freeze", "--all"], run_dir, env, 120)
            run_step("07-capacity-after", preflight, run_dir, env, 180)
        except BaseException as exc:
            write_json(run_dir / "result.json", {"status": "failed", "error_type": type(exc).__name__,
                                                 "error": str(exc), "original_wheels_preserved": True})
            raise
        write_json(run_dir / "result.json", {"status": "complete", "original_wheels_preserved": True,
                                             "gpu_inference_run": False})
        return run_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Install only after the original pip/bootstrap exited; default only verifies wheels")
    args = parser.parse_args(argv)
    entries = load_manifest()
    if not args.execute:
        verified = verify_wheels(entries, WHEELHOUSE)
        print(json.dumps({"mode": "validation_only", "verified_wheels": len(verified),
                          "size_bytes": sum(x["size_bytes"] for x in verified)}))
        return 0
    print(json.dumps({"status": "complete", "run_dir": str(resume(entries))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
