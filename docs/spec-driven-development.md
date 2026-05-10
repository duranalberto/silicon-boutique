# Spec Driven Development

## Project

SiliconBoutique is an automated, ephemeral benchmarking workspace for comparing cloud processor performance and price-to-performance with the Google Online Boutique workload.

Primary execution paths:

- Local Kubernetes in the devcontainer for development, smoke tests, dashboard inspection, and acceptance checks.
- GCP GKE for guarded live benchmark runs and durable BigQuery persistence.
- AWS EKS for guarded live benchmark runs that reuse the same workload, summary, dashboard, and comparison contracts.

## Architecture Specification

The system is organized into five decoupled components with structured artifacts at every boundary.

1. **Infrastructure Foundation:** Terraform provisions run-scoped local namespaces, GCP GKE resources, AWS EKS resources, and durable BigQuery history.
2. **Workload Deployment:** Helm deploys the pinned Online Boutique workload and injects SiliconBoutique run metadata and load-generator settings.
3. **Observability and History:** Prometheus records benchmark metrics, Grafana presents the run dashboard, and BigQuery stores canonical benchmark summaries.
4. **Automation Workflow:** Local scripts and GitHub Actions sequence provisioning, deployment, benchmark execution, extraction, summary generation, acceptance checks, and teardown.
5. **MCP Boundary:** The MCP package exposes benchmark trigger, status, and historical query tools without importing Terraform, Helm, or workflow internals.

## Component Requirements

### Infrastructure

- Terraform roots must be small, explicit, and teardown-aware.
- Each benchmark run is keyed by a DNS-safe `run_id`.
- Local resources use the `silicon-boutique-${run_id}` prefix; GCP and AWS resources use the shorter `sb-${run_id}` prefix where provider limits require it.
- Label-capable or tag-capable resources carry provider, region, zone, machine type, processor family, architecture, node count, pricing model, and Terraform ownership metadata.
- BigQuery history is durable infrastructure and is not destroyed as part of benchmark teardown.

### Workload and Load Generation

- The workload chart wraps Online Boutique `0.10.5`.
- The load generator accepts configurable concurrent users, users per second, and benchmark duration without editing upstream manifests.
- Load profiles can be selected manually or generated through calibration.
- The same workload and monitoring charts are used by local, GCP, and AWS paths.

### Metrics, Dashboard, and Summary

- Prometheus extracts CPU usage, CPU utilization percentage, memory working set, CPU throttling, frontend probe latency, pod readiness, restarts, and benchmark metadata.
- Grafana is private by default and must prove the expected dashboard through the API during acceptance.
- `BenchmarkSummary` rows include normalized provider and processor metadata, request volume, duration and coverage quality, latency, CPU, memory, cost fields, and summary status.
- BigQuery is the canonical durable history destination for live cloud runs and optional local integration checks.
- Comparison reports rank comparable runs and list rejected rows instead of silently dropping incomplete or incompatible summaries.

### Automation and Acceptance

- Local automation runs the same benchmark shape as the cloud workflows without dispatching GitHub Actions.
- GCP and AWS workflows are manual `workflow_dispatch` paths and must run only with confirmed credentials, quota, state, and teardown windows.
- Teardown attempts are mandatory after provisioning starts. Workflow cleanup steps are bounded and record teardown evidence.
- Acceptance evidence must tie one `run_id` to workload deployment, Prometheus metrics, load-generator stats, summary validation, Grafana API proof, optional or required BigQuery load evidence, comparison output, and teardown status.

### MCP Boundary

- `trigger_benchmark_run` dispatches the GCP benchmark workflow and returns a GitHub-derived benchmark run identity.
- `get_benchmark_status` maps GitHub Actions workflow state to the boundary status enum.
- `query_historical_metrics` reads durable BigQuery history through a read-only adapter.
- Fixture-backed status and history modes remain available for local validation.
- AWS workflow triggering is not exposed through the MCP trigger adapter unless a later change adds that interface explicitly.

## Roadmap

[`docs/roadmap.md`](roadmap.md) remains the implementation history and dependency record. Current operating instructions live in [`docs/local-usage.md`](local-usage.md) and [`docs/runbook.md`](runbook.md).
