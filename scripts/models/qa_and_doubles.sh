#!/usr/bin/env bash
set -eu
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_dir"
source environments/models.env.sh
for ms in 1000 3000 5000; do
  "$BTV_MODELS_ENV/bin/python" scripts/models/pose_preview.py --request /mnt/d/video/models/handoff/requests/real-pose-002.json --features /mnt/d/video/models/handoff/real-pose-002/attempt-01/features.json --time-ms "$ms" --output "models/handoff/real-pose-002/attempt-01/preview-$ms.png"
done
"$BTV_MODELS_ENV/bin/python" scripts/models/prepare_doubles.py
"$BTV_MODELS_ENV/bin/python" -m packages.models run --request /mnt/d/video/models/handoff/requests/real-pose-doubles-001.json --result /mnt/d/video/models/handoff/real-pose-doubles-001/attempt-01/result.json
for ms in 500 2000 3500; do
  "$BTV_MODELS_ENV/bin/python" scripts/models/pose_preview.py --request /mnt/d/video/models/handoff/requests/real-pose-doubles-001.json --features /mnt/d/video/models/handoff/real-pose-doubles-001/attempt-01/features.json --time-ms "$ms" --output "models/handoff/real-pose-doubles-001/attempt-01/preview-$ms.png"
done
