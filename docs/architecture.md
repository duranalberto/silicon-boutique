# Architecture

## Overview

SiliconBoutique is organized around a benchmark pipeline with a clear separation between infrastructure, workload deployment, metrics collection, automation, and MCP boundary contracts. The first validated path is local development inside the devcontainer and a local Kubernetes validation path, with guarded GCP and AWS workflows available for live cloud processor comparisons.

## Main Parts

- `infra/`: provisions ephemeral infrastructure for local Kubernetes validation, GCP GKE, AWS EKS, plus durable BigQuery summary storage.
- `k8s/`: packages the workload and monitoring stack for deployment.
- `automation/`: runs local benchmarks, extracts metrics, generates summaries, validates acceptance evidence, and builds comparison reports.
- `.github/workflows/`: orchestrates guarded GCP and AWS benchmark runs with BigQuery persistence and teardown evidence.
- `mcp-server/`: dependency-light Python boundary package with production adapters for GCP workflow trigger, GitHub Actions status, BigQuery history, and a stdio MCP server.

## Data Flow

1. The devcontainer boots a local Kubernetes environment for development validation.
2. Terraform and Helm are exercised against the same workflow shape for local Kubernetes, GCP GKE, and AWS EKS.
3. The load generator runs a benchmark window.
4. Automation gathers Prometheus and load-generator metrics, then writes the canonical benchmark summary.
5. Acceptance checks verify summary quality, Grafana dashboard API evidence, optional or required BigQuery load evidence, comparison readiness, and teardown status.
6. Results are stored in local artifacts and, for live GCP/AWS benchmark workflow runs, loaded into durable BigQuery history.
7. The MCP boundary exposes GCP benchmark triggering, live GitHub Actions status, and BigQuery-backed historical queries through abstract ports.

## Design Notes

- Keep benchmark runs ephemeral and repeatable.
- Treat cloud workflows as teardown-sensitive: confirm credentials, IAM, quotas, Terraform state, and cleanup windows before live apply.
- Prefer structured data at every boundary.
- Keep the MCP service boundary separate from Terraform roots, Helm charts, workflow YAML, and direct artifact mutation. GitHub Actions and BigQuery access remain behind adapters.
- Document any change to the run model before implementing it.
