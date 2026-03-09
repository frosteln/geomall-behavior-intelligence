#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-${SCRIPT_DIR}/../config/deployment.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

export MODEL_ROOT="${MODEL_ROOT:-/mnt/models}"
export QWEN_MODEL_PATH="${MODEL_ROOT}/qwen3.5-9b"
export WHISPER_MODEL_PATH="${MODEL_ROOT}/faster-whisper-large-v3"
export BERT_MODEL_PATH="${MODEL_ROOT}/bert-seq-cls"
export BERT_LABELS_JSON='["negative","positive"]'

docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d --build
