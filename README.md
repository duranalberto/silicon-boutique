# SiliconBoutique

SiliconBoutique is a local-first benchmarking workspace for running the Google Online Boutique workload in a devcontainer and local Kubernetes validation path, then carrying the same benchmark workflow to guarded GCP and AWS cloud paths for ephemeral infrastructure and cost/performance comparisons. BigQuery is the canonical durable store for multi-cloud benchmark summaries.

## Start Here

- [`docs/spec-driven-development.md`](docs/spec-driven-development.md): the project specification and long-term design intent.
- [`docs/runbook.md`](docs/runbook.md): the single operator guide for setup, local runs, cloud dispatch, BigQuery, dashboards, acceptance evidence, and teardown.
- [`docs/project-layout.md`](docs/project-layout.md): the current repository layout and intended folder structure.
- [`docs/architecture.md`](docs/architecture.md): the component breakdown and data flow.
- [`docs/roadmap.md`](docs/roadmap.md): the implementation sequence and dependency order.
- [`AGENTS.md`](AGENTS.md): operating notes for AI agents and collaborators.
- [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json): local development environment.

## Repository Layout

- `.devcontainer/`: devcontainer definition for local setup.
- `.github/workflows/`: CI orchestration and benchmark automation.
- `infra/`: infrastructure definitions shared across local and cloud workflows.
- `k8s/`: Kubernetes manifests and Helm chart assets.
- `automation/`: metric extraction and reporting helpers.
- `mcp-server/`: dependency-light MCP boundary package with fixture-testable status and history contracts.
- `docs/`: living documentation for architecture, runbooks, and planning.

## Working Locally

Open the repository in a devcontainer to get Terraform, kubectl, Helm, Python, Docker, and a local minikube-backed Kubernetes validation path. The devcontainer bootstrap checks the toolchain and brings up the `siliconboutique` profile automatically when Docker is reachable.

Use [`docs/runbook.md`](docs/runbook.md) for the documented command flow. Run local validation first, then use the guarded GCP or AWS workflow-dispatch paths for live cloud benchmarks.

## Run A Benchmark

The canonical benchmark operator guide is [`docs/runbook.md`](docs/runbook.md). Start there for setup, command selection, local and GCP execution, diagrams, BigQuery persistence, dashboard viewing, expected artifacts, teardown guidance, and troubleshooting.

Common entrypoints:

- Local smoke: `python3 automation/scripts/run_benchmark_workflow.py --target local --profile smoke --bigquery-env-file credential.env`
- GCP remote benchmark: `python3 automation/scripts/run_benchmark_workflow.py --target gcp --project-id "$project_id" --bigquery-env-file credential.env`
- Results dashboard: `python3 automation/scripts/launch_metrics_dashboard.py --no-browser`

MCP entrypoints remain available for integration validation: `PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --tools` and `silicon-boutique-mcp-stdio` after installing package dependencies.

Implemented pieces include local, GCP, and AWS Terraform roots, Helm workload and monitoring charts, metric extraction and summary automation, GitHub Actions benchmark orchestration, strict Grafana dashboard API acceptance, BigQuery-backed history, comparison reports, a multi-cloud acceptance matrix, a unified workflow coordinator, and production MCP adapters for GCP trigger, GitHub Actions status, and BigQuery history.
