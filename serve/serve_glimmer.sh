#!/usr/bin/env bash
# Serve Muse Glimmer (nvidia/Muse-Glimmer-30B-NVFP4, open weights) with vLLM, on this computer's own GPUs.
#
#   bash serve/serve_glimmer.sh             start it on :8001
#   bash serve/serve_glimmer.sh --dry-run   say which GPUs it would use, and how, without starting
#
# The NVFP4 weights are 24.7 GB and run natively on Blackwell GPUs (compute capability 10 or 12). It shares them across
# 4, 2 or 1 cards: the most, up to 4, that each have room, so the cache gets the most memory. Tested here on four
# 16 GB RTX 5060 Ti; the 2- and 1-card choices follow the same rule but weren't run here. GLIMMER_GPUS=0,1 picks cards yourself.
#
# Safety: it refuses to start if the cards lack free memory, and it never stops anything else to make room.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${GLIMMER_WEIGHTS:-models/Muse-Glimmer-30B-NVFP4}"
PORT="${GLIMMER_PORT:-8001}"
PY="${GLIMMER_PYTHON:-.venv/bin/python}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

if [ ! -f "$MODEL/config.json" ]; then
  echo "The weights aren't in $MODEL. Download them once (24.7 GB), accepting the license on Hugging Face if it asks:" >&2
  echo "  pip install -U huggingface_hub && hf download nvidia/Muse-Glimmer-30B-NVFP4 --local-dir $MODEL" >&2
  [ "$DRY" = 1 ] || exit 1
fi
if ! "$PY" -c "import vllm" 2>/dev/null; then
  echo "vLLM isn't installed for $PY. Install it once, in its own environment:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install vllm==0.32.0" >&2
  [ "$DRY" = 1 ] || exit 1
fi

# Free memory (MiB) per Blackwell card, freest first: "index,free".
mapfile -t CARDS < <(nvidia-smi --query-gpu=index,memory.free,compute_cap --format=csv,noheader,nounits 2>/dev/null |
  tr -d ' ' | awk -F, '$3+0 >= 10.0 {print $1","$2}' | sort -t, -k2 -rn)
if [ -n "${GLIMMER_GPUS:-}" ]; then
  IFS=, read -r -a PICK <<< "$GLIMMER_GPUS"
else
  # Room each card needs, by how many share the weights: its part of 24.7 GB, plus room for the cache.
  declare -A NEED=([4]=10000 [2]=15500 [1]=30000)
  PICK=()
  for tp in 4 2 1; do
    [ "${#CARDS[@]}" -ge "$tp" ] || continue
    ok=1
    for entry in "${CARDS[@]:0:$tp}"; do [ "${entry#*,}" -ge "${NEED[$tp]}" ] || ok=0; done
    if [ "$ok" = 1 ]; then for entry in "${CARDS[@]:0:$tp}"; do PICK+=("${entry%%,*}"); done; break; fi
  done
  if [ "${#PICK[@]}" -eq 0 ]; then
    echo "No room for Glimmer: it needs Blackwell GPUs with 4 x 10 GB, 2 x 15.5 GB or 1 x 30 GB free." >&2
    FREE="$(for c in "${CARDS[@]}"; do printf 'GPU %s has %s MiB; ' "${c%%,*}" "${c#*,}"; done)"; FREE="${FREE%; }"
    echo "Free now: ${FREE:-no Blackwell GPU found}. Free a card, or set GLIMMER_URL to a server that already runs it." >&2
    echo "Nothing was stopped to make room." >&2
    exit 1
  fi
fi
TP="${#PICK[@]}"
GPUS="$(IFS=,; echo "${PICK[*]}")"

export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES="$GPUS"
# Nothing here should reach out: this is the model that runs with the internet unplugged.
# GPU workers talk over loopback, so unplugging the network cannot take them down.
export GLOO_SOCKET_IFNAME=lo NCCL_SOCKET_IFNAME=lo MASTER_ADDR=127.0.0.1
export VLLM_HOST_IP=127.0.0.1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
CMD=("$PY" -m vllm.entrypoints.openai.api_server
  --model "$MODEL"
  --served-model-name muse-glimmer
  --tensor-parallel-size "$TP"
  --dtype auto
  --gpu-memory-utilization 0.92
  --max-model-len "${GLIMMER_MAX_LEN:-32768}"
  --max-num-seqs "${GLIMMER_MAX_SEQS:-8}"
  --enable-prefix-caching
  --reasoning-parser muse_glimmer
  --host 127.0.0.1 --port "$PORT")
echo "Serving Muse Glimmer on GPU ${GPUS} (${TP} card$([ "$TP" = 1 ] || echo s)), at http://127.0.0.1:${PORT}/v1"
if [ "$DRY" = 1 ]; then printf '%q ' "${CMD[@]}"; echo; exit 0; fi
exec "${CMD[@]}"
