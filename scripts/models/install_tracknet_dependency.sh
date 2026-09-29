#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
# A separate pip-only mutation of the existing environment. This never invokes
# Conda or shares the VL installer's temporary directory/package cache.
mkdir /mnt/d/video/runtime/models/.tracknet-dependency-lock
trap 'rmdir /mnt/d/video/runtime/models/.tracknet-dependency-lock' EXIT
python3 "$repo_dir/scripts/models/runtime_preflight_reuse.py" --models-peak 24300000000 --shared-peak 2000000000
export TMPDIR=/mnt/d/video/runtime/models/tracknet-pip-tmp
export PIP_CACHE_DIR=/mnt/d/video/runtime/models/tracknet-pip-cache
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
env_python=/mnt/d/video/runtime/models/env/bin/python
"$env_python" -m pip install --no-deps --no-cache-dir --no-compile --only-binary=:all: opencv-python-headless==4.11.0.86
"$env_python" -m pip check
"$env_python" -c 'import cv2, numpy; print({"opencv": cv2.__version__, "numpy": numpy.__version__})'
"$env_python" -m pip freeze > "$repo_dir/environments/models-tracknet-pip-freeze.txt"
