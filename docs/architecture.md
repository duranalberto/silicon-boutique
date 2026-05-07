# Architecture

## Overview

SiliconBoutique is organized around a benchmark pipeline with a clear separation between infrastructure, workload deployment, metrics collection, automation, and future MCP access. The first validated path is local development inside the devcontainer and a local Kubernetes validation path, with GCP remaining the first cloud rollout path.

## Main Parts

- `infra/`: provisions ephemeral infrastructure for local Kubernetes validation and the GCP rollout path.
- `k8s/`: packages the workload and monitoring stack for deployment.
- `automation/`: extracts metrics and prepares benchmark summaries.
- `.github/workflows/`: orchestrates provisioning, deployment, benchmark execution, extraction, and teardown.
- `mcp-server/`: dependency-light Python boundary scaffold with fixture-testable status and historical query contracts for future MCP access.

## Data Flow

1. The devcontainer boots a local Kubernetes environment for development validation.
2. Terraform and Helm are exercised against the same workflow shape that will later target both local Kubernetes and GCP.
3. The load generator runs a benchmark window.
4. Automation gathers metrics and summarizes the run.
5. Results are stored for later comparison and future agent queries.
6. The MCP boundary exposes status and historical query contracts through abstract ports, keeping GitHub Actions dispatch and summary storage adapters outside the service core.

## Design Notes

- Keep benchmark runs ephemeral and repeatable.
- Prefer structured data at every boundary.
- Keep the MCP service boundary separate from pipeline internals such as Terraform roots, Helm charts, automation scripts, workflow YAML, GitHub API clients, and BigQuery clients.
- Document any change to the run model before implementing it.
