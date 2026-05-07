# Architecture

## Overview

SiliconBoutique is organized around a benchmark pipeline with a clear separation between infrastructure, workload execution, observability, and future agent access. The first validated path is local development inside the devcontainer and a local Kubernetes cluster, with GCP remaining the first cloud target for later rollout.

## Main Parts

- `infra/terraform/`: provisions ephemeral infrastructure for local Kubernetes validation and the GCP rollout path.
- `k8s/charts/`: packages the workload and monitoring stack for deployment.
- `automation/`: extracts metrics and prepares benchmark summaries.
- `.github/workflows/`: orchestrates setup, run, extraction, and teardown.
- `mcp-server/`: reserved for a future MCP interface over benchmark data and run control.

## Data Flow

1. The devcontainer boots a local Kubernetes environment for development validation.
2. Terraform and Helm are exercised against the same workflow shape that will later target both local Kubernetes and GCP.
3. The load generator runs a benchmark window.
4. Automation gathers metrics and summarizes the run.
5. Results are stored for later comparison and future agent queries.

## Design Notes

- Keep benchmark runs ephemeral and repeatable.
- Prefer structured data at every boundary.
- Document any change to the run model before implementing it.
