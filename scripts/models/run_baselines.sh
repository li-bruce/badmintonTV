#!/usr/bin/env bash
# Run only when the models GPU lease and owner writer slot are available.
# Failed/blocked Qwen output is retained and does not stop the diagnostic suite.
set -u
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_dir"
source environments/models.env.sh
export CUDA_VISIBLE_DEVICES=0
"$BTV_MODELS_ENV/bin/python" scripts/models/prepare_experiments.py --run-suffix 002 || exit 1
for run_name in query-rule-v1-002 real-pose-002 real-video_embedding-002 qwen3-0.6b-002; do
  "$BTV_MODELS_ENV/bin/python" -m packages.models run --request "/mnt/d/video/models/handoff/requests/$run_name.json" --result "/mnt/d/video/models/handoff/$run_name/attempt-01/result.json"
  code=$?
  printf '{"run":"%s","returncode":%s}\n' "$run_name" "$code"
done
"$BTV_MODELS_ENV/bin/python" scripts/models/query_benchmark.py --output-dir models/handoff/query-diagnostic-001
