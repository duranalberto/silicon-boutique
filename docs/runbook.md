# Runbook

## Local Development

1. Open the repository in the devcontainer.
2. Verify the environment has Terraform, kubectl, Helm, Python, Docker, and minikube.
3. Let the devcontainer bootstrap the local `siliconboutique` minikube profile; the post-create script now checks the toolchain, verifies Docker access, and starts or validates the profile automatically.
4. Review `docs/spec-driven-development.md` and `docs/project-layout.md`.
5. Review `docs/architecture.md` and `docs/roadmap.md` for the current pipeline language and phase order.

The devcontainer pins the local toolchain baseline used by Phase 0 validation:

| Tool | Baseline |
| --- | --- |
| Terraform | 1.15.2 |
| kubectl | 1.36.0 |
| Helm | 4.1.4 |
| minikube | 1.38.1 |

The managed minikube profile is `siliconboutique`, uses the Docker driver, and runs Kubernetes `v1.35.1`. The devcontainer runs with host networking so minikube can reach the Docker driver SSH and API ports published on `127.0.0.1`.

Run the reusable check any time the container is rebuilt or the local environment looks suspicious:

```bash
.devcontainer/verify-toolchain.sh
```

## Benchmark Execution Flow

1. Provision the target environment with Terraform.
2. Deploy the Kubernetes workload and monitoring stack with Helm.
3. Start the benchmark run.
4. Collect metrics and produce a summary payload.
5. Teardown the infrastructure when complete.

## Naming and Labels

Every benchmark run is keyed by one DNS-safe `run_id`. When a caller does not provide one, Terraform generates a stable ID in state. Local resource names use `silicon-boutique-${run_id}` and GCP resource names use `sb-${run_id}` with resource suffixes such as `-vpc` and `-subnet`.

All label-capable resources must carry the run metadata needed for traceability:

- `run_id` or `silicon-boutique/run-id`
- `environment` or `silicon-boutique/environment`
- `machine_type` or `silicon-boutique/machine-type`
- `processor_family` or `silicon-boutique/processor-family`
- `architecture` or `silicon-boutique/architecture`
- `managed_by=terraform` where the platform supports plain GCP labels

The Terraform roots expose the rendered labels and selectors with `terraform output labels`, `terraform output kubernetes_label_selector`, or `terraform output gcp_label_filter`.

## Local Terraform Validation

The local Kubernetes Terraform path creates an isolated benchmark namespace in the devcontainer-managed `siliconboutique` minikube profile. It assumes the profile already exists and does not start or destroy minikube.

```bash
cd infra/terraform/local-kubernetes
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan
terraform apply -auto-approve
namespace="$(terraform output -raw namespace)"
kubectl get namespace "$namespace" --context siliconboutique --show-labels
terraform output teardown_check_commands
terraform destroy -auto-approve
! kubectl get namespace "$namespace" --context siliconboutique
```

## Cloud Rollout

1. Use GCP for the first cloud benchmark target after local validation is complete.
2. Confirm cloud credentials and Terraform state are configured before applying.
3. Run the same deployment and benchmark flow used in local Kubernetes.
4. Preserve teardown discipline to avoid leaving cloud resources running.

## GCP Terraform Validation

The GCP rollout path provisions a dedicated VPC, subnet, GKE cluster, and benchmark node pool. Routine checks should stay bounded and should not create cloud resources.

```bash
cd infra/terraform/gcp-gke
timeout 20s terraform fmt -check -recursive
timeout 60s terraform init -backend=false -input=false
timeout 30s terraform validate
timeout 60s terraform plan -refresh=false -input=false -var='project_id=example-project'
```

Only run cloud execution after confirming credentials, project ID, and the teardown window:

```bash
timeout 10m terraform plan -input=false -var='project_id=<project-id>' -var='static_validation_mode=false'
timeout 30m terraform apply -auto-approve -var='project_id=<project-id>' -var='static_validation_mode=false'
terraform output get_credentials_command
timeout 5m $(terraform output -raw get_credentials_command)
terraform output teardown_check_commands
timeout 30m terraform destroy -auto-approve -var='project_id=<project-id>' -var='static_validation_mode=false'
```

## Teardown Checks

- Confirm the run has finished collecting data before destroying infrastructure.
- Confirm any persisted summaries have been written.
- Capture `terraform output run_id`, `terraform output labels`, and the matching teardown check commands before destroy.
- For local runs, verify the benchmark namespace exists before destroy and is gone after destroy.
- For GCP runs, verify the cluster, VPC, and subnet names or labels before destroy and confirm they no longer appear after destroy.
- Do not destroy shared minikube profiles, GCP projects, credentials, state buckets, or resources that do not match the run ID.
- If destroy fails, inspect Terraform state and provider errors before retrying; do not manually delete unrelated resources to force state clean.

## Troubleshooting

- If minikube does not start, confirm Docker is available to the devcontainer and that the Docker socket is mounted.
- If the configured minikube profile has a corrupt or unreadable config, the devcontainer bootstrap deletes and recreates only that named local profile.
- If the cloud rollout fails, recheck GCP authentication, project selection, and Terraform provider settings.
- If Terraform fails, inspect state and provider configuration first.
- If Kubernetes resources do not appear, verify the cluster context and namespace.
