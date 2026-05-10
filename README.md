# SiliconBoutique

SiliconBoutique is a local-first benchmarking workspace for running the Google Online Boutique workload in a devcontainer and local Kubernetes validation path, then carrying the same benchmark workflow to guarded GCP and AWS cloud paths for ephemeral infrastructure and cost/performance comparisons. BigQuery is the canonical durable store for multi-cloud benchmark summaries.

## Start Here

- [`docs/spec-driven-development.md`](docs/spec-driven-development.md): the project specification and long-term design intent.
- [`docs/local-usage.md`](docs/local-usage.md): the recommended first-time local setup and usage guide.
- [`docs/project-layout.md`](docs/project-layout.md): the current repository layout and intended folder structure.
- [`docs/architecture.md`](docs/architecture.md): the component breakdown and data flow.
- [`docs/roadmap.md`](docs/roadmap.md): the implementation sequence and dependency order.
- [`docs/runbook.md`](docs/runbook.md): the local and cloud operating flow.
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

Use the local Kubernetes validation path for development and test validation first, then use the guarded GCP or AWS workflows for live cloud benchmarks.

## Supported Workflows

- Local smoke benchmark: `python3 automation/scripts/run_local_benchmark.py --test-duration 2m --min-duration-seconds 60`
- Local acceptance demo: `python3 automation/scripts/run_acceptance_demo.py --mode local`
- GCP live benchmark: dispatch `.github/workflows/benchmark.yml` after provisioning the BigQuery destination and confirming teardown expectations.
- AWS live benchmark: dispatch `.github/workflows/benchmark-aws.yml` in a sandbox AWS account with `AWS_ROLE_TO_ASSUME` and BigQuery credentials configured.
- Multi-cloud acceptance matrix: `python3 automation/scripts/run_acceptance_matrix.py --mode verify --gcp-artifacts <dir> --aws-artifacts <dir>`
- MCP entrypoints: `PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --tools` for CLI validation and `silicon-boutique-mcp-stdio` for the stdio MCP server after installing package dependencies.

Implemented pieces include local, GCP, and AWS Terraform roots, Helm workload and monitoring charts, metric extraction and summary automation, GitHub Actions benchmark orchestration, strict Grafana dashboard API acceptance, BigQuery-backed history, comparison reports, a multi-cloud acceptance matrix, and production MCP adapters for GCP trigger, GitHub Actions status, and BigQuery history.
