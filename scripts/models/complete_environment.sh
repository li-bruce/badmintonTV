#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
source "$repo_dir/environments/models.env.sh"
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
mkdir /mnt/d/video/runtime/shared/.models-bootstrap-lock
trap 'rmdir /mnt/d/video/runtime/shared/.models-bootstrap-lock' EXIT
# Refuse a missing or broken framework install instead of resolving large
# replacement CUDA wheels inside this small completion budget.
"$BTV_MODELS_ENV/bin/python" - <<'PY'
from importlib.metadata import version
for package, expected in [('torch', '2.7.1+cu128'), ('torchvision', '0.22.1+cu128')]:
    if version(package) != expected:
        raise SystemExit('Complete the pinned torch/vision bootstrap first')
PY
"$BTV_MODELS_ENV/bin/python" -m pip check
# Additional peak for the pinned non-torch wheels, temporary downloads and
# unpacked files. Torch/torchvision are installed by bootstrap, not this step.
# Hold the shared installer lock for both preflight and final measurement.
python3 "$repo_dir/scripts/models/budget_check.py" --reserve-runtime 3000000000
"$BTV_MODELS_ENV/bin/python" -m pip install --no-cache-dir --no-compile --only-binary=:all: -c "$repo_dir/environments/models-requirements-lock.txt" transformers==4.51.3 accelerate==1.6.0 safetensors==0.5.3 pillow==11.2.1 av==15.0.0
"$BTV_MODELS_ENV/bin/python" -m pip check
"$BTV_MODELS_ENV/bin/python" -m pip freeze > "$BTV_STORAGE_ROOT/models/pip-freeze.txt"
/home/ubuntu/miniforge3/bin/conda list --prefix "$BTV_MODELS_ENV" --explicit > "$BTV_STORAGE_ROOT/models/conda-explicit.txt"
python3 "$repo_dir/scripts/models/budget_check.py"
