# Architecture

## Overview

SiliconBoutique is organized around a benchmark pipeline with a clear separation between infrastructure, workload deployment, metrics collection, automation, and MCP boundary contracts. The first validated path is local development inside the devcontainer and a local Kubernetes validation path, with GCP remaining the first cloud rollout path.

## Main Parts

- `infra/`: provisions ephemeral infrastructure for local Kubernetes validation and the GCP rollout path, keeps the AWS EKS scaffold, plus durable BigQuery summary storage.
- `k8s/`: packages the workload and monitoring stack for deployment.
- `automation/`: extracts metrics and prepares benchmark summaries.
- `.github/workflows/`: orchestrates provisioning, deployment, benchmark execution, extraction, and teardown.
- `mcp-server/`: dependency-light Python boundary package with fixture-testable status and historical query contracts; production adapters remain roadmap work.

## Data Flow

1. The devcontainer boots a local Kubernetes environment for development validation.
2. Terraform and Helm are exercised against the same workflow shape for local Kubernetes and GCP; AWS EKS currently validates the next-provider scaffold shape.
3. The load generator runs a benchmark window.
4. Automation gathers metrics and summarizes the run.
5. Results are stored in local artifacts and, for GCP benchmark workflow runs, loaded into durable BigQuery history.
6. The MCP boundary exposes status and historical query contracts through abstract ports, keeping GitHub Actions dispatch and summary storage adapters outside the service core.

## Design Notes

- Keep benchmark runs ephemeral and repeatable.
- Treat non-GCP cloud paths as scaffolded until their credentials, IAM, live apply, and teardown flows are explicitly promoted.
- Prefer structured data at every boundary.
- Keep the MCP service boundary separate from pipeline internals such as Terraform roots, Helm charts, automation scripts, workflow YAML, GitHub API clients, and BigQuery clients.
- Document any change to the run model before implementing it.
