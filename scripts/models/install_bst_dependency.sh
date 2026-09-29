#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir /mnt/d/video/runtime/models/.bst-dependency-lock
trap 'rmdir /mnt/d/video/runtime/models/.bst-dependency-lock' EXIT
# Include the separate running VL install's conservative original reservation.
python3 "$repo_dir/scripts/models/runtime_preflight_reuse.py" --models-peak 24010000000 --shared-peak 2000000000
export TMPDIR=/mnt/d/video/runtime/models/bst-pip-tmp
export PIP_CACHE_DIR=/mnt/d/video/runtime/models/bst-pip-cache
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
env_python=/mnt/d/video/runtime/models/env/bin/python
"$env_python" -m pip install --no-deps --no-cache-dir --no-compile --only-binary=:all: --require-hashes -r "$repo_dir/environments/models-bst-requirements.txt"
"$env_python" -m pip check
"$env_python" -m pip freeze > "$repo_dir/environments/models-bst-pip-freeze.txt"
