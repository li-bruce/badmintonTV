#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${BTV_BOOTSTRAP_PYTHON:-python3}" "$repo_dir/scripts/deploy/manage.py" run --profile desktop-cpu --target worker "$@"
