#!/usr/bin/env bash
set -euo pipefail

services=(vllm-qwen whisper-api bert-classifier litellm open-webui)

echo "== GPU status =="
nvidia-smi

echo "== systemd status =="
for svc in "${services[@]}"; do
  systemctl is-active --quiet "${svc}"
  echo "${svc}: active"
done

echo "== health checks =="
curl -fsS http://127.0.0.1:8001/health > /dev/null
echo "vLLM health: ok"
curl -fsS http://127.0.0.1:8002/healthz > /dev/null
echo "Whisper health: ok"
curl -fsS http://127.0.0.1:8003/healthz > /dev/null
echo "BERT health: ok"
curl -fsS http://127.0.0.1:4000/health/liveliness > /dev/null
echo "LiteLLM health: ok"
curl -fsS http://127.0.0.1:3000/health > /dev/null
echo "Open WebUI health: ok"

echo "== model listing =="
curl -fsS http://127.0.0.1:8001/v1/models
curl -fsS http://127.0.0.1:4000/v1/models
