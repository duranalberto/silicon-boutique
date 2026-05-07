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

## Local Workload Validation

After local Terraform creates the benchmark namespace, deploy the P2 workload chart into that namespace. The chart pins Google's `onlineboutique` Helm chart to `0.10.5` and uses a post-renderer to apply SiliconBoutique run labels, teardown annotations, and load-generator settings to rendered resources.

```bash
cd infra/terraform/local-kubernetes
terraform apply -auto-approve
namespace="$(terraform output -raw namespace)"
run_id="$(terraform output -raw run_id)"
environment="$(terraform output -raw environment)"
machine_type="$(terraform output -raw machine_type)"
processor_family="$(terraform output -raw processor_family)"
architecture="$(terraform output -raw architecture)"
cd ../../..

helm dependency update k8s/charts/silicon-boutique-online-boutique
helm lint k8s/charts/silicon-boutique-online-boutique
helm plugin list | awk 'NR > 1 {print $1}' | grep -qx silicon-boutique-metadata \
  || helm plugin install k8s/charts/silicon-boutique-online-boutique/post-renderer
helm upgrade --install silicon-boutique-online-boutique \
  ./k8s/charts/silicon-boutique-online-boutique \
  --namespace "$namespace" \
  --kube-context siliconboutique \
  --set-string siliconBoutique.runId="$run_id" \
  --set-string siliconBoutique.environment="$environment" \
  --set-string siliconBoutique.machineType="$machine_type" \
  --set-string siliconBoutique.processorFamily="$processor_family" \
  --set-string siliconBoutique.architecture="$architecture" \
  --set siliconBoutique.loadGenerator.concurrentUsers=10 \
  --set siliconBoutique.loadGenerator.usersPerSecond=1 \
  --set-string siliconBoutique.loadGenerator.testDuration=20m \
  --post-renderer silicon-boutique-metadata

kubectl wait deployment --all \
  --for=condition=Available \
  --timeout=10m \
  --namespace "$namespace" \
  --context siliconboutique
kubectl get pods,services --namespace "$namespace" --context siliconboutique
```

## Local Monitoring Validation

After the local workload is installed and ready, deploy the P2.3 monitoring chart into the same Terraform-owned namespace. The chart installs Prometheus with 24-hour retention, Kubernetes metric exporters, and a blackbox frontend probe for HTTP latency.

```bash
helm dependency update k8s/charts/silicon-boutique-monitoring
helm lint k8s/charts/silicon-boutique-monitoring
helm template sb-monitoring \
  ./k8s/charts/silicon-boutique-monitoring \
  --namespace "$namespace" \
  --set-string siliconBoutique.runId="$run_id" \
  --set-string siliconBoutique.environment="$environment" \
  --set-string siliconBoutique.machineType="$machine_type" \
  --set-string siliconBoutique.processorFamily="$processor_family" \
  --set-string siliconBoutique.architecture="$architecture" \
  --set-string siliconBoutique.workloadNamespace="$namespace"

helm upgrade --install sb-monitoring \
  ./k8s/charts/silicon-boutique-monitoring \
  --namespace "$namespace" \
  --kube-context siliconboutique \
  --set-string siliconBoutique.runId="$run_id" \
  --set-string siliconBoutique.environment="$environment" \
  --set-string siliconBoutique.machineType="$machine_type" \
  --set-string siliconBoutique.processorFamily="$processor_family" \
  --set-string siliconBoutique.architecture="$architecture" \
  --set-string siliconBoutique.workloadNamespace="$namespace"

kubectl rollout status deployment/sb-monitoring-kube-state-metrics \
  --namespace "$namespace" \
  --context siliconboutique \
  --timeout=10m
kubectl rollout status deployment/sb-monitoring-prometheus-blackbox-exporter \
  --namespace "$namespace" \
  --context siliconboutique \
  --timeout=10m
kubectl rollout status daemonset/sb-monitoring-prometheus-node-exporter \
  --namespace "$namespace" \
  --context siliconboutique \
  --timeout=10m
kubectl wait pod \
  --for=condition=Ready \
  --selector app.kubernetes.io/name=prometheus \
  --timeout=10m \
  --namespace "$namespace" \
  --context siliconboutique
```

Port-forward Prometheus and confirm the local benchmark signals have samples. Run the port-forward in one terminal:

```bash
kubectl port-forward service/sb-monitoring-kube-prometh-prometheus \
  9090:9090 \
  --namespace "$namespace" \
  --context siliconboutique
```

Then query from another terminal:

```bash
prometheus='http://127.0.0.1:9090/api/v1/query'
curl -fsG "$prometheus" --data-urlencode "query=sum(rate(container_cpu_usage_seconds_total{namespace=\"$namespace\",container!=\"\",image!=\"\"}[5m]))"
curl -fsG "$prometheus" --data-urlencode "query=sum(container_memory_working_set_bytes{namespace=\"$namespace\",container!=\"\",image!=\"\"})"
curl -fsG "$prometheus" --data-urlencode "query=sum(rate(container_cpu_cfs_throttled_periods_total{namespace=\"$namespace\",container!=\"\",image!=\"\"}[5m])) / sum(rate(container_cpu_cfs_periods_total{namespace=\"$namespace\",container!=\"\",image!=\"\"}[5m]))"
curl -fsG "$prometheus" --data-urlencode "query=kube_pod_info{namespace=\"$namespace\"}"
curl -fsG "$prometheus" --data-urlencode "query=probe_duration_seconds{silicon_boutique_component=\"frontend-probe\"}"
curl -fsG "$prometheus" --data-urlencode "query=silicon_boutique:frontend_probe_latency_seconds"
```

Extract the benchmark window into structured P3.1 metrics JSON. Set the window to the actual load-test period; the example below uses the latest 20 minutes:

```bash
benchmark_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
benchmark_start="$(date -u -d '20 minutes ago' +%Y-%m-%dT%H:%M:%SZ)"

python3 automation/scripts/extract_prometheus_metrics.py \
  --prometheus-url http://127.0.0.1:9090 \
  --run-id "$run_id" \
  --namespace "$namespace" \
  --start "$benchmark_start" \
  --end "$benchmark_end" \
  --step 15s \
  --output artifacts/prometheus-metrics.json \
  --strict
```

Generate the P3.2 benchmark summary and persist a local BigQuery-ready NDJSON row. Direct BigQuery loading is deferred to later automation work, but the store format is intended to be loadable without manual cleanup:

```bash
python3 automation/scripts/generate_benchmark_summary.py \
  --metrics-input artifacts/prometheus-metrics.json \
  --summary-output artifacts/benchmark-summary.json \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --environment "$environment" \
  --machine-type "$machine_type" \
  --processor-family "$processor_family" \
  --architecture "$architecture" \
  --cloud-provider local \
  --strict
```

Validate the local summary store before using rows for cross-machine comparisons. P3.3 is a local quality gate; direct BigQuery loading and cost comparability remain later work.

```bash
python3 automation/scripts/validate_benchmark_comparability.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparability-report.json \
  --min-duration-seconds 1200 \
  --min-coverage-ratio 0.95 \
  --strict
```

Clean up monitoring before uninstalling the workload and destroying the Terraform-owned namespace:

```bash
helm uninstall sb-monitoring \
  --namespace "$namespace" \
  --kube-context siliconboutique

helm uninstall silicon-boutique-online-boutique \
  --namespace "$namespace" \
  --kube-context siliconboutique
cd infra/terraform/local-kubernetes
terraform destroy -auto-approve
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
