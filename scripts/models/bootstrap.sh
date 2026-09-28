#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
source "$repo_dir/environments/models.env.sh"
mkdir -p "$CONDA_PKGS_DIRS" "$TMPDIR" "$PIP_CACHE_DIR" "$HF_HOME" "$TORCH_HOME"
test -x /home/ubuntu/miniforge3/bin/conda
python3 "$repo_dir/scripts/models/budget_check.py" --reserve-runtime 18000000000 --reserve-models 3000000000
if [ ! -x "$BTV_MODELS_ENV/bin/python" ]; then
  /home/ubuntu/miniforge3/bin/conda create --yes --prefix "$BTV_MODELS_ENV" --override-channels -c conda-forge python=3.11 pip
fi
"$BTV_MODELS_ENV/bin/python" -m pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
"$BTV_MODELS_ENV/bin/python" -m pip install --no-cache-dir transformers==4.51.3 accelerate==1.6.0 safetensors==0.5.3 pillow==11.2.1 av==14.4.0
"$BTV_MODELS_ENV/bin/python" -m pip freeze > "$BTV_STORAGE_ROOT/models/pip-freeze.txt"
/home/ubuntu/miniforge3/bin/conda list --prefix "$BTV_MODELS_ENV" --explicit > "$BTV_STORAGE_ROOT/models/conda-explicit.txt"
python3 "$repo_dir/scripts/models/budget_check.py"
