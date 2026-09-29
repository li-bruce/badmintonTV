#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
source "$repo_dir/environments/models-vl.env.sh"
mkdir /mnt/d/video/runtime/shared/.models-bootstrap-lock
trap 'rmdir /mnt/d/video/runtime/shared/.models-bootstrap-lock' EXIT
# Old env remains ~7.3GB. Reserve 24GB new runtime peak plus 2GB shared
# package cache growth, including temporary wheels and unpacked copies.
python3 "$repo_dir/scripts/models/runtime_preflight_reuse.py" --models-peak 24000000000 --shared-peak 2000000000
test ! -e "$BTV_MODELS_ENV"
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
/home/ubuntu/miniforge3/bin/conda create --yes --prefix "$BTV_MODELS_ENV" --file "$repo_dir/environments/models-conda-explicit.txt"
"$BTV_MODELS_ENV/bin/python" -m pip install --no-cache-dir --no-compile --only-binary=:all: --index-url https://download.pytorch.org/whl/cu128 torch==2.8.0 torchvision==0.23.0
"$BTV_MODELS_ENV/bin/python" -m pip install --no-cache-dir --no-compile --only-binary=:all: transformers==4.57.3 qwen-vl-utils==0.0.14 accelerate==1.6.0 safetensors==0.5.3 av==15.0.0 pillow==11.2.1
"$BTV_MODELS_ENV/bin/python" -m pip check
"$BTV_MODELS_ENV/bin/python" -m pip freeze > "$repo_dir/environments/models-vl-pip-freeze.txt"
/home/ubuntu/miniforge3/bin/conda list --prefix "$BTV_MODELS_ENV" --explicit > "$repo_dir/environments/models-vl-conda-explicit.txt"
python3 "$repo_dir/scripts/models/runtime_preflight_reuse.py"
