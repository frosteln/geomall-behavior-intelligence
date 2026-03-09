# Manual AWS Deployment Guide

This guide walks through the deployment using the AWS Console and manual SSH steps instead of Terraform, CloudFormation, or AWS CLI provisioning.

It assumes you will still upload the deployment bundle and model files to S3, then use the EC2 bootstrap script on the instance.

Default target Region for this guide: `ap-southeast-1` (Singapore).

## 1. Prepare the files locally

On your local machine:

1. Open the deployment bundle in [`deployment/llm-serving`](./).
2. Copy [`config/deployment.env.example`](./config/deployment.env.example) to `deployment.env`.
3. Copy [`config/services.yaml.example`](./config/services.yaml.example) to `services.yaml`.
4. Edit `deployment.env`:
   - set `AWS_REGION=ap-southeast-1`
   - set `S3_BUCKET`
   - set `PUBLIC_HOSTNAME` if you have a domain
   - set `OPENWEBUI_SECRET`
   - set `LITELLM_MASTER_KEY`
5. Edit `services.yaml`:
   - confirm Qwen path for GPU `0,1`
   - confirm Whisper path for GPU `2`
   - confirm BERT path for GPU `3`
   - update BERT labels if needed

## 2. Upload artifacts to S3

You need one S3 bucket that stores both:

- model files
- deployment bundle files

Recommended structure:

```text
s3://YOUR-BUCKET/models/qwen3.5-9b/...
s3://YOUR-BUCKET/models/faster-whisper-large-v3/...
s3://YOUR-BUCKET/models/bert-seq-cls/...
s3://YOUR-BUCKET/deploy-bundle/bootstrap_ec2.sh
s3://YOUR-BUCKET/deploy-bundle/render_stack.py
s3://YOUR-BUCKET/deploy-bundle/validate_stack.sh
s3://YOUR-BUCKET/deploy-bundle/requirements.deploy.txt
s3://YOUR-BUCKET/deploy-bundle/deployment.env
s3://YOUR-BUCKET/deploy-bundle/services.yaml
s3://YOUR-BUCKET/deploy-bundle/whisper_api.py
s3://YOUR-BUCKET/deploy-bundle/bert_classifier_api.py
```

Console steps:

1. Open AWS Console.
2. Go to `S3`.
3. Create a bucket if you do not already have one.
4. Open the bucket.
5. Create folders:
   - `models/`
   - `deploy-bundle/`
6. Upload your model directories into the `models/` prefixes.
7. Upload these files into `deploy-bundle/`:
   - [`bootstrap_ec2.sh`](./ec2/bootstrap_ec2.sh)
   - [`render_stack.py`](./ec2/render_stack.py)
   - [`validate_stack.sh`](./ec2/validate_stack.sh)
   - [`requirements.deploy.txt`](./requirements.deploy.txt)
   - your edited `deployment.env`
   - your edited `services.yaml`
   - [`whisper_api.py`](./services/whisper_api.py)
   - [`bert_classifier_api.py`](./services/bert_classifier_api.py)

## 3. Create the IAM role for EC2

This role gives the instance permission to read the model and deployment files from S3.

Console steps:

1. Go to `IAM`.
2. Open `Roles`.
3. Click `Create role`.
4. Trusted entity type: `AWS service`.
5. Use case: `EC2`.
6. Attach permissions:
   - `AmazonS3ReadOnlyAccess`
   - or a narrower custom policy limited to your bucket
7. Name the role something like `ec2-llm-serving-role`.
8. Create the role.

Recommended custom policy scope:

- `s3:ListBucket` on the bucket
- `s3:GetObject` on:
  - `deploy-bundle/*`
  - `models/*`

## 4. Create the security group

You need one instance security group and one ALB security group.

### ALB security group

1. Go to `EC2` -> `Security Groups`.
2. Create a security group named something like `sg-llm-alb`.
3. Inbound rules:
   - `HTTP` `80` from `0.0.0.0/0`
   - `HTTPS` `443` from `0.0.0.0/0` if using TLS
4. Outbound:
   - allow all

### EC2 instance security group

1. Create another security group named something like `sg-llm-ec2`.
2. Inbound rules:
   - `SSH` `22` from your office or your IP
   - custom TCP `3000` from `sg-llm-alb`
   - custom TCP `4000` from `sg-llm-alb`
   - custom TCP `8002` from `sg-llm-alb`
   - custom TCP `8003` from `sg-llm-alb`
3. Do not expose `8001` publicly.
4. Outbound:
   - allow all

## 5. Launch the EC2 instance

Console steps:

1. Go to `EC2` -> `Instances`.
2. Click `Launch instances`.
3. Name the instance, for example `llm-g4dn-12xlarge-01`.
4. Choose an AMI:
   - use an Ubuntu 22.04 NVIDIA-enabled AMI
   - preferred: AWS Deep Learning Base OSS Nvidia Driver AMI Ubuntu 22.04
5. Choose instance type:
   - `g4dn.12xlarge`
6. Choose or create a key pair for SSH.
7. Under `Network settings`:
   - choose the VPC and subnets where the ALB will live
   - attach `sg-llm-ec2`
   - auto-assign public IP only if you want direct SSH from the internet
8. Under `Advanced details`:
   - attach the IAM instance profile `ec2-llm-serving-role`
   - optional: paste user data if you want partial automation
9. Set EBS root volume large enough for OS, logs, and package install.
10. Launch the instance.

## 6. Connect to the instance

After the instance is running:

1. Go to `EC2` -> `Instances`.
2. Select the instance.
3. Copy the public IP or public DNS.
4. Connect by SSH from your terminal.

Example:

```bash
ssh -i /path/to/key.pem ubuntu@YOUR_PUBLIC_IP
```

## 7. Pull the deployment bundle from S3

Run these commands on the EC2 instance:

```bash
sudo mkdir -p /opt/llm-serving-src
cd /opt/llm-serving-src
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/bootstrap_ec2.sh .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/render_stack.py .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/validate_stack.sh .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/requirements.deploy.txt .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/deployment.env .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/services.yaml .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/whisper_api.py .
aws s3 cp s3://YOUR-BUCKET/deploy-bundle/bert_classifier_api.py .
chmod +x bootstrap_ec2.sh render_stack.py validate_stack.sh whisper_api.py bert_classifier_api.py
```

Create the folder structure expected by the script:

```bash
sudo mkdir -p /opt/llm-serving-src/ec2
sudo mkdir -p /opt/llm-serving-src/services
sudo cp bootstrap_ec2.sh /opt/llm-serving-src/ec2/bootstrap_ec2.sh
sudo cp render_stack.py /opt/llm-serving-src/ec2/render_stack.py
sudo cp validate_stack.sh /opt/llm-serving-src/ec2/validate_stack.sh
sudo cp whisper_api.py /opt/llm-serving-src/services/whisper_api.py
sudo cp bert_classifier_api.py /opt/llm-serving-src/services/bert_classifier_api.py
sudo cp requirements.deploy.txt /opt/llm-serving-src/requirements.deploy.txt
sudo cp deployment.env /opt/llm-serving-src/deployment.env
sudo cp services.yaml /opt/llm-serving-src/services.yaml
```

## 8. Run the bootstrap

Run on the EC2 instance:

```bash
cd /opt/llm-serving-src
sudo ./ec2/bootstrap_ec2.sh \
  --env /opt/llm-serving-src/deployment.env \
  --services /opt/llm-serving-src/services.yaml
```

This step will:

1. install system packages
2. mount local NVMe storage under `/mnt/models` if available
3. install Python dependencies
4. sync models from S3
5. render config files
6. start:
   - `vllm-qwen`
   - `whisper-api`
   - `bert-classifier`
   - `litellm`
   - `open-webui`

## 9. Validate on the instance

Run:

```bash
sudo /opt/llm-serving-src/ec2/validate_stack.sh
```

Or manually:

```bash
nvidia-smi
systemctl status vllm-qwen whisper-api bert-classifier litellm open-webui --no-pager
curl http://127.0.0.1:8001/v1/models
curl http://127.0.0.1:4000/v1/models
curl http://127.0.0.1:8002/healthz
curl http://127.0.0.1:8003/healthz
```

## 10. Create the load balancer

Console steps:

1. Go to `EC2` -> `Load Balancers`.
2. Click `Create load balancer`.
3. Choose `Application Load Balancer`.
4. Set it to `internet-facing`.
5. Select the same VPC as the instance.
6. Select at least two public subnets.
7. Attach security group `sg-llm-alb`.

## 11. Create target groups

Create four target groups, all with target type `Instance`.

### Open WebUI target group

1. Name: `tg-open-webui`
2. Protocol: `HTTP`
3. Port: `3000`
4. Health check path: `/health`
5. Register your EC2 instance

### LiteLLM target group

1. Name: `tg-litellm`
2. Protocol: `HTTP`
3. Port: `4000`
4. Health check path: `/health/liveliness`
5. Register your EC2 instance

### Whisper target group

1. Name: `tg-whisper`
2. Protocol: `HTTP`
3. Port: `8002`
4. Health check path: `/healthz`
5. Register your EC2 instance

### BERT target group

1. Name: `tg-bert`
2. Protocol: `HTTP`
3. Port: `8003`
4. Health check path: `/healthz`
5. Register your EC2 instance

## 12. Add ALB listener rules

For the ALB listener on port `80`:

1. Add rule: path `/v1/*` -> `tg-litellm`
2. Add rule: path `/audio/*` -> `tg-whisper`
3. Add rule: path `/bert/*` -> `tg-bert`
4. Default rule -> `tg-open-webui`

If you use HTTPS:

1. Request a certificate in `ACM`.
2. Validate the domain.
3. Add an HTTPS listener on `443`.
4. Attach the certificate.
5. Copy the same listener rules to `443`.
6. Optionally redirect `80` to `443`.

## 13. Point DNS to the ALB

If you use Route 53:

1. Open `Route 53`.
2. Open your hosted zone.
3. Create an `A` record.
4. Choose `Alias`.
5. Point it to the ALB DNS name.

If you use another DNS provider:

1. Create a `CNAME` for your subdomain to the ALB DNS name.

## 14. Test from your browser and API client

Browser:

1. Open `http://YOUR_ALB_DNS` or your domain.
2. Confirm Open WebUI loads.

API checks:

```bash
curl http://YOUR_ALB_DNS/v1/models
curl http://YOUR_ALB_DNS/bert/classify \
  -H 'Content-Type: application/json' \
  -d '{"text":"This is great"}'
```

Whisper test:

```bash
curl http://YOUR_ALB_DNS/audio/transcriptions \
  -F "file=@sample.wav" \
  -F "model=whisper-1"
```

## 15. Troubleshooting

If target groups are unhealthy:

1. confirm the security groups allow ALB-to-instance traffic
2. confirm the service is listening on the expected port
3. confirm the health path is correct
4. check logs:

```bash
journalctl -u vllm-qwen -n 200 --no-pager
journalctl -u whisper-api -n 200 --no-pager
journalctl -u bert-classifier -n 200 --no-pager
journalctl -u litellm -n 200 --no-pager
journalctl -u open-webui -n 200 --no-pager
```

If model sync fails:

1. verify the IAM role is attached
2. verify the bucket name and prefixes in `deployment.env` and `services.yaml`
3. test:

```bash
aws s3 ls s3://YOUR-BUCKET/models/
```

If GPU services fail:

1. check `nvidia-smi`
2. verify the AMI has a working NVIDIA driver
3. confirm the model fits the assigned GPU memory

## 16. Manual update flow

To update a model or config later:

1. upload new artifacts to S3
2. SSH to the instance
3. pull updated config or scripts
4. rerun bootstrap or targeted sync
5. restart services

Example restart:

```bash
sudo systemctl restart vllm-qwen whisper-api bert-classifier litellm open-webui
```
