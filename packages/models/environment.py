"""Model environment metadata only; no process or dependency loading."""
import os
from pathlib import PurePosixPath, PureWindowsPath


def runtime_prefix(root, legacy_name):
    configured = os.environ.get("BTV_MODELS_ENV")
    if configured:
        return configured
    text = str(root)
    windows = PureWindowsPath(text)
    if len(windows.drive) == 2 and windows.drive[1] == ":":
        # Conventional WSL automount mapping. A custom mount must explicitly
        # supply BTV_MODELS_ENV; never expose a Windows path as a Linux prefix.
        base = PurePosixPath("/mnt", windows.drive[0].lower(), *windows.parts[1:])
    else:
        base = PurePosixPath(text)
    return str(base / "runtime/models" / legacy_name)
