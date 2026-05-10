# Runbook

For first-time local setup and day-one usage, start with [`docs/local-usage.md`](local-usage.md). This runbook is the deeper operating reference for local validation, cloud rollout, teardown, and troubleshooting.

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
- Canonical summary rows must also include normalized `region`, `zone`, `node_count`, `pricing_model`, `load_profile_source`, and optional `cpu_platform`.
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

## Local Benchmark Automation

Use the local automation entrypoint when you want the same workflow shape as the GCP benchmark job without dispatching GitHub Actions. The command provisions the local Terraform namespace, deploys workload and monitoring charts, runs the benchmark window, extracts metrics, generates and validates the summary, captures workflow trace artifacts, and tears down the namespace.

```bash
python3 automation/scripts/run_local_benchmark.py
```

For a shorter local smoke run, lower the summary duration threshold to match the measured window:

```bash
python3 automation/scripts/run_local_benchmark.py \
  --run-id local-smoke \
  --test-duration 2m \
  --min-duration-seconds 60
```

The generated `artifacts/` directory uses the same artifact names as the GitHub workflow, including `prometheus-metrics.json`, `benchmark-summary.json`, `benchmark-summaries.ndjson`, `comparability-report.json`, `workflow-trace.json`, `workflow-trace.env`, and teardown logs. Use `--failure-stage after_provision`, `--failure-stage after_monitoring_ready`, or `--failure-stage before_extract` only to validate cleanup behavior. Use `--skip-destroy` only when intentionally debugging local resources.

To inspect the Grafana dashboard after a local automated run, use `--skip-destroy`, port-forward Grafana from the benchmark namespace, and manually clean up the Helm releases plus Terraform namespace when finished.

## Acceptance Demo

Use the acceptance demo when you want one command that proves the required use case end to end. The local path provisions the benchmark namespace, deploys Online Boutique and monitoring, runs the load generator, extracts Prometheus and load-generator metrics, generates and validates a `BenchmarkSummary`, verifies Grafana dashboard evidence, writes `artifacts/acceptance-demo-report.json`, and then tears down the namespace.

```bash
python3 automation/scripts/run_acceptance_demo.py --mode local
```

For a short smoke demo in the devcontainer:

```bash
python3 automation/scripts/run_acceptance_demo.py \
  --mode local \
  --run-id local-demo \
  --test-duration 2m \
  --min-duration-seconds 60
```

Local BigQuery persistence is optional. When all BigQuery inputs are provided, the demo loads the generated summary row with the same loader used by the GCP workflow; otherwise the acceptance report records BigQuery as `skipped_optional`.

```bash
python3 automation/scripts/run_acceptance_demo.py \
  --mode local \
  --bigquery-project-id "$project_id" \
  --bigquery-dataset silicon_boutique \
  --bigquery-table benchmark_summaries \
  --bigquery-location US
```

To briefly inspect Grafana before cleanup, use a bounded hold. The report records the local URL, dashboard UID, and dashboard title, then cleanup resumes automatically after the hold expires.

```bash
python3 automation/scripts/run_acceptance_demo.py \
  --mode local \
  --dashboard-hold-seconds 120
```

The GCP benchmark workflow supports the same acceptance evidence path through the `acceptance_demo` dispatch input. When enabled, `.github/workflows/benchmark.yml` verifies the dashboard ConfigMap, Prometheus metric artifact, canonical summary, BigQuery load report, and acceptance `run_id` before teardown. It does not publish Grafana publicly; dashboard location is represented by the Grafana service name and dashboard UID in `acceptance-demo-report.json` and the GitHub step summary.

Expected acceptance artifacts:

- `acceptance-demo-report.json`
- `workflow-trace.json`
- `benchmark-summary.json`
- `benchmark-summaries.ndjson`
- `comparability-report.json`
- `prometheus-metrics.json`
- `loadgenerator-stats.json`
- `bigquery-load-report.json` when BigQuery persistence runs

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
python3 -m unittest discover -s k8s/tests
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

After the local workload is installed and ready, deploy the P2.3 monitoring chart into the same Terraform-owned namespace. The chart installs Prometheus with 24-hour retention, Grafana with a private ClusterIP service, Kubernetes metric exporters, a blackbox frontend probe for HTTP latency, and the `SiliconBoutique Online Boutique Benchmark` dashboard.

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
```

The rendered output should include a dashboard `ConfigMap` labeled `grafana_dashboard: "1"`.

```bash
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

kubectl rollout status deployment/sb-monitoring-grafana \
  --namespace "$namespace" \
  --context siliconboutique \
  --timeout=10m
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

To inspect the dashboard locally, keep the namespace alive and port-forward Grafana:

```bash
kubectl port-forward service/sb-monitoring-grafana \
  3000:80 \
  --namespace "$namespace" \
  --context siliconboutique
```

In another terminal, read the generated admin password:

```bash
kubectl get secret sb-monitoring-grafana \
  --namespace "$namespace" \
  --context siliconboutique \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

Log in at `http://127.0.0.1:3000` with user `admin`, then open `SiliconBoutique Online Boutique Benchmark`. The dashboard defaults to the last 30 minutes so short local smoke runs are visible; use the time picker to match the exact benchmark window.

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
curl -fsG "$prometheus" --data-urlencode "query=silicon_boutique:workload_cpu_utilization_pct{run_id=\"$run_id\",workload_namespace=\"$namespace\"}"
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

Capture Locust request volume from the load generator logs:

```bash
kubectl logs deployment/loadgenerator \
  --namespace "$namespace" \
  --context siliconboutique > artifacts/loadgenerator.log

python3 automation/scripts/extract_loadgenerator_stats.py \
  --logs-input artifacts/loadgenerator.log \
  --output artifacts/loadgenerator-stats.json \
  --run-id "$run_id" \
  --strict
```

Generate the P3.2 benchmark summary and persist a local BigQuery-ready NDJSON row. The summary includes `avg_cpu_utilization_pct`, `max_cpu_utilization_pct`, request volume, load-profile metadata, and nullable cost fields:

```bash
python3 automation/scripts/generate_benchmark_summary.py \
  --metrics-input artifacts/prometheus-metrics.json \
  --loadgenerator-stats artifacts/loadgenerator-stats.json \
  --summary-output artifacts/benchmark-summary.json \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --environment "$environment" \
  --machine-type "$machine_type" \
  --processor-family "$processor_family" \
  --architecture "$architecture" \
  --cloud-provider local \
  --region local \
  --zone local \
  --node-count 1 \
  --pricing-model local \
  --concurrent-users "$concurrent_users" \
  --users-per-second "$users_per_second" \
  --load-profile-source manual \
  --strict
```

For GCP summaries, pass `--region`, `--zone`, `--pricing-model`, optional `--cpu-platform`, and `--pricing-table automation/templates/machine-pricing.json` so `benchmark_compute_cost_usd` and `cost_per_1m_requests_usd` are populated from the repo-owned pricing table. The GCP workflow maps `pricing_model=spot` to Spot nodes and `pricing_model=on_demand` to regular on-demand nodes.

To calibrate local load settings before a comparison run:

```bash
python3 automation/scripts/calibrate_load_profile.py \
  --execute-local \
  --output artifacts/load-profile-calibration.json \
  --initial-concurrent-users 10 \
  --initial-users-per-second 1 \
  --trial-duration 5m

python3 automation/scripts/run_local_benchmark.py \
  --load-profile-file artifacts/load-profile-calibration.json
```

To calibrate against the GCP benchmark workflow, dispatch trial runs with the same target band and load settings. After each trial artifact is available under `artifacts/calibration/trial-<n>/benchmark-summary.json`, rerun the command to continue selection:

```bash
python3 automation/scripts/calibrate_load_profile.py \
  --execute-gcp \
  --project-id "$project_id" \
  --output artifacts/load-profile-calibration.json \
  --machine-type e2-standard-4 \
  --processor-family e2 \
  --trial-duration 5m
```

Selected calibration profiles record `load_profile_source=calibration`, source run IDs, target CPU band, machine metadata, observed utilization, and request failure ratio. Pass the selected values to `.github/workflows/benchmark.yml` with `load_profile_source=calibration` for calibrated GCP runs.

Validate the current summary row after summary generation. Use summary mode with `--run-id` so append-only historical rows from smoke or demo runs do not fail the current run's quality gate.

```bash
python3 automation/scripts/validate_benchmark_comparability.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparability-report.json \
  --run-id "$run_id" \
  --mode summary \
  --min-duration-seconds 1200 \
  --min-coverage-ratio 0.95 \
  --strict
```

Before using accumulated rows for cross-machine comparisons, rerun the same validator without `--run-id` and with `--mode comparability`; that mode validates the historical store and requires at least two comparable rows. For local comparison acceptance without cloud credentials, prefer the split-evidence helper because `artifacts/benchmark-summaries.ndjson` can contain legacy, smoke, or demo rows:

```bash
python3 automation/scripts/validate_local_comparison.py
```

The helper writes valid-only comparability evidence and mixed comparison-report evidence under `artifacts/local-comparison-validation/`. Treat `pass` on the valid-only `comparability-report.json` as the quality gate, `warn` on the mixed `comparison-report.json` as expected when rejected-row evidence is present, and `fail` as a blocked comparison with no usable groups or schema drift.

Generate a historical comparison report from local NDJSON rows when you want ranked CPU, memory, latency, throughput, cost, and quality tables without opening a spreadsheet:

```bash
python3 automation/scripts/generate_comparison_report.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparison-report.json \
  --markdown-output artifacts/comparison-report.md
```

For durable BigQuery history, query the benchmark summary table directly. Add filters such as `--machine-type`, `--processor-family`, `--architecture`, `--cloud-provider`, `--pricing-model`, or `--limit` to narrow the comparison set:

```bash
python3 automation/scripts/generate_comparison_report.py \
  --project-id "$project_id" \
  --dataset-id silicon_boutique \
  --table-id benchmark_summaries \
  --location US \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparison-report.json \
  --markdown-output artifacts/comparison-report.md
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
2. Treat AWS EKS as scaffolded until credentials, IAM, live apply, and teardown are explicitly promoted.
3. Confirm cloud credentials and Terraform state are configured before applying.
4. Run the same deployment and benchmark flow used in local Kubernetes.
5. Preserve teardown discipline to avoid leaving cloud resources running.

Validate the AWS EKS scaffold without AWS credentials:

```bash
cd infra/terraform/aws-eks
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate
terraform plan -refresh=false -input=false
```

The AWS root exports the same run metadata used by the GCP workflow, including `cloud_provider=aws`, region, zone, machine type, processor metadata, node count, pricing model, `get_credentials_command`, tags, managed resource names, and teardown check commands. Live AWS execution requires AWS credentials and the `aws` CLI to run `aws eks update-kubeconfig`; do not apply or destroy the scaffold without a confirmed teardown window.

## GitHub Actions Benchmark Workflow

The Phase 4 workflow is `.github/workflows/benchmark.yml`. It exposes the GCP benchmark path through manual `workflow_dispatch` so future MCP tooling can trigger the same orchestration boundary through the GitHub Actions API.

`.github/workflows/benchmark-aws.yml` is scaffold-only. It runs Terraform static validation for `infra/terraform/aws-eks` and records the intended AWS metadata, but it does not authenticate to AWS, apply resources, deploy Helm charts, run benchmarks, or load BigQuery rows.

P9.1 through P9.3 add production MCP adapters for dispatching the GCP benchmark workflow, querying live GitHub Actions run state, and reading durable BigQuery benchmark history. Configure the MCP process with:

- `SILICON_BOUTIQUE_GITHUB_TOKEN`, falling back to `GITHUB_TOKEN`
- `SILICON_BOUTIQUE_GITHUB_REPOSITORY`, falling back to `GITHUB_REPOSITORY`, in `owner/repo` format
- `SILICON_BOUTIQUE_GITHUB_REF`, defaulting to `main`
- `SILICON_BOUTIQUE_GITHUB_WORKFLOW_ID`, defaulting to `benchmark.yml`
- `SILICON_BOUTIQUE_BIGQUERY_PROJECT_ID`, falling back to `GOOGLE_CLOUD_PROJECT`
- Optional `SILICON_BOUTIQUE_BIGQUERY_DATASET`, `SILICON_BOUTIQUE_BIGQUERY_TABLE`, and `SILICON_BOUTIQUE_BIGQUERY_LOCATION`

The GitHub token needs Actions write permission to create workflow dispatch events and Actions read permission for fallback workflow-run lookup and status checks. The trigger adapter sends safe production inputs only: `failure_stage=none`, `load_profile_source=manual`, and `acceptance_demo=false`. It returns `RunIdentity.run_id` as `gha-<github-run-id>-1`, matching the workflow's derived `RUN_ID` convention for the first run attempt, plus the external GitHub run ID and URL when available.

For guarded manual validation from the MCP package:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp trigger \
  --request-json request.json
```

Query live status with the returned benchmark run ID:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp status \
  --run-id gha-123456789-1
```

Fixture-backed status remains available by adding `--trace-fixture artifacts/workflow-trace.json`. Live status maps GitHub `queued`, `requested`, `waiting`, and `pending` to `queued`; `in_progress` to `running`; completed successful runs to `completed`; completed non-success conclusions such as `failure`, `cancelled`, `timed_out`, and `skipped` to `failed`; missing or unrecognized states to `unknown`. P9.2 reports workflow state only and does not download artifacts or infer teardown success from `workflow-trace.json`.

Query durable history through BigQuery with the same filters as the fixture-backed command:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp history \
  --machine-type c3-standard-4 \
  --processor-family c3 \
  --architecture x86_64 \
  --limit 10
```

The MCP history adapter is read-only, uses the `bq` CLI with Standard SQL, and returns rows from the configured benchmark summary table. Local NDJSON history remains available by adding `--summary-store artifacts/benchmark-summaries.ndjson`.

Before dispatching the workflow, configure GitHub OIDC for GCP and provide these repository or environment secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

The workflow service account needs permissions for the ephemeral GKE benchmark resources plus BigQuery access to inspect the durable summary table, run duplicate checks, and load rows. Use `roles/bigquery.jobUser` at the project level and table-level data editor access on the benchmark summary table.

Dispatch inputs include:

- `project_id`, `region`, and `zone`
- `machine_type`, `node_count`, `processor_family`, optional `cpu_platform`, `architecture`, and `pricing_model`
- `concurrent_users`, `users_per_second`, and `test_duration`
- `bigquery_dataset`, `bigquery_table`, and `bigquery_location`, which default to `silicon_boutique`, `benchmark_summaries`, and `US`
- `failure_stage`, which defaults to `none`

Provision the durable BigQuery destination before the first benchmark load:

```bash
cd infra/terraform/gcp-bigquery
terraform init
terraform apply -auto-approve \
  -var="project_id=$project_id" \
  -var="static_validation_mode=false"
```

The workflow derives a DNS-safe `run_id` as `gha-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}`. That identifier is passed into Terraform, Helm metadata, metric extraction, summary generation, and the BigQuery duplicate check.

The job runs the standard benchmark sequence:

1. Provision the GKE benchmark environment from `infra/terraform/gcp-gke`.
2. Configure `kubectl` with the Terraform `get_credentials_command` output.
3. Deploy `k8s/charts/silicon-boutique-online-boutique`.
4. Deploy `k8s/charts/silicon-boutique-monitoring`.
5. Restart `deployment/loadgenerator` so the measured run starts after monitoring is ready.
6. Sleep for the configured benchmark window.
7. Update the Grafana dashboard metadata with the exact benchmark start and end timestamps.
8. Port-forward Prometheus and run `automation/scripts/extract_prometheus_metrics.py`.
9. Run `automation/scripts/generate_benchmark_summary.py`.
10. Run `automation/scripts/validate_benchmark_comparability.py --run-id "$RUN_ID" --mode summary`.
11. Run `automation/scripts/load_benchmark_summary_to_bigquery.py`.
12. Uninstall Helm releases and destroy Terraform-managed GCP resources.
13. Capture traceability outputs.
14. Upload the generated benchmark artifacts.

The uploaded artifact is named `benchmark-gha-<github-run-id>-<attempt>` and should contain Prometheus metrics, the canonical summary JSON, the local BigQuery-ready NDJSON row, the comparability report, `bigquery-load-report.json`, and Terraform metadata snapshots for managed resources and teardown checks.

To verify persistence, query by the workflow `run_id`:

```bash
bq query --nouse_legacy_sql \
  "SELECT run_id, machine_type, benchmark_start, summary_status
   FROM \`$project_id.silicon_boutique.benchmark_summaries\`
   WHERE run_id = '$run_id'"
```

Duplicate `run_id` values fail before loading, so rerun attempts should use their GitHub-derived attempt-specific `run_id` or explicitly clean up a test row.

For a guarded load/query proof against a test table, use the validation helper. It loads one row, queries it by `run_id`, and only deletes that exact test row when `--cleanup-row` is set:

```bash
python3 automation/scripts/validate_bigquery_summary_load.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --project-id "$project_id" \
  --dataset-id silicon_boutique \
  --table-id benchmark_summaries \
  --location US \
  --schema automation/templates/benchmark-summary.bigquery-schema.json \
  --run-id "$run_id" \
  --report-output artifacts/bigquery-validation-report.json
```

P4.2 guarantees a teardown attempt after Terraform provisioning starts. Terraform apply and destroy remain in the same job so local Terraform state is available to cleanup. Cleanup steps use `if: always()`, Helm uninstall is best-effort and bounded, Terraform destroy is bounded, and the final workflow step fails the job when destroy fails or is refused.

The artifact also includes teardown evidence:

- `provision-status.env`
- `helm-cleanup.log`
- `teardown-precheck.txt`
- `teardown-destroy.log`
- `teardown-postcheck.txt`
- `teardown-status.env`

P4.3 adds traceability outputs for downstream GitHub workflow use and future MCP integration. The benchmark job exposes non-secret outputs for `run_id`, environment, GCP location, machine metadata, benchmark window, summary artifact paths, BigQuery destination, BigQuery load report path, teardown status, and `failure_stage`.

The same trace data is available in three places after a run:

- the benchmark job outputs
- the GitHub step summary table
- `workflow-trace.json` and `workflow-trace.env` in the uploaded artifact

Use `failure_stage=after_provision`, `failure_stage=after_monitoring_ready`, or `failure_stage=before_extract` only in branch validation to force a controlled failure and verify cleanup still runs. Use `failure_stage=none` for normal benchmark runs.

Normal GitHub workflow cancellation should still allow `if: always()` cleanup to continue. Force-cancel behavior that bypasses those conditions cannot be fully guaranteed by workflow YAML alone, so inspect GCP for run-scoped resources if a run is force-canceled.

## MCP Boundary Validation

The MCP boundary package lives in `mcp-server/`. It exposes the production GitHub Actions and BigQuery adapters through the CLI and a real stdio MCP SDK server, while preserving fixture-backed local validation.

Validate the package entry point, tool contracts, and boundary isolation with:

```bash
PYTHONPATH=mcp-server/src python3 -m unittest discover -s mcp-server/tests
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --manifest
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --tools
```

Exercise status and historical queries against local artifacts or fixtures:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp status \
  --run-id "$run_id" \
  --trace-fixture artifacts/workflow-trace.json

PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp history \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --machine-type "$machine_type" \
  --limit 10
```

After installing the package dependencies, start the stdio MCP server for local agents:

```bash
silicon-boutique-mcp-stdio
```

Use fixture mode when validating the MCP transport without live GitHub or BigQuery access:

```bash
export SILICON_BOUTIQUE_MCP_ADAPTER_MODE=fixture
export SILICON_BOUTIQUE_TRACE_FIXTURE=artifacts/workflow-trace.json
export SILICON_BOUTIQUE_SUMMARY_STORE=artifacts/benchmark-summaries.ndjson
silicon-boutique-mcp-stdio
```

Fixture mode supports status and history calls. Benchmark triggering remains production-adapter only.

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

The BigQuery root manages durable benchmark history and is not part of run-scoped teardown:

```bash
cd infra/terraform/gcp-bigquery
timeout 20s terraform fmt -check -recursive
timeout 60s terraform init -backend=false -input=false
timeout 30s terraform validate
timeout 60s terraform plan -refresh=false -input=false -var='project_id=example-project'
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
