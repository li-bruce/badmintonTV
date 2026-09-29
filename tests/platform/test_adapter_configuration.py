"""Exercise administrator mapping through PowerShell; never launch an adapter."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required to execute the administrator configuration")


def configure(tmp_path, options=None, *, repeat_without_yolo=False):
    storage = tmp_path / "video"
    interpreter = storage / "runtime/platform/env/Scripts/python.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"")  # The script checks existence; it must not execute this file.
    env = {**os.environ, "BTV_TEST_SCRIPT": str(REPO / "configure-platform-adapters.ps1"),
           "BTV_TEST_OPTIONS": json.dumps({"StorageRoot": str(storage), "ModelsRepo": str(REPO), **(options or {})}),
           "BTV_TEST_REPEAT": "1" if repeat_without_yolo else "0", "BTV_FFMPEG": "", "BTV_FFPROBE": ""}
    harness = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$options=@{}
($env:BTV_TEST_OPTIONS | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $options[$_.Name]=$_.Value }
. $env:BTV_TEST_SCRIPT @options
$first=$env:BTV_MODEL_COMMANDS_JSON | ConvertFrom-Json
if ($env:BTV_TEST_REPEAT -eq '1') {
    $options.Remove('EnableExperimentalYolo')
    . $env:BTV_TEST_SCRIPT @options
}
@{first=$first; final=($env:BTV_MODEL_COMMANDS_JSON | ConvertFrom-Json)} | ConvertTo-Json -Depth 8 -Compress
"""
    return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", harness],
                          env=env, cwd=REPO, text=True, encoding="utf-8", capture_output=True, timeout=20)


def mappings(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def prefix(command):
    assert command[1:3] == ["-m", "packages.runtime.wsl_bridge"]
    assert command[command.index("--distribution") + 1] == "Ubuntu"
    return command[command.index("--env-prefix") + 1]


def test_yolo_is_not_registered_by_default(tmp_path):
    commands = mappings(configure(tmp_path))["final"]
    assert "yolo11n-pose-bytetrack" not in commands
    assert "bst-cg-ap-reuse" not in commands
    assert "qwen3-vl-embedding-2b" not in commands


def test_yolo_opt_in_uses_its_independent_environment_and_exact_id(tmp_path):
    commands = mappings(configure(tmp_path, {"EnableExperimentalYolo": True, "EnableExperimentalBst": True,
        "EnableVlEmbedding": True, "WslEnvPrefix": "/mnt/d/video/runtime/models/alternate-main"}))["final"]
    assert prefix(commands["yolo11n-pose-bytetrack"]) == "/mnt/d/video/runtime/models/yolo-env"
    assert prefix(commands["bst-cg-ap-reuse"]) == "/mnt/d/video/runtime/models/alternate-main"
    assert prefix(commands["qwen3-vl-embedding-2b"]) == "/mnt/d/video/runtime/models/vl-env"
    assert not any(key in commands for key in ("yolo", "yolo11n", "yolo11n-pose"))


def test_administrator_can_choose_a_separate_yolo_environment(tmp_path):
    commands = mappings(configure(tmp_path, {"EnableExperimentalYolo": True,
        "YoloEnvPrefix": "/mnt/d/video/runtime/models/yolo-isolated-fixture"}))["final"]
    assert prefix(commands["yolo11n-pose-bytetrack"]) == "/mnt/d/video/runtime/models/yolo-isolated-fixture"


@pytest.mark.parametrize("yolo_prefix", ["/mnt/d/video/runtime/models/env", "/mnt/d/video/runtime/models/env/",
    "/mnt/d/video/runtime/models/alternate-main", "/mnt/d/video/runtime/models/vl-env"])
def test_yolo_cannot_be_registered_in_shared_main_or_vl_environment(tmp_path, yolo_prefix):
    result = configure(tmp_path, {"EnableExperimentalYolo": True, "YoloEnvPrefix": yolo_prefix,
        "WslEnvPrefix": "/mnt/d/video/runtime/models/alternate-main"})
    assert result.returncode != 0
    assert "YOLO requires an independent environment" in result.stderr


def test_reloading_without_yolo_opt_in_removes_previous_registration(tmp_path):
    result = mappings(configure(tmp_path, {"EnableExperimentalYolo": True}, repeat_without_yolo=True))
    assert "yolo11n-pose-bytetrack" in result["first"]
    assert "yolo11n-pose-bytetrack" not in result["final"]
