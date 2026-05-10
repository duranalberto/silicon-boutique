# AWS EKS Terraform

This Terraform root provisions the bounded AWS EKS benchmark environment for SiliconBoutique. It renders a run-scoped VPC, subnets, EKS cluster, managed node group, tags, node labels, and workflow metadata outputs.

Routine validation is intentionally static and does not require AWS credentials:

```bash
timeout 20s terraform fmt -check -recursive
timeout 60s terraform init -backend=false -input=false
timeout 30s terraform validate
timeout 60s terraform plan -refresh=false -input=false
```

Only run apply or destroy after confirming AWS credentials, account, region, and teardown window:

```bash
timeout 10m terraform plan -input=false -var='static_validation_mode=false'
timeout 30m terraform apply -auto-approve -var='static_validation_mode=false'
terraform output get_credentials_command
timeout 5m $(terraform output -raw get_credentials_command)
timeout 30m terraform destroy -auto-approve -var='static_validation_mode=false'
```

The `get_credentials_command` output is provided for later workflow steps so Terraform does not write kubeconfig material into state.

## Workflow Boundary

Live AWS execution is orchestrated by `.github/workflows/benchmark-aws.yml` with GitHub OIDC through `AWS_ROLE_TO_ASSUME`. That workflow applies this root with `static_validation_mode=false`, configures kubeconfig from `get_credentials_command`, deploys the shared Helm workload and monitoring charts, writes canonical benchmark artifacts, loads summaries to BigQuery, and destroys the run-scoped resources.

## Naming, Tags, and Teardown

The default AWS resource prefix is `sb-${run_id}`. Tag-capable AWS resources receive:

```bash
terraform output tags
terraform output node_labels
terraform output aws_tag_filter
terraform output managed_resource_names
terraform output teardown_check_commands
```

Destroy must remove only run-scoped AWS resources that match the active `run_id`. Before retrying a failed destroy, inspect Terraform state and confirm every manual check still matches the active run.
