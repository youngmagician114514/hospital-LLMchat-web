#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${VLLM_MODEL_PATH:-/home/lwb/Decoding/mydecoding/mydecoding/base_model/qwen/Qwen2___5-7B-Instruct}"
SERVED_NAME="${VLLM_SERVED_MODEL_NAME:-qwen2.5-7b-instruct}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8001}"
TP_SIZE="${VLLM_TENSOR_PARALLEL_SIZE:-1}"
GPU_UTIL="${VLLM_GPU_MEMORY_UTILIZATION:-0.9}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
DTYPE="${VLLM_DTYPE:-bfloat16}"

python -m vllm.entrypoints.openai.api_server \
  --host "${HOST}" \
  --port "${PORT}" \
  --model "${MODEL_PATH}" \
  --served-model-name "${SERVED_NAME}" \
  --tensor-parallel-size "${TP_SIZE}" \
  --gpu-memory-utilization "${GPU_UTIL}" \
  --max-model-len "${MAX_LEN}" \
  --dtype "${DTYPE}"
