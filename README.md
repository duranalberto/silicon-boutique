# SiliconBoutique

SiliconBoutique is a local-first benchmarking workspace for running the Google Online Boutique workload in a devcontainer and local Kubernetes cluster, then carrying the same workflow to GCP as the first cloud target for ephemeral infrastructure and cost/performance comparisons.

## Start Here

- [`docs/spec-driven-development.md`](docs/spec-driven-development.md): the project specification and long-term design intent.
- [`docs/project-layout.md`](docs/project-layout.md): the current repository layout and intended folder structure.
- [`AGENTS.md`](AGENTS.md): operating notes for AI agents and collaborators.
- [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json): local development environment.

## Repository Layout

- `.devcontainer/`: devcontainer definition for local setup.
- `.github/workflows/`: CI orchestration and benchmark automation.
- `infra/terraform/`: infrastructure definitions shared across local and cloud workflows.
- `k8s/`: Kubernetes manifests and Helm chart assets.
- `automation/`: metric extraction and reporting helpers.
- `mcp-server/`: future Model Context Protocol service.
- `docs/`: living documentation for architecture, runbooks, and planning.

## Working Locally

Open the repository in a devcontainer to get Terraform, kubectl, Helm, Python, Docker, and a local minikube-backed Kubernetes cluster.

Use the local Kubernetes path for development and test validation first; GCP remains the first cloud rollout target.

The implementation itself is still scaffolded, so the documentation in `docs/` is the main source of truth for the intended system behavior and rollout plan.
