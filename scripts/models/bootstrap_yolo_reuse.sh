#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir /mnt/d/video/runtime/models/.yolo-bootstrap-lock
trap 'rmdir /mnt/d/video/runtime/models/.yolo-bootstrap-lock' EXIT
python3 "$repo_dir/scripts/models/runtime_preflight_reuse.py" --models-peak 24600000000 --shared-peak 2000000000
yolo_prefix=/mnt/d/video/runtime/models/yolo-env
test ! -e "$yolo_prefix"
export TMPDIR=/mnt/d/video/runtime/models/yolo-tmp
export PIP_CACHE_DIR=/mnt/d/video/runtime/models/yolo-pip-cache
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
# No second Conda operation or replacement of the existing framework. This
# explicitly shares only the project's already isolated parent environment.
/mnt/d/video/runtime/models/env/bin/python -m venv --system-site-packages "$yolo_prefix"
"$yolo_prefix/bin/python" -m pip install --no-deps --no-cache-dir --no-compile --only-binary=:all: -r "$repo_dir/environments/models-yolo-requirements.txt"
"$yolo_prefix/bin/python" -m pip check
"$yolo_prefix/bin/python" -m pip freeze > "$repo_dir/environments/models-yolo-pip-freeze.txt"
"$yolo_prefix/bin/python" -c 'import importlib.metadata as m; print({k:m.version(k) for k in ["torch","torchvision","numpy","ultralytics","opencv-python","scipy","lap"]})'
python3 "$repo_dir/scripts/models/runtime_preflight_reuse.py"
