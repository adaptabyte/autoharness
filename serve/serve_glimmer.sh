#!/usr/bin/env bash
# Serve Muse Glimmer NVFP4 (nvidia/Muse-Glimmer-30B-NVFP4) with vLLM.
#
# Hardware fit on this machine: weights are 24.7 GB, so a single 16 GB
# RTX 5060 Ti cannot hold them. We tensor-parallel across the four freest
# Blackwell (sm_120) cards: ~6.6 GB weights per card + KV cache.
# NVFP4 (ModelOpt) runs natively on Blackwell FP4 tensor cores.
#
# Safety: refuses to start if the chosen cards lack free VRAM (e.g. while
# other workloads such as `strata` hold them). Never kills other processes.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${GLIMMER_MODEL:-models/Muse-Glimmer-30B-NVFP4}"
PORT="${GLIMMER_PORT:-8001}"
MIN_FREE_MB="${MIN_FREE_MB:-10000}"

# Pick the two Blackwell (cap >= 12.0) GPUs with the most free memory.
mapfile -t GPUS < <(nvidia-smi --query-gpu=index,memory.free,compute_cap \
  --format=csv,noheader,nounits | sort -t, -k2 -rn | \
  awk -F, '$3+0 >= 12.0 {print $1","$2}' | head -n 4)
if [ "${#GPUS[@]}" -lt 4 ]; then
  echo "ERROR: need 4 free Blackwell GPUs (RTX 5060 Ti). Found: ${GPUS[*]:-none}" >&2
  exit 1
fi
for entry in "${GPUS[@]}"; do
  free="${entry#*,}"
  if [ "${free%.*}" -lt "$MIN_FREE_MB" ]; then
    echo "ERROR: GPU ${entry%%,*} has only ${free} MiB free (need ${MIN_FREE_MB})." >&2
    echo "Another workload is using it; free a 5060 Ti first. Not killing anything." >&2
    exit 1
  fi
done
CUDA_VISIBLE_DEVICES="$(printf '%s\n' "${GPUS[@]}" | cut -d, -f1 | paste -sd, -)"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES
# Nothing here should reach out: this is the model that runs with the internet unplugged.
# GPU workers talk over loopback, so unplugging the network cannot take them down.
export VLLM_HOST_IP=127.0.0.1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
echo "Serving $MODEL on GPUs $CUDA_VISIBLE_DEVICES (TP=4), port $PORT"

exec .venv/bin/python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" \
  --served-model-name muse-glimmer \
  --tensor-parallel-size 4 \
  --dtype auto \
  --gpu-memory-utilization 0.92 \
  --max-model-len "${GLIMMER_MAX_LEN:-32768}" \
  --max-num-seqs "${GLIMMER_MAX_SEQS:-8}" \
  --enable-prefix-caching \
  --reasoning-parser muse_glimmer \
  --port "$PORT"
