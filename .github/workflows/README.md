# Workflows

This directory holds the GitHub Actions pipelines for benchmark orchestration.

## AWS scaffold workflow

`benchmark-aws.yml` validates the P8.3 AWS EKS scaffold through `workflow_dispatch`. It runs `terraform fmt`, `terraform init -backend=false`, `terraform validate`, and `terraform plan -refresh=false` for `infra/terraform/aws-eks` using static provider validation. It intentionally does not configure AWS credentials, apply resources, deploy Helm charts, run benchmarks, or persist BigQuery rows.

## Benchmark workflow

`benchmark.yml` runs the GCP benchmark path through `workflow_dispatch`. It sequences the Phase 4 automation flow:

1. Authenticate to GCP with GitHub OIDC.
2. Provision the ephemeral GKE benchmark environment with Terraform.
3. Deploy the Online Boutique workload and monitoring stack with Helm.
4. Restart the load generator to start the measured benchmark window after monitoring is ready.
5. Observe the configured benchmark window.
6. Extract Prometheus metrics.
7. Generate and validate the benchmark summary.
8. Persist the validated benchmark summary to BigQuery.
9. Uninstall Helm releases and destroy the Terraform-managed GCP environment.
10. Capture traceability outputs.
11. Upload benchmark artifacts.

The workflow expects these repository or environment secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

The service account must be able to create and tear down the ephemeral GKE resources and must have BigQuery permissions to inspect the summary table, query duplicate `run_id` values, and load rows. A project-level role set such as `roles/bigquery.jobUser` plus table-level data editor access on the summary table is sufficient for the P7.2 load step.

Manual dispatch inputs include the GCP project, region, zone, machine type, node count, processor metadata, optional CPU platform, load-generator settings, `load_profile_source`, pricing model, BigQuery destination, and `failure_stage`. Use `load_profile_source=calibration` when applying a profile selected by `automation/scripts/calibrate_load_profile.py`. The workflow derives a DNS-safe `run_id` from the GitHub Actions run ID and attempt so Terraform resources, Kubernetes labels, artifacts, and BigQuery rows remain traceable.

The durable BigQuery destination is configured with `bigquery_dataset`, `bigquery_table`, and `bigquery_location`. Defaults are `silicon_boutique`, `benchmark_summaries`, and `US`; provision that destination first with `infra/terraform/gcp-bigquery`.

Use `failure_stage=none` for normal benchmark runs. Use `after_provision`, `after_monitoring_ready`, or `before_extract` only in branch validation to force a controlled failure and prove teardown still runs.

Teardown behavior is intentionally safety-biased:

- Terraform apply and destroy stay in the same job so local Terraform state remains available.
- Cleanup steps use `if: always()` so they still run after benchmark, extraction, summary, or validation failures.
- Helm uninstall is best-effort and bounded with `timeout`.
- Terraform destroy is bounded with `timeout`, records its exit code, and the final workflow step fails the job if destroy failed.

Normal GitHub workflow cancellation should still allow `if: always()` cleanup to continue. Force-cancel behavior that bypasses those conditions cannot be fully guaranteed by workflow YAML alone.

The job exposes non-secret traceability outputs for downstream workflow use:

- `run_id`, `namespace`, `environment`, and `cloud_provider`
- `project_id`, `region`, and `zone`
- `machine_type`, `processor_family`, optional `cpu_platform`, `architecture`, `node_count`, and `pricing_model`
- `benchmark_start` and `benchmark_end`
- `summary_artifact_name`, `summary_path`, and `summary_store_path`
- `bigquery_dataset`, `bigquery_table`, `bigquery_location`, `bigquery_summary_table`, and `bigquery_load_report_path`
- `destroy_attempted`, `teardown_succeeded`, and `failure_stage`

The workflow also writes the same traceability data to the GitHub step summary and to `workflow-trace.json` and `workflow-trace.env` in the uploaded artifact.

Artifacts are uploaded as `benchmark-gha-<github-run-id>-<attempt>` and include:

- `prometheus-metrics.json`
- `benchmark-summary.json`
- `benchmark-summaries.ndjson`
- `loadgenerator.log`
- `loadgenerator-stats.json`
- `comparability-report.json`
- `bigquery-load-report.json`
- Terraform metadata snapshots for managed resource names, labels, and teardown checks
- `provision-status.env`
- `helm-cleanup.log`
- `teardown-precheck.txt`
- `teardown-destroy.log`
- `teardown-postcheck.txt`
- `teardown-status.env`
- `workflow-trace.json`
- `workflow-trace.env`
