# Cost Checklist

This checklist gives you a practical cost view for the deployment options around the current design.

Pricing assumptions in this document:

- Region: `ap-southeast-1` (Singapore)
- Billing basis: Linux, shared tenancy, On-Demand
- Primary usage pattern: `8 hours/day`, `5 days/week`
- Business-hours weekly runtime: `40 hours`
- Business-hours monthly runtime: `173.33 hours` using `40 x 52 / 12`
- Always-on monthly runtime for comparison: `730 hours`
- On-Demand prices pulled from the AWS public EC2 price list on March 9, 2026
- Spot numbers are planning estimates only, not live quotes

Source references:

- AWS EC2 public price list JSON for `ap-southeast-1`
- AWS G4 instance family page
- AWS Spot docs stating savings can be up to 90% and prices vary by Region and Availability Zone

Useful AWS references:

- https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-southeast-1/index.json
- https://aws.amazon.com/ec2/instance-types/g4/
- https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-spot-instances.html
- https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-best-practices.html

## 1. Current EC2 price points used here

On-Demand:

- `g4dn.xlarge`: `$0.736/hour`
- `g4dn.12xlarge`: `$5.474/hour`

Business-hours cost at `8h/day`, `5d/week`:

- `g4dn.xlarge`: `$5.89/day`, `$29.44/week`, `$127.57/month`
- `g4dn.12xlarge`: `$43.79/day`, `$218.96/week`, `$948.83/month`

Always-on monthly equivalents at `730` hours:

- `g4dn.xlarge`: `$537.28/month`
- `g4dn.12xlarge`: `$3,996.02/month`

## 2. Scenario summary

### Scenario A: Full recommended stack, normal instance

Use:

- `1 x g4dn.12xlarge`
- `4 GPUs total`
- Qwen on `2 GPUs`
- Whisper on `1 GPU`
- BERT on `1 GPU`

Compute cost:

- hourly: `$5.474`
- per day at `8h`: `$43.79`
- per week at `40h`: `$218.96`
- monthly at business-hours schedule: `$948.83`
- monthly if left on `24/7`: `$3,996.02`

Best fit:

- this is the recommended single-instance production baseline

### Scenario B: Full recommended stack, Spot instance

Use:

- `1 x g4dn.12xlarge` on Spot

Important:

- actual Spot price changes by Availability Zone and time
- use the AWS Console Spot price view before launch
- expect interruptions

Planning range against On-Demand:

- 30% discount: `$30.65/day`, `$153.27/week`, `$664.18/month`
- 50% discount: `$21.90/day`, `$109.48/week`, `$474.41/month`
- 60% discount: `$17.52/day`, `$87.58/week`, `$379.53/month`
- 70% discount: `$13.14/day`, `$65.69/week`, `$284.65/month`

Always-on monthly comparison:

- 30% discount: `$2,797.21/month`
- 50% discount: `$1,998.01/month`
- 60% discount: `$1,598.41/month`
- 70% discount: `$1,198.81/month`

Best fit:

- batch or non-critical environments
- cost-sensitive staging
- only use for production if you have interruption handling

### Scenario C: 1 GPU scenario

Use:

- `1 x g4dn.xlarge`
- `1 GPU total`

Compute cost:

- hourly: `$0.736`
- per day at `8h`: `$5.89`
- per week at `40h`: `$29.44`
- monthly at business-hours schedule: `$127.57`
- monthly if left on `24/7`: `$537.28`

Important limitation:

- this does **not** fit the full revised stack
- it is suitable only for:
  - Whisper-only
  - BERT-only
  - a very constrained single-model prototype

If you try to run Qwen + Whisper + BERT + Open WebUI + LiteLLM on one T4, you will likely run out of GPU memory or create unacceptable latency.

Spot planning for this 1 GPU scenario:

- 30% discount: `$4.12/day`, `$20.61/week`, `$89.30/month`
- 50% discount: `$2.94/day`, `$14.72/week`, `$63.79/month`
- 60% discount: `$2.36/day`, `$11.78/week`, `$51.03/month`
- 70% discount: `$1.77/day`, `$8.83/week`, `$38.27/month`

Always-on monthly comparison:

- 30% discount: `$376.10/month`
- 50% discount: `$268.64/month`
- 60% discount: `$214.91/month`
- 70% discount: `$161.18/month`

### Scenario D: 8 GPU scenario, 2 instances

Use:

- `2 x g4dn.12xlarge`
- `8 GPUs total`

Compute cost:

- hourly: `$10.948`
- per day at `8h`: `$87.58`
- per week at `40h`: `$437.92`
- monthly at business-hours schedule: `$1,897.65`
- monthly if left on `24/7`: `$7,992.04`

Typical layout options:

- option 1: active/active duplicate stacks for more throughput
- option 2: one stack per language/domain/model family
- option 3: one stack live and one stack warm for safer upgrades

Spot planning for this 8 GPU scenario:

- 30% discount: `$61.31/day`, `$306.54/week`, `$1,328.36/month`
- 50% discount: `$43.79/day`, `$218.96/week`, `$948.83/month`
- 60% discount: `$35.03/day`, `$175.17/week`, `$759.06/month`
- 70% discount: `$26.28/day`, `$131.38/week`, `$569.30/month`

Always-on monthly comparison:

- 30% discount: `$5,594.43/month`
- 50% discount: `$3,996.02/month`
- 60% discount: `$3,196.82/month`
- 70% discount: `$2,397.61/month`

## 3. Non-EC2 costs people usually forget

Before approving the deployment, check these items:

- `EBS root volume`
  - OS disk, package cache, logs, temporary files
- `ALB`
  - hourly charge
  - LCU usage based on requests, active connections, bytes, and rule evaluations
- `S3`
  - model storage
  - PUT/GET/LIST requests
  - cross-region transfer if your bucket and EC2 instance are in different Regions
- `Data transfer`
  - internet egress from the ALB or EC2
  - intra-AZ or cross-AZ traffic if you scale out later
- `Public IPv4`
  - public IPv4 addresses now carry a separate charge in many AWS setups
- `CloudWatch`
  - log ingestion and retention if you centralize service logs
- `ACM / Route 53`
  - certificate is usually low or zero direct cost
  - hosted zone and DNS query charges still apply

### Hidden cost reference box

These are public AWS pricing references I verified online from AWS pricing pages and docs, not from the price-list API:

- `ALB hourly and LCU charges`
  - AWS Elastic Load Balancing public pricing examples show `Application Load Balancer` at `$0.0225 per hour` plus `$0.008 per LCU-hour`
  - Fixed ALB fee only:
    - business-hours schedule `8h/day, 5d/week`: about `$3.90/month`
    - always-on `730h/month`: about `$16.43/month`
  - LCU charges are extra and scale with the highest measured dimension such as new connections, active connections, processed bytes, or rule evaluations
- `EBS root volume`
  - AWS EBS public pricing examples show `gp3` storage at `$0.08 per GB-month` in the example priced region
  - AWS also shows extra `gp3` performance pricing at `$0.005 per provisioned IOPS-month` above baseline and `$0.06 per provisioned MB/s-month` above baseline
  - Reference examples:
    - `100 GB` root volume: about `$8.00/month`
    - `200 GB` root volume: about `$16.00/month`
- `S3 model storage and request volume`
  - AWS S3 pricing docs state the first `100 GB/month` of internet data transfer out is free, aggregated across AWS services except China and GovCloud
  - AWS S3 FAQs state data transfer between `EC2` and `S3` in the same Region is free, which helps when your Singapore EC2 instance pulls model weights from a Singapore S3 bucket
  - For a Singapore storage-class reference available from AWS public announcements, AWS lists `S3 Standard-IA` in `Asia Pacific (Singapore)` at `$0.0138 per GB-month`
  - For exact current `S3 Standard` storage and request pricing in Singapore, check the live S3 pricing page or AWS Pricing Calculator before approval

## 4. Practical cost checklist before launch

- Pick the Region first and keep S3 + EC2 in the same Region.
- Decide whether this is production, staging, or experiment.
- Decide whether the stack will be manually started and stopped on a business-hours schedule.
- If production and interruption-sensitive, default to On-Demand.
- If cost-sensitive and interruption-tolerant, evaluate Spot with a fallback relaunch process.
- Confirm the `g4dn.12xlarge` quota for your account and Region.
- Estimate monthly runtime:
  - business-hours `8h/day`, `5d/week`
  - always-on `730h`
  - burst workload
- Decide whether the `1 GPU` scenario is only for dev/test.
- Decide whether the `8 GPU` scenario is for redundancy or throughput.
- Add ALB, S3, and data-transfer estimates before final approval.
- Set a Cost Explorer budget and billing alarm before launch.

## 5. Recommendation by scenario

- Cheapest realistic dev/test:
  - `g4dn.xlarge` only if you are testing one GPU service at a time
- Cheapest full-stack path:
  - `1 x g4dn.12xlarge` Spot, only if interruptions are acceptable
- Safest full-stack path:
  - `1 x g4dn.12xlarge` On-Demand
- Scaled production path:
  - `2 x g4dn.12xlarge` with one ALB and path-based routing, preferably On-Demand or mixed purchase model

## 6. Quick formulas

Use these formulas for your own revisions:

- per-day business-hours cost = `hourly_rate x 8`
- per-week business-hours cost = `hourly_rate x 40`
- business-hours monthly cost = `hourly_rate x (40 x 52 / 12)`
- always-on monthly cost = `hourly_rate x 730`
- spot estimate = `on_demand_monthly x (1 - discount_rate)`
- 2-instance cost = `single_instance_cost x 2`

Example:

- `g4dn.12xlarge` business-hours monthly = `5.474 x 173.33 = 948.83`
- `g4dn.12xlarge` always-on monthly = `5.474 x 730 = 3996.02`
