#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
source "$repo_dir/environments/models.env.sh"
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
mkdir /mnt/d/video/runtime/shared/.models-bootstrap-lock
trap 'rmdir /mnt/d/video/runtime/shared/.models-bootstrap-lock' EXIT
"$BTV_MODELS_ENV/bin/python" -m pip install --no-cache-dir --no-compile --only-binary=:all: transformers==4.51.3 accelerate==1.6.0 safetensors==0.5.3 pillow==11.2.1 av==15.0.0
"$BTV_MODELS_ENV/bin/python" -m pip check
"$BTV_MODELS_ENV/bin/python" -m pip freeze > "$BTV_STORAGE_ROOT/models/pip-freeze.txt"
/home/ubuntu/miniforge3/bin/conda list --prefix "$BTV_MODELS_ENV" --explicit > "$BTV_STORAGE_ROOT/models/conda-explicit.txt"
