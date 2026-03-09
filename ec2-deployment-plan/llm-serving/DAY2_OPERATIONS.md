# Day-2 Operations Guide

This guide covers the common operational tasks after the initial deployment:

- checking service health
- restarting services
- rotating configs and secrets
- updating models
- rolling back bad changes
- basic scaling and maintenance habits

## 1. Core paths and services

Default paths used by the deployment:

- stack root: `/opt/llm-serving`
- source bundle used during bootstrap: `/opt/llm-serving-src`
- generated config: `/opt/llm-serving/generated`
- model root: `/mnt/models`

Main `systemd` services:

- `vllm-qwen`
- `whisper-api`
- `bert-classifier`
- `litellm`
- `open-webui`

## 2. Health and status checks

Check service state:

```bash
systemctl status vllm-qwen whisper-api bert-classifier litellm open-webui --no-pager
```

Check logs:

```bash
journalctl -u vllm-qwen -n 200 --no-pager
journalctl -u whisper-api -n 200 --no-pager
journalctl -u bert-classifier -n 200 --no-pager
journalctl -u litellm -n 200 --no-pager
journalctl -u open-webui -n 200 --no-pager
```

Check health endpoints:

```bash
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8002/healthz
curl -fsS http://127.0.0.1:8003/healthz
curl -fsS http://127.0.0.1:4000/health/liveliness
curl -fsS http://127.0.0.1:3000/health
```

Check GPU state:

```bash
nvidia-smi
```

Run the bundled validation script:

```bash
sudo /opt/llm-serving-src/ec2/validate_stack.sh
```

## 3. Safe restart procedures

### Restart one service

Use this when only one backend is unhealthy.

```bash
sudo systemctl restart whisper-api
sudo systemctl restart bert-classifier
sudo systemctl restart vllm-qwen
sudo systemctl restart litellm
sudo systemctl restart open-webui
```

### Restart the API layer only

Use this when Qwen is healthy but API/UI config changed.

```bash
sudo systemctl restart litellm open-webui
```

### Full stack restart

Use this after a major config or dependency update.

```bash
sudo systemctl restart vllm-qwen whisper-api bert-classifier litellm open-webui
```

Recommended restart order when doing it manually:

1. `vllm-qwen`
2. `whisper-api`
3. `bert-classifier`
4. `litellm`
5. `open-webui`

## 4. Updating configuration

Configuration lives in:

- `/opt/llm-serving/config/deployment.env`
- `/opt/llm-serving/config/services.yaml`

Generated files live in:

- `/opt/llm-serving/generated/runtime.env`
- `/opt/llm-serving/generated/litellm/config.yaml`
- `/opt/llm-serving/generated/systemd/*.service`

After changing config:

```bash
sudo /opt/llm-serving/.venv/bin/python /opt/llm-serving/render_stack.py render \
  --env /opt/llm-serving/config/deployment.env \
  --services /opt/llm-serving/config/services.yaml \
  --output /opt/llm-serving/generated

sudo cp /opt/llm-serving/generated/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart vllm-qwen whisper-api bert-classifier litellm open-webui
```

Use this when you change:

- ports
- GPU assignments
- model aliases
- LiteLLM key
- Open WebUI secret
- service arguments

## 5. Updating models from S3

### Standard model refresh

If the model files in S3 have changed and the local copy should be updated:

```bash
sudo /opt/llm-serving/.venv/bin/python /opt/llm-serving/render_stack.py sync-models \
  --env /opt/llm-serving/config/deployment.env \
  --services /opt/llm-serving/config/services.yaml
```

Then restart the affected service:

```bash
sudo systemctl restart vllm-qwen
sudo systemctl restart whisper-api
sudo systemctl restart bert-classifier
```

### Recommended model update flow

For safer updates:

1. upload the new model under a new S3 prefix
2. update `services.yaml` to point to the new prefix and local directory
3. rerun `sync-models`
4. rerender config
5. restart only the affected service
6. validate locally
7. validate through the ALB

This is safer than overwriting the old model in place.

## 6. Rolling back a bad model update

If a new model or config is bad:

1. revert `services.yaml` to the previous `s3_prefix` and `local_dir`
2. rerun the model sync
3. rerender config
4. restart the affected service
5. validate health and sample inference

Fast rollback example:

```bash
sudo systemctl restart vllm-qwen
curl -fsS http://127.0.0.1:8001/v1/models
```

## 7. Rotating secrets

Secrets in this deployment:

- `LITELLM_MASTER_KEY`
- `OPENWEBUI_SECRET`

Rotation procedure:

1. edit `/opt/llm-serving/config/deployment.env`
2. rerender generated config
3. restart `litellm` and `open-webui`

Commands:

```bash
sudo editor /opt/llm-serving/config/deployment.env

sudo /opt/llm-serving/.venv/bin/python /opt/llm-serving/render_stack.py render \
  --env /opt/llm-serving/config/deployment.env \
  --services /opt/llm-serving/config/services.yaml \
  --output /opt/llm-serving/generated

sudo cp /opt/llm-serving/generated/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart litellm open-webui
```

## 8. Updating application code or bootstrap assets

If you update:

- `whisper_api.py`
- `bert_classifier_api.py`
- `render_stack.py`
- `requirements.deploy.txt`

Recommended process:

1. copy new files to the instance
2. replace files under `/opt/llm-serving`
3. reinstall dependencies only if required
4. rerender if config generation changed
5. restart the affected services

Reinstall dependencies:

```bash
sudo /opt/llm-serving/.venv/bin/pip install -r /opt/llm-serving-src/requirements.deploy.txt
```

## 9. Day-2 checks after any change

After each model, config, or code update:

1. run `systemctl status`
2. run `nvidia-smi`
3. hit all local health endpoints
4. run one sample Qwen request through LiteLLM
5. run one sample transcription request
6. run one sample BERT classification request
7. test through the ALB public URLs

## 10. Recommended maintenance habits

- Keep one copy of the last known-good `deployment.env` and `services.yaml`.
- Prefer versioned S3 model prefixes instead of overwriting existing ones.
- Restart only the affected service when possible.
- Put billing alarms on the account before leaving the instance always-on.
- Check disk usage regularly because model caches and logs can grow.
- Export or centralize logs if you need incident history beyond local journal retention.

## 11. Useful maintenance commands

Disk usage:

```bash
df -h
du -sh /mnt/models/*
```

Top GPU processes:

```bash
nvidia-smi
```

Recent boot logs:

```bash
journalctl -b -n 200 --no-pager
```

Service enablement:

```bash
systemctl is-enabled vllm-qwen whisper-api bert-classifier litellm open-webui
```
