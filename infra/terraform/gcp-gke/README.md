# GCP GKE Terraform

This Terraform root provisions the first GCP rollout path for SiliconBoutique: a dedicated VPC, subnet, GKE cluster, and managed benchmark node pool.

Routine validation is intentionally bounded and does not apply cloud resources:

```bash
timeout 20s terraform fmt -check -recursive
timeout 60s terraform init -backend=false -input=false
timeout 30s terraform validate
timeout 60s terraform plan -refresh=false -input=false -var='project_id=example-project'
```

Only run apply or destroy after confirming the GCP project, credentials, and teardown window:

```bash
timeout 10m terraform plan -input=false -var='project_id=<project-id>' -var='static_validation_mode=false'
timeout 30m terraform apply -auto-approve -var='project_id=<project-id>' -var='static_validation_mode=false'
terraform output get_credentials_command
timeout 30m terraform destroy -auto-approve -var='project_id=<project-id>' -var='static_validation_mode=false'
```

The `get_credentials_command` output is provided for later workflow steps so Terraform does not write kubeconfig material into state.

## Naming, Labels, and Teardown

The default GCP resource prefix is `sb-${run_id}`. The cluster uses the prefix directly, while the network and subnet use `-vpc` and `-subnet` suffixes. Label-capable GCP resources receive the rendered labels exposed by:

```bash
terraform output labels
terraform output node_labels
terraform output gcp_label_filter
terraform output managed_resource_names
terraform output teardown_check_commands
```

Destroy must remove the run-scoped GKE cluster, node pool, VPC, and subnet. Before retrying a failed destroy, inspect Terraform state and confirm every manual check still matches the active `run_id`.
