#!/usr/bin/env bash
# Plan by default. Install only with --apply; never alter Conda base or drivers.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "${BTV_BOOTSTRAP_PYTHON:-python3}" -s -B "$repo_dir/scripts/models/device_setup.py" "$@"
