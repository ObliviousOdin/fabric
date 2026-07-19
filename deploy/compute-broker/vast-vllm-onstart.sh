#!/usr/bin/env bash
# =============================================================================
# vast-vllm-onstart.sh — serve a frontier open-source model with vLLM on a
# rented GPU (Vast.ai, Hetzner GPU, Vultr GPU, …), OpenAI-compatible on :8000.
#
# On Vast.ai: choose the `vllm/vllm-openai:latest` image for the instance and
# paste this as the "On-start Script". On any other CUDA box, run it directly
# (vLLM must be installed, or use docker-compose.vllm.yml instead).
#
# A Fabric agent then points its model route at this box (or at the broker in
# front of it) as a custom OpenAI-compatible provider:
#
#   model:
#     provider: custom
#     base_url: http://<gpu-host>:8000/v1
#     default: <the VLLM_MODEL below>
#     api_key: ${VLLM_API_KEY}
#
# See docs: /deploy/compute-broker
# =============================================================================
set -euo pipefail

# --- Configure via environment (Vast.ai lets you set these on the instance) ---

# HuggingFace model id. EXAMPLE default — replace with the current best open
# model that fits your GPU/VRAM budget. Big models need multiple GPUs
# (set VLLM_TP to the GPU count for tensor parallelism).
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-72B-Instruct}"

# Bearer key clients must send. Generate once: openssl rand -hex 32
VLLM_API_KEY="${VLLM_API_KEY:-changeme-generate-with-openssl-rand-hex-32}"

# Fabric needs >= 64k effective context for agentic/tool use.
VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-65536}"

# Tensor-parallel size = number of GPUs to shard across (1 for a single GPU).
VLLM_TP="${VLLM_TP:-1}"

# Tool-call parser must match the model family so Fabric's tool calls work:
#   qwen*/hermes -> hermes | llama3.x -> llama3_json | mistral -> mistral
#   deepseek-v3 -> deepseek_v3 | (see vLLM docs for the full list)
VLLM_TOOL_PARSER="${VLLM_TOOL_PARSER:-hermes}"

VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_GPU_UTIL="${VLLM_GPU_UTIL:-0.92}"

# Optional: a HF token for gated models.
[ -n "${HF_TOKEN:-}" ] && export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"

echo "Starting vLLM: model=$VLLM_MODEL tp=$VLLM_TP max_len=$VLLM_MAX_MODEL_LEN parser=$VLLM_TOOL_PARSER port=$VLLM_PORT"

exec vllm serve "$VLLM_MODEL" \
  --host 0.0.0.0 \
  --port "$VLLM_PORT" \
  --api-key "$VLLM_API_KEY" \
  --max-model-len "$VLLM_MAX_MODEL_LEN" \
  --tensor-parallel-size "$VLLM_TP" \
  --gpu-memory-utilization "$VLLM_GPU_UTIL" \
  --enable-auto-tool-choice \
  --tool-call-parser "$VLLM_TOOL_PARSER" \
  --served-model-name "$VLLM_MODEL"

# Verify from your laptop once it is up:
#   curl -s http://<gpu-host>:8000/v1/models -H "Authorization: Bearer $VLLM_API_KEY"
