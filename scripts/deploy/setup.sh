#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${BTV_BOOTSTRAP_PYTHON:-python3}" "$script_dir/manage.py" setup "$@"
