# EC2 LLM Serving Bundle

This bundle deploys a mixed-runtime inference stack on a single AWS `g4dn.12xlarge` instance:

- `Qwen3.5-9B` on GPUs `0,1` using `vLLM`
- `faster-whisper` on GPU `2`
- one BERT sequence-classification model on GPU `3`
- `LiteLLM` as the OpenAI-compatible gateway for the Qwen backend
- `Open WebUI` as the browser frontend

The primary path is host-based on EC2 with `systemd`. The Docker setup is included as a fallback under [`docker/`](./docker).

Default target Region for this bundle: `ap-southeast-1` (Singapore).

## Bundle layout

- [`config/deployment.env.example`](./config/deployment.env.example): shared infrastructure and runtime settings
- [`config/services.yaml.example`](./config/services.yaml.example): per-service inventory and GPU bindings
- [`ec2/bootstrap_ec2.sh`](./ec2/bootstrap_ec2.sh): EC2 user-data or manual bootstrap entrypoint
- [`ec2/render_stack.py`](./ec2/render_stack.py): config renderer for `systemd` and LiteLLM
- [`ec2/validate_stack.sh`](./ec2/validate_stack.sh): post-boot validation checks
- [`services/whisper_api.py`](./services/whisper_api.py): OpenAI-style transcription adapter
- [`services/bert_classifier_api.py`](./services/bert_classifier_api.py): BERT classification API
- [`docker/`](./docker): Docker fallback

## What this deploys

Internal ports on the instance:

- `127.0.0.1:8001` -> `vLLM` for Qwen
- `127.0.0.1:8002` -> Whisper adapter
- `127.0.0.1:8003` -> BERT classifier
- `127.0.0.1:4000` -> `LiteLLM`
- `127.0.0.1:3000` -> `Open WebUI`

Recommended public ALB routing:

- `/` -> `Open WebUI :3000`
- `/v1/*` -> `LiteLLM :4000`
- `/audio/*` -> Whisper adapter `:8002`
- `/bert/*` -> BERT classifier `:8003`

## AWS prerequisites

1. Create or reuse an S3 bucket that contains one directory per model.
2. Create an IAM role for the EC2 instance with:
   - `s3:GetObject`
   - `s3:ListBucket`
   - optional `logs:*` permissions if you forward logs elsewhere
3. Launch an EC2 `g4dn.12xlarge` instance with:
   - an NVIDIA-enabled Ubuntu AMI, preferably AWS Deep Learning Base OSS Nvidia Driver AMI Ubuntu 22.04
   - enough EBS for the OS plus logs
   - security group allowing inbound `80/443` from the ALB only, plus SSH as needed
4. Attach the IAM role to the instance.
5. Create an ALB in the same VPC/subnets.
6. Prepare DNS and ACM certificate if you want HTTPS.

## Prepare configuration

1. Copy [`config/deployment.env.example`](./config/deployment.env.example) to `deployment.env`.
2. Copy [`config/services.yaml.example`](./config/services.yaml.example) to `services.yaml`.
3. Fill in:
   - `AWS_REGION=ap-southeast-1`
   - S3 bucket and prefixes
   - public hostname
   - secrets
   - exact model paths
   - BERT label names
4. Keep the service order and GPU assignments unless you have a reason to change them.

## S3 model layout

Expected object layout:

```text
s3://<bucket>/models/qwen3.5-9b/...
s3://<bucket>/models/faster-whisper-large-v3/...
s3://<bucket>/models/bert-seq-cls/...
```

The bootstrap syncs each `s3_prefix` into the corresponding `local_dir`.

## Launch on EC2

### Option 1: EC2 user data

Pass the bootstrap script as user data and place the config files next to it on the instance image or fetch them early in user data.

Example user data:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/bootstrap_ec2.sh .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/render_stack.py .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/validate_stack.sh .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/requirements.deploy.txt .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/deployment.env .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/services.yaml .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/whisper_api.py .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/bert_classifier_api.py .
chmod +x bootstrap_ec2.sh
./bootstrap_ec2.sh --env /opt/deployment.env --services /opt/services.yaml
```

### Option 2: Manual bootstrap over SSH

```bash
chmod +x ec2/bootstrap_ec2.sh
sudo ec2/bootstrap_ec2.sh \
  --env config/deployment.env \
  --services config/services.yaml
```

## What the bootstrap does

1. Installs OS packages, Python tooling, and FFmpeg.
2. Detects and mounts the local NVMe instance store under `/mnt/models`.
3. Creates a Python virtualenv under `/opt/llm-serving/.venv`.
4. Installs Python dependencies from [`requirements.deploy.txt`](./requirements.deploy.txt).
5. Copies the service adapters into `/opt/llm-serving/services`.
6. Syncs each model directory from S3 to local NVMe storage.
7. Renders:
   - LiteLLM config
   - environment files
   - `systemd` units
8. Starts and enables all services.

## ALB setup

Create one target group per backend:

- `tg-open-webui` -> instance port `3000`, health path `/health`
- `tg-litellm` -> instance port `4000`, health path `/health/liveliness`
- `tg-whisper` -> instance port `8002`, health path `/healthz`
- `tg-bert` -> instance port `8003`, health path `/healthz`

Recommended listener rules:

1. `/v1/*` -> `tg-litellm`
2. `/audio/*` -> `tg-whisper`
3. `/bert/*` -> `tg-bert`
4. default `/` -> `tg-open-webui`

For HTTPS:

1. Request or import an ACM certificate.
2. Add an HTTPS `443` listener on the ALB.
3. Redirect `80` to `443`.
4. Set `PUBLIC_HOSTNAME` in `deployment.env`.

## Validation

Run the included validator:

```bash
sudo ec2/validate_stack.sh
```

Manual checks:

```bash
nvidia-smi
systemctl status vllm-qwen whisper-api bert-classifier litellm open-webui --no-pager
curl -s http://127.0.0.1:8001/v1/models
curl -s http://127.0.0.1:4000/v1/models
curl -s http://127.0.0.1:8003/healthz
curl -s http://127.0.0.1:8002/healthz
```

## Rollback

1. Disable ALB listener rules or detach the instance from target groups.
2. Stop the local services:

```bash
sudo systemctl stop open-webui litellm bert-classifier whisper-api vllm-qwen
```

3. If needed, remove generated units from `/etc/systemd/system/` and rerun `systemctl daemon-reload`.

## Docker fallback

The Docker-based version lives in [`docker/`](./docker). Use it only when you explicitly prefer container lifecycle management over a host-native install; the EC2-native path is simpler for GPU debugging and boot-time orchestration.
