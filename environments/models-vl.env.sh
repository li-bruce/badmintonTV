#!/usr/bin/env bash
# Separate runtime: does not modify the accepted torch2.7.1 environment.
export BTV_STORAGE_ROOT=/mnt/d/video
export BTV_MODELS_ENV=/mnt/d/video/runtime/models/vl-env
export CONDA_PKGS_DIRS=/mnt/d/video/runtime/shared/pkgs
export CONDA_ENVS_PATH=/mnt/d/video/runtime/models
export TMPDIR=/mnt/d/video/runtime/models/vl-tmp
export PIP_CACHE_DIR=/mnt/d/video/runtime/models/vl-pip-cache
export HF_HOME=/mnt/d/video/models/cache/huggingface
export TORCH_HOME=/mnt/d/video/models/cache/torch
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
