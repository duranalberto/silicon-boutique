# AWS EKS Terraform

This Terraform root is the bounded AWS scaffold for SiliconBoutique. It renders an EKS-shaped benchmark environment with a run-scoped VPC, subnets, EKS cluster, managed node group, tags, node labels, and workflow metadata outputs.

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

## Scaffold Boundaries

P8.3 does not implement production AWS OIDC, IAM policy hardening, or a live AWS benchmark workflow. The existing Helm workload, monitoring chart, metric extraction, summary generation, BigQuery load, and comparison reporting scripts should be reused once a guarded AWS workflow is promoted beyond scaffold status.

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
