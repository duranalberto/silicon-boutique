# Local Usage Guide

This guide is the first local path for SiliconBoutique. It walks through starting the development environment, running a local benchmark, inspecting the generated artifacts, and cleaning up safely.

For deeper operating details, use [`docs/runbook.md`](runbook.md). For the repository structure, use [`docs/project-layout.md`](project-layout.md).

## What Runs Locally

SiliconBoutique runs the Google Online Boutique workload in a local Kubernetes cluster, collects benchmark metrics with Prometheus, creates a benchmark summary, and stores run artifacts under `artifacts/`.

The local path uses the same workflow shape as the cloud benchmark:

1. Provision an isolated benchmark namespace with Terraform.
2. Deploy the workload and monitoring charts with Helm.
3. Run the configured benchmark window.
4. Extract Prometheus and load-generator metrics.
5. Generate and validate benchmark summaries.
6. Tear down the Terraform-owned namespace.

The local workflow is meant for development, smoke testing, dashboard inspection, and validating changes before using the guarded GCP or AWS benchmark workflows described in [`docs/runbook.md`](runbook.md#github-actions-benchmark-workflow).

## Prerequisites

Use the devcontainer whenever possible. It provides the expected local toolchain and starts or validates the managed minikube profile.

Required tools inside the devcontainer:

| Tool | Expected version |
| --- | --- |
| Terraform | 1.15.2 |
| kubectl | 1.36.0 |
| Helm | 4.1.4 |
| minikube | 1.38.1 |
| Python | `python3` available |
| Docker | reachable from the devcontainer |

The managed local Kubernetes profile is `siliconboutique`. Terraform manages benchmark namespaces inside that cluster; it does not manage the minikube profile itself.

## Initialize The Project

Open the repository in the devcontainer. The devcontainer post-create step checks the toolchain, verifies Docker access, and starts or validates the `siliconboutique` minikube profile when Docker is reachable.

After the container is ready, verify the toolchain:

```bash
.devcontainer/verify-toolchain.sh
```

Confirm the Kubernetes context is available:

```bash
kubectl config get-contexts
kubectl get nodes --context siliconboutique
```

If the context exists but `kubectl get nodes` reports `no route to host` or a
connection timeout, the minikube profile is usually stopped while kubeconfig
still points at its previous API address. Restart the managed profile before
running Terraform-backed commands:

```bash
.devcontainer/post-create.sh
```

If Docker is unavailable or minikube cannot start, fix the devcontainer Docker socket access before running benchmark commands.

## Run A Quick Local Benchmark

Use a short smoke benchmark when you want a fast local check. The lowered duration threshold matches the shorter measured window:

```bash
python3 automation/scripts/run_local_benchmark.py \
  --run-id local-smoke \
  --test-duration 2m \
  --min-duration-seconds 60
```

This command provisions the namespace, deploys workload and monitoring charts, runs the load generator, extracts metrics, writes artifacts, validates the current run's summary row, and tears down the namespace by default.

On a cold minikube profile, the first smoke run can spend several extra minutes warming images and waiting for Prometheus recording rules to emit the required metric series before the configured benchmark window starts.

For a normal local benchmark, omit the smoke-test overrides:

```bash
python3 automation/scripts/run_local_benchmark.py
```

## Run The Acceptance Demo

Use the acceptance demo when you want one command that proves the end-to-end local use case:

```bash
python3 automation/scripts/run_acceptance_demo.py --mode local
```

For a shorter demo in a development loop:

```bash
python3 automation/scripts/run_acceptance_demo.py \
  --mode local \
  --run-id local-demo \
  --test-duration 2m \
  --min-duration-seconds 60
```

The acceptance demo verifies the benchmark summary and live Grafana dashboard API evidence for one `run_id`, writes `artifacts/acceptance-demo-report.json`, and then cleans up.

## Inspect Results

Local runs write artifacts under `artifacts/` unless another directory is passed with `--artifacts-dir`.

Key files:

- `artifacts/benchmark-summary.json`: canonical summary for one benchmark run.
- `artifacts/benchmark-summaries.ndjson`: local appendable summary history shaped for BigQuery loading.
- `artifacts/comparability-report.json`: validation report for the current `run_id`, including schema, metric quality, duration, and coverage.
- `artifacts/comparison-report.json`: machine-readable historical comparison report across comparable runs.
- `artifacts/comparison-report.md`: human-readable comparison table for CPU, memory, latency, throughput, cost, and quality.
- `artifacts/workflow-trace.json`: run metadata and traceability data matching the GitHub workflow shape.
- `artifacts/prometheus-metrics.json`: extracted Prometheus metrics for the benchmark window.
- `artifacts/prometheus-metrics-readiness.json`: pre-run metric readiness evidence used to avoid starting a benchmark before required Prometheus series exist.
- `artifacts/acceptance-demo-report.json`: acceptance evidence from `run_acceptance_demo.py`.

Use `benchmark-summary.json` for the fastest view of a single run. The local benchmark validates only the current `run_id` in `benchmark-summaries.ndjson`; use the full NDJSON history when validating historical comparisons, generating comparison reports, or loading BigQuery rows.

For full local comparison validation without cloud credentials, prefer the split-evidence helper:

```bash
python3 automation/scripts/validate_local_comparison.py
```

The helper does not use GCP, AWS, BigQuery, or GitHub Actions. It runs the local
unit and Terraform static checks, then writes deterministic comparison evidence
under `artifacts/local-comparison-validation/`. The valid-only
`comparability-report.json` should be `pass`; the mixed `comparison-report.json`
and `.md` should be `warn` when they include comparable ranked groups plus an
intentional rejected partial row. The default `artifacts/benchmark-summaries.ndjson`
may still contain legacy or smoke rows and is not guaranteed to pass historical
comparability by itself.

```bash
python3 automation/scripts/generate_comparison_report.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparison-report.json \
  --markdown-output artifacts/comparison-report.md
```

## Inspect Grafana

For a bounded local dashboard inspection, use the acceptance demo hold option. Cleanup resumes automatically after the hold expires:

```bash
python3 automation/scripts/run_acceptance_demo.py \
  --mode local \
  --dashboard-hold-seconds 120
```

The report records the local Grafana URL, dashboard UID, dashboard title, and benchmark run ID.

Use `--skip-destroy` with `run_local_benchmark.py` only for deliberate debugging:

```bash
python3 automation/scripts/run_local_benchmark.py \
  --run-id local-debug \
  --test-duration 2m \
  --min-duration-seconds 60 \
  --skip-destroy
```

When `--skip-destroy` is used, manually clean up the Helm releases and Terraform-owned namespace after inspection. Do not delete the `siliconboutique` minikube profile as benchmark cleanup.

## What You Can Do Locally

- Run smoke checks with `automation/scripts/run_local_benchmark.py`.
- Run the full acceptance path with `automation/scripts/run_acceptance_demo.py`.
- Inspect Prometheus-derived benchmark summaries and comparability reports.
- Inspect the Grafana dashboard during a bounded hold.
- Calibrate a reusable load profile:

```bash
python3 automation/scripts/calibrate_load_profile.py \
  --execute-local \
  --output artifacts/load-profile-calibration.json \
  --initial-concurrent-users 10 \
  --initial-users-per-second 1 \
  --trial-duration 5m
```

Then reuse the selected settings:

```bash
python3 automation/scripts/run_local_benchmark.py \
  --load-profile-file artifacts/load-profile-calibration.json
```

- Validate MCP fixture-backed status and history contracts:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --tools
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp status \
  --run-id local-smoke \
  --trace-fixture artifacts/workflow-trace.json
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp history \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --limit 10
```

- Generate local comparison reports from accumulated summaries:

```bash
python3 automation/scripts/generate_comparison_report.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparison-report.json \
  --markdown-output artifacts/comparison-report.md
```

- Optionally prepare BigQuery-backed persistence for cloud or integration testing by following the guarded BigQuery steps in [`docs/runbook.md`](runbook.md#github-actions-benchmark-workflow).
- Move to guarded GCP or AWS benchmark workflows only after local acceptance passes and cloud credentials, quota, Terraform state, and teardown windows are confirmed in the runbook.

## Cleanup And Safety

The default local automation path tears down the Terraform-owned namespace after each run. This is the safest mode for normal development.

Keep these boundaries clear:

- Terraform owns the benchmark namespace, not the local minikube profile.
- The minikube profile is named `siliconboutique` and is managed by the devcontainer setup.
- Use `--skip-destroy` only when you intend to inspect live resources.
- After any `--skip-destroy` run, uninstall the Helm releases and destroy the Terraform namespace before starting another benchmark.
- Never delete unrelated namespaces, kubeconfigs, Terraform state, credentials, or the minikube profile as part of benchmark teardown.

Manual cleanup after a debugging run:

```bash
cd infra/terraform/local-kubernetes
namespace="$(terraform output -raw namespace)"
cd ../../..

helm uninstall sb-monitoring \
  --namespace "$namespace" \
  --kube-context siliconboutique

helm uninstall silicon-boutique-online-boutique \
  --namespace "$namespace" \
  --kube-context siliconboutique

cd infra/terraform/local-kubernetes
terraform destroy -auto-approve
```

## Troubleshooting

- Docker is unavailable: rerun `.devcontainer/verify-toolchain.sh` and confirm the devcontainer can reach the host Docker daemon.
- minikube is stopped or stale: rerun `.devcontainer/post-create.sh`, then verify `kubectl get nodes --context siliconboutique`.
- minikube does not start: check Docker first, then rerun the devcontainer post-create setup or rebuild the devcontainer.
- `kubectl` cannot find resources: confirm the command uses `--context siliconboutique` and the namespace from Terraform output.
- `terraform apply failed`: inspect `artifacts/terraform-apply.log`; local automation also checks the Kubernetes context before applying.
- Port `3000` or `9090` is already in use: stop the existing port-forward or pass another Grafana or Prometheus port when the script supports it.
- A short run fails duration validation: set `--min-duration-seconds` lower than the measured smoke window.
- A duplicate `run_id` fails summary storage: use a new `--run-id` or intentionally regenerate with the documented script-specific replacement option.
- Cleanup fails: inspect Terraform state and the namespace before retrying; do not manually remove unrelated cluster resources.
