#!/bin/sh
# LoRA fine-tune of the coach model with MLX on Apple Silicon.
#   training/train.sh <run-name> [iters]
# Reads training/data/{train,valid,test}.jsonl, writes training/adapters/<run-name>.
set -eu
cd "$(dirname "$0")/.."
RUN="${1:?run name}"
ITERS="${2:-300}"

exec .venv/bin/mlx_lm.lora \
  --model mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --train \
  --data training/data \
  --fine-tune-type lora \
  --num-layers 16 \
  --batch-size 2 \
  --grad-accumulation-steps 2 \
  --iters "$ITERS" \
  --learning-rate 1e-4 \
  --mask-prompt \
  --grad-checkpoint \
  --max-seq-length 2048 \
  --steps-per-report 10 \
  --steps-per-eval 50 \
  --val-batches 10 \
  --save-every 100 \
  --seed 7 \
  --adapter-path "training/adapters/$RUN"
