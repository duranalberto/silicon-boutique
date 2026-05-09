# Terraform

This directory contains the infrastructure definitions for SiliconBoutique across local and cloud workflows.

Current roots:

- `local-kubernetes/`: creates the local benchmark namespace in the devcontainer-managed `siliconboutique` minikube profile.
- `gcp-gke/`: provisions the first GCP rollout path with a dedicated VPC, subnet, GKE cluster, and benchmark node pool.
- `gcp-bigquery/`: provisions durable BigQuery benchmark summary history outside run-scoped teardown.
- `aws-eks/`: static-validation scaffold for a future AWS EKS benchmark path using the same metadata and workload contract.

## Naming, Labels, and Teardown

Terraform roots use a shared run contract:

- `run_id` is the durable benchmark identifier. Provide it explicitly for automation; otherwise Terraform generates one and keeps it stable in state.
- Local Kubernetes resources use the `silicon-boutique-${run_id}` naming prefix.
- GCP resources use the shorter `sb-${run_id}` naming prefix to leave room for provider suffixes.
- AWS scaffold resources also use the shorter `sb-${run_id}` naming prefix and `RunId` tags.
- Label-capable resources include run metadata for environment, machine type, processor family, architecture, and Terraform ownership.
- Teardown-owned resources are marked with `destroy-after-run` metadata where the platform supports labels or annotations.

Before teardown, capture `terraform output run_id`, `terraform output labels`, and `terraform output teardown_check_commands`. After teardown, use those commands to confirm the run-scoped resources no longer exist. Never delete resources that do not match the active `run_id`.

## Local Kubernetes

The local path assumes `.devcontainer/post-create.sh` has already started or validated the `siliconboutique` minikube profile. Terraform manages the benchmark namespace only; it does not manage the local cluster lifecycle.

```bash
cd infra/terraform/local-kubernetes
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan
terraform apply -auto-approve
terraform output namespace
terraform output labels
terraform output teardown_check_commands
terraform destroy -auto-approve
```

## GCP GKE

The GCP path is apply-capable, but routine validation should remain bounded and should not create cloud resources unless a project, credentials, and teardown window are explicitly confirmed.

```bash
cd infra/terraform/gcp-gke
timeout 20s terraform fmt -check -recursive
timeout 60s terraform init -backend=false -input=false
timeout 30s terraform validate
timeout 60s terraform plan -refresh=false -input=false -var='project_id=example-project'
```

Cloud execution commands must stay time-bounded:

```bash
timeout 10m terraform plan -input=false -var='project_id=<project-id>' -var='static_validation_mode=false'
timeout 30m terraform apply -auto-approve -var='project_id=<project-id>' -var='static_validation_mode=false'
terraform output get_credentials_command
terraform output labels
terraform output teardown_check_commands
timeout 30m terraform destroy -auto-approve -var='project_id=<project-id>' -var='static_validation_mode=false'
```

## GCP BigQuery

The BigQuery path manages persistent benchmark history. It is not coupled to the ephemeral GKE root and must not be destroyed as part of normal benchmark teardown.

```bash
cd infra/terraform/gcp-bigquery
timeout 20s terraform fmt -check -recursive
timeout 60s terraform init -backend=false -input=false
timeout 30s terraform validate
timeout 60s terraform plan -refresh=false -input=false -var='project_id=example-project'
```

The default destination is `<project-id>.silicon_boutique.benchmark_summaries` in location `US`. The benchmark workflow service account needs permission to inspect the table, query duplicate `run_id` values, and load rows.

## AWS EKS Scaffold

The AWS root is scaffold-only for P8.3. It should validate without AWS credentials and should not be applied until AWS account access, IAM scope, and teardown expectations are explicitly reviewed.

```bash
cd infra/terraform/aws-eks
timeout 20s terraform fmt -check -recursive
timeout 60s terraform init -backend=false -input=false
timeout 30s terraform validate
timeout 60s terraform plan -refresh=false -input=false
```

Live AWS execution requires credentials outside Terraform state and uses the `get_credentials_command` output to configure kubeconfig after apply.
