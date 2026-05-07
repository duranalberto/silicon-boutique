# AGENTS.md

This repository is meant to be easy for both humans and agents to extend safely.

## Goals

- Keep the repository aligned with [`docs/spec-driven-development.md`](docs/spec-driven-development.md).
- Prefer small, explicit changes over broad speculative refactors.
- Treat teardown-sensitive infrastructure work as high risk.

## Working Rules

- Read [`docs/project-layout.md`](docs/project-layout.md) before creating new files or folders.
- Use the devcontainer for local development whenever possible.
- Do not overwrite unrelated user changes.
- Avoid destructive infrastructure actions unless the task explicitly requires them.

## Expected Tooling

- Terraform for infrastructure.
- Helm and kubectl for Kubernetes workflows, including local Kubernetes validation.
- Python for metric extraction and report generation.
- Google Cloud CLI for GCP authentication and cluster access during cloud workflows only.

## Useful Commands

- `terraform fmt`
- `terraform validate`
- `helm lint`
- `kubectl get pods`
- `python -m pytest`

## Safety Notes

- Never assume a benchmark run can be destroyed without checking state and dependencies first.
- Protect GCP credentials, Terraform state, kubeconfigs, and BigQuery access tokens as secrets.
- Prefer additive changes in `automation/`, `infra/`, and `k8s/` unless a cleanup is explicitly requested.

## Documentation Expectations

- Update the matching docs when changing architecture or workflow assumptions.
- If a new workflow is introduced, document it in `docs/runbook.md` or `docs/roadmap.md` before leaving the task.
