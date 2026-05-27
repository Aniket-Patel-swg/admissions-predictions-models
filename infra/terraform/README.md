# Terraform — Admissions Predictors

Three independent stacks, one per ML predictor service, all built on a shared `predictor-lambda` module. CI/CD is GitHub Actions; AWS auth is via OIDC (no long-lived keys).

```
infra/terraform/
├── bootstrap/                          # one-time setup (state bucket + GH OIDC role)
├── modules/
│   └── predictor-lambda/               # ECR + IAM + LogGroup + Lambda + Function URL
└── stacks/
    ├── college-predictor/              # ~10 lines, instantiates the module
    ├── marks-predictor/
    └── guject-percentile-predictor/
```

Each stack keeps its **own state file** in S3 (blast-radius isolation), but all infra logic lives in the single module — so changes to the shared shape only need to be made once.

## What the module provisions

- ECR repository (image-scan on push, lifecycle policy retains last 10 images)
- IAM role for Lambda (basic execution)
- CloudWatch log group with 14-day retention
- Lambda function (container image, `ignore_changes = [image_uri]` so GitHub Actions owns rollouts)
- Lambda Function URL (HTTPS endpoint, no API Gateway)

## Pipeline shape

```
push to main
   │
   ├─ <service>/**    changed → .github/workflows/<service>.yml
   │                            └─ docker build → ECR push → aws lambda update-function-code
   │
   └─ infra/terraform/** changed → .github/workflows/terraform-infra.yml
                                   └─ terraform plan → terraform apply (per stack matrix)
```

Two workflows, two responsibilities:
- **Per-service workflows** roll out new images. Fast (~3–4 min). They never touch Terraform.
- **Terraform workflow** changes infra (memory, env vars, auth). Plan-only on PRs, apply on merge.

## One-time bootstrap

You only do this **once per AWS account**, from your laptop, before the GitHub workflows can run.

```bash
cd infra/terraform/bootstrap
cp terraform.tfvars.example terraform.tfvars
#   → set github_owner + github_repo
terraform init
terraform apply
#   → copy output `github_actions_role_arn` and `aws_account_id`
```

Then in GitHub: **Settings → Secrets and variables → Actions → New repository secret**, add:

| Secret name             | Value                                               |
| ----------------------- | --------------------------------------------------- |
| `AWS_ACCOUNT_ID`        | `aws_account_id` output from bootstrap              |
| `AWS_DEPLOY_ROLE_ARN`   | `github_actions_role_arn` output from bootstrap     |

That's it. Everything else runs from CI.

## First-time per-service apply

The Lambda needs an image to exist in ECR before the full `terraform apply` succeeds. From your laptop, once per service:

```bash
cd infra/terraform/stacks/college-predictor
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply -target=module.predictor.aws_ecr_repository.this   # step 1: create the repo
#   ↳ trigger the GH Actions workflow for college-predictor (push or workflow_dispatch).
#     It builds & pushes :latest into the new repo.
terraform apply                                                    # step 2: create everything else
```

Repeat for `marks-predictor` and `guject-percentile-predictor`. Then plug each `lambda_function_url` output into the Node backend env (`COLLEGE_PREDICTOR_URL`, `MARKS_PREDICTOR_URL`, `PERCENTILE_PREDICTOR_URL`).

After bootstrap, GitHub Actions owns image rollouts. The Terraform workflow re-applies only when you change infra config.

## Day-to-day flow

| You did this                                       | What happens                                                      |
| -------------------------------------------------- | ----------------------------------------------------------------- |
| Edit `college-predictor/college_predictor.py`      | `college-predictor.yml` runs → new image → Lambda updated         |
| Edit `infra/terraform/stacks/.../main.tf` on a PR  | `terraform-infra.yml` posts a plan in the run summary             |
| Merge that PR                                      | `terraform-infra.yml` applies the plan to all 3 stacks (matrix)   |
| Manual redeploy needed                             | Actions tab → pick the workflow → **Run workflow**                |

## Module inputs

| Variable                          | Default      | When to change                                                              |
| --------------------------------- | ------------ | --------------------------------------------------------------------------- |
| `image_tag`                       | `latest`     | First-time bootstrap; CI overrides on subsequent deploys                    |
| `memory_size`                     | `2048`       | Tune after profiling. Increase if CSV load OOMs                             |
| `timeout`                         | `30`         | Function URL hard ceiling — don't raise                                     |
| `architecture`                    | `arm64`      | Use `"x86_64"` only if you need amd64-only native deps (also set workflow `platform` to `linux/amd64`) |
| `authorization_type`              | `NONE`       | Flip to `"AWS_IAM"` in production (see § Locking it down)                   |
| `cors_allow_origins`              | `["*"]`      | Restrict to actual frontend origin, or drop entirely if server-to-server    |
| `reserved_concurrent_executions`  | `-1`         | Set to `20` (or similar) to cap blast radius + cost                         |
| `env_vars`                        | `{}`         | Per-service env (e.g. `ACPC_CSV`, `RATE_LIMIT`)                             |

## Locking down `authorization_type = "NONE"`

Today the Function URLs are public. Two options:

### Option A (recommended): `AWS_IAM` + SigV4 from the Node backend

1. In each stack's `terraform.tfvars`:
   ```hcl
   authorization_type = "AWS_IAM"
   cors_allow_origins = []   # server-to-server only
   ```
2. Grant the Node backend's Lambda role permission to invoke each predictor URL:
   ```hcl
   resource "aws_iam_role_policy" "invoke_predictors" {
     role = aws_iam_role.backend_lambda.id
     policy = jsonencode({
       Version = "2012-10-17"
       Statement = [{
         Effect   = "Allow"
         Action   = "lambda:InvokeFunctionUrl"
         Resource = [
           "arn:aws:lambda:ap-south-1:<acct>:function:college-predictor",
           "arn:aws:lambda:ap-south-1:<acct>:function:marks-predictor",
           "arn:aws:lambda:ap-south-1:<acct>:function:guject-percentile-predictor",
         ]
         Condition = { StringEquals = { "lambda:FunctionUrlAuthType" = "AWS_IAM" } }
       }]
     })
   }
   ```
3. Sign outbound POSTs in the Node clients with `aws4-axios`.

### Option B (lighter): keep `NONE`, put AWS WAF in front

- Attach a `aws_wafv2_web_acl` with rate-limit + IP allowlist. ~$5/mo per ACL, no code changes.

Pick A for real production. B is fine as a stopgap.
