# Automation

This directory contains scripts and helpers that extract benchmark metrics, generate summaries, and prepare structured outputs for downstream use.

Current subdirectories:

- `scripts/`: executable automation helpers
- `templates/`: report templates, schemas, and structured output definitions

## Local Benchmark Orchestration

`scripts/run_local_benchmark_workflow.py` is the recommended one-command local
workflow. It verifies the local toolchain, starts or repairs the managed
`siliconboutique` minikube profile when needed, preflights BigQuery, runs a
short local benchmark with BigQuery persistence enabled, validates the remote
BigQuery row, and writes run-scoped debug logs.

```bash
python3 automation/scripts/run_local_benchmark_workflow.py
```

Artifacts are written to `artifacts/local-workflow/<run-id>/`, including
`local-workflow-report.json`, `workflow.log`, per-command logs under
`commands/`, and `issue-report.json` when a workflow step fails. Use
`--full-duration` for the normal benchmark duration instead of the default
smoke settings, or `--run-id` to choose a DNS-safe run ID.

`scripts/run_local_benchmark.py` remains the lower-level orchestration
entrypoint for advanced/debug use. It provisions the Terraform-owned namespace,
deploys the workload and monitoring charts, restarts the load generator for the
measured window, extracts Prometheus metrics, generates and validates the
summary, writes workflow-shaped trace artifacts, and tears the namespace down.
Use `--skip-destroy` only for deliberate debugging.

```bash
python3 automation/scripts/run_local_benchmark.py \
  --run-id local-smoke \
  --test-duration 2m \
  --min-duration-seconds 60 \
  --persist-bigquery \
  --bigquery-env-file credential.env
```

Local BigQuery persistence stores the canonical `BenchmarkSummary` row in
BigQuery, not raw Prometheus time-series samples. Copy
`credential.env.example` to the ignored `credential.env`, set `PROJECT_ID` and
`BIGQUERY_*`, and authenticate with Application Default Credentials or an
ignored `GOOGLE_APPLICATION_CREDENTIALS` key path before running either local
workflow.

## Acceptance Demo

`scripts/run_acceptance_demo.py` is the single-command local proof path. It runs the local benchmark flow, verifies the canonical summary and dashboard API evidence for one `run_id`, optionally loads BigQuery when destination inputs are provided, writes `acceptance-demo-report.json`, and then cleans up.

```bash
python3 automation/scripts/run_acceptance_demo.py --mode local
```

Use `--dashboard-hold-seconds` for a bounded local Grafana inspection window before automatic cleanup resumes.

## Acceptance Matrix

`scripts/run_acceptance_matrix.py` ties local, GCP, AWS, dashboard, summary, comparison, storage, and teardown evidence together in one report. Local mode runs the local acceptance demo and records cloud checks as skipped when credentials are not supplied; verify mode consumes downloaded cloud artifact directories without launching infrastructure.

## Prometheus Extraction

`scripts/extract_prometheus_metrics.py` queries the SiliconBoutique Prometheus recording rules for a benchmark window and writes deterministic JSON for the next pipeline stage.

CPU utilization is extracted from `silicon_boutique:workload_cpu_utilization_pct`, which records workload CPU usage divided by allocatable CPU cores on nodes running benchmark pods, with node capacity used only when allocatable metrics are unavailable.

Example against a port-forwarded local Prometheus endpoint:

```bash
python3 automation/scripts/extract_prometheus_metrics.py \
  --prometheus-url http://127.0.0.1:9090 \
  --run-id "$run_id" \
  --namespace "$namespace" \
  --start "$benchmark_start" \
  --end "$benchmark_end" \
  --step 15s \
  --output artifacts/prometheus-metrics.json \
  --strict
```

The extractor can also run against fixture responses for deterministic tests:

```bash
python3 automation/scripts/extract_prometheus_metrics.py \
  --fixture-dir automation/tests/fixtures/prometheus \
  --run-id test-run \
  --namespace sb-test \
  --start 2026-05-07T12:00:00Z \
  --end 2026-05-07T12:01:00Z
```

## Benchmark Summary Persistence

`scripts/generate_benchmark_summary.py` consumes the Prometheus metrics JSON, writes one canonical benchmark summary, and persists a compact NDJSON row that is ready for BigQuery loading.

`scripts/extract_loadgenerator_stats.py` parses Locust aggregate stats from `deployment/loadgenerator` logs and writes request volume fields for the summary:

```bash
kubectl logs deployment/loadgenerator --namespace "$namespace" > artifacts/loadgenerator.log
python3 automation/scripts/extract_loadgenerator_stats.py \
  --logs-input artifacts/loadgenerator.log \
  --output artifacts/loadgenerator-stats.json \
  --run-id "$run_id" \
  --strict
```

```bash
python3 automation/scripts/generate_benchmark_summary.py \
  --metrics-input artifacts/prometheus-metrics.json \
  --loadgenerator-stats artifacts/loadgenerator-stats.json \
  --summary-output artifacts/benchmark-summary.json \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --environment "$environment" \
  --machine-type "$machine_type" \
  --processor-family "$processor_family" \
  --architecture "$architecture" \
  --cloud-provider local \
  --region local \
  --zone local \
  --node-count 1 \
  --pricing-model local \
  --concurrent-users "$concurrent_users" \
  --users-per-second "$users_per_second" \
  --load-profile-source manual \
  --min-coverage-ratio 0.95 \
  --strict
```

For priced GCP runs, also pass `--region`, `--zone`, `--pricing-model`, optional `--cpu-platform`, and `--pricing-table automation/templates/machine-pricing.json`. The summary calculates `benchmark_compute_cost_usd` and `cost_per_1m_requests_usd` from successful request count, node count, duration, and hourly node price. Strict summary validation rejects impossible CPU utilization values and records both average and max utilization.
`summary_status=complete` requires required metrics and derived fields plus coverage at or above the configured minimum; the default `--min-coverage-ratio 0.95` matches the comparability validator.

The local summary store fails on duplicate `run_id` values by default. Use `--replace` only when intentionally regenerating a summary for the same benchmark run.

## Comparison Reports

Generate ranked comparison artifacts from accumulated local summaries:

```bash
python3 automation/scripts/generate_comparison_report.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparison-report.json \
  --markdown-output artifacts/comparison-report.md
```

The JSON report is the canonical machine-readable output. The Markdown report contains a compact table for humans. Both outputs group repeated runs by normalized provider, machine, processor, pricing, and load-profile metadata; rank latency, throughput, memory, CPU efficiency, cost, and run quality; and list rejected non-comparable runs instead of silently dropping them.

## Portable Metrics Dashboard

Generate and serve a local HTML dashboard from the default local summary store:

```bash
python3 automation/scripts/launch_metrics_dashboard.py --no-browser
```

The launcher reads `artifacts/benchmark-summaries.ndjson`, reuses the comparison report grouping, ranking, warning, and rejected-run behavior, writes `artifacts/dashboard/index.html` and `artifacts/dashboard/dashboard-data.json`, and prints a localhost URL. The dashboard data includes source metadata with `type=ndjson`, latest-run metadata, comparison groups, rankings, rejected runs, and duplicate `run_id` hints.

Use BigQuery dashboard source mode for durable cloud history:

```bash
python3 automation/scripts/launch_metrics_dashboard.py \
  --project-id "$project_id" \
  --dataset-id silicon_boutique \
  --table-id benchmark_summaries \
  --location US \
  --no-browser
```

BigQuery mode requires local `bq` CLI access with credentials and permissions for the configured project, dataset, and table. Use `--no-serve` when you only want to regenerate the files without starting the local HTTP server. Use `--limit`, `--machine-type`, `--processor-family`, `--architecture`, `--cloud-provider`, or `--pricing-model` to narrow either local or BigQuery source data before the dashboard is generated.

Dashboard files are ignored generated artifacts, not canonical project documentation. This portable dashboard visualizes stored benchmark summaries after a run; it is distinct from the private Grafana dashboard used for live Kubernetes monitoring during a benchmark.

## Load Calibration

`scripts/calibrate_load_profile.py` finds load settings that target the 80-90% CPU utilization band and writes a reusable profile:

```bash
python3 automation/scripts/calibrate_load_profile.py \
  --execute-local \
  --output artifacts/load-profile-calibration.json \
  --initial-concurrent-users 10 \
  --initial-users-per-second 1 \
  --trial-duration 5m
```

Use the selected profile in a later local benchmark run:

```bash
python3 automation/scripts/run_local_benchmark.py \
  --load-profile-file artifacts/load-profile-calibration.json
```

For GCP calibration, use `--execute-gcp --project-id "$project_id"` to dispatch benchmark workflow trials. Selected profiles include machine metadata, target CPU band, source run IDs, observed utilization, and request failure ratio; pass those load settings to the workflow with `load_profile_source=calibration`.

`scripts/load_benchmark_summary_to_bigquery.py` loads one canonical summary row into the durable BigQuery table provisioned by `infra/terraform/gcp-bigquery`. It validates the local NDJSON, inspects the remote table schema with `bq show`, checks for an existing `run_id`, and writes a load report whether the load succeeds or fails.

```bash
python3 automation/scripts/load_benchmark_summary_to_bigquery.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --project-id "$project_id" \
  --dataset-id silicon_boutique \
  --table-id benchmark_summaries \
  --location US \
  --schema automation/templates/benchmark-summary.bigquery-schema.json \
  --load-report-output artifacts/bigquery-load-report.json \
  --duplicate-policy fail \
  --run-id "$run_id"
```

Duplicate `run_id` values fail before load. If you point the script at a multi-row NDJSON store, pass `--run-id` so exactly one row is selected.

Use `--dry-run` with the same arguments to validate local input, table access, schema compatibility, and duplicate status without appending a row.

`scripts/validate_bigquery_summary_load.py` is a guarded integration helper for test datasets. It loads one selected `run_id`, queries the same table for that row, writes `bigquery-validation-report.json`, and deletes only that exact test row when `--cleanup-row` is explicitly provided.

## Summary and Comparability Validation

For local comparison validation without cloud credentials, use the dedicated helper instead of pointing
the historical gate directly at `artifacts/benchmark-summaries.ndjson`. Local
history can contain pre-comparison-ready, smoke, or demo rows, so the helper writes split
evidence under `artifacts/local-comparison-validation/`: a valid-only store whose
comparability report must pass, and a mixed store whose comparison report should
warn while listing the intentional rejected partial row.

```bash
python3 automation/scripts/validate_local_comparison.py
```

Expected statuses are `pass` for
`artifacts/local-comparison-validation/comparability-report.json`, `warn` for
`artifacts/local-comparison-validation/comparison-report.json` when rejected-row
evidence is present, and `fail` only when no comparable groups are available or
schema drift blocks comparison.

`scripts/validate_benchmark_comparability.py` has two validation modes. Use `--mode summary` for a fresh per-run artifact store that may contain only one summary row. It checks schema stability, stable baseline labels, complete metric quality, duration, and coverage without requiring a second run.

```bash
python3 automation/scripts/validate_benchmark_comparability.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparability-report.json \
  --mode summary \
  --min-duration-seconds 1200 \
  --min-coverage-ratio 0.95 \
  --strict
```

Use `--mode comparability` before cross-machine comparisons. This keeps the per-row quality checks and also requires at least two comparable rows.

```bash
python3 automation/scripts/validate_benchmark_comparability.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparability-report.json \
  --mode comparability \
  --min-duration-seconds 1200 \
  --min-coverage-ratio 0.95 \
  --strict
```

The report lists comparable run IDs, rejected runs with reasons, schema field count, `summary_validation_status`, and `comparability_validation_status`. `comparability_status` remains as an alias for the cross-run status.

## Internal Workflow Helpers

`scripts/write_workflow_trace.py` and `scripts/render_acceptance_summary.py` keep GitHub workflow trace and step-summary rendering in testable Python instead of inline workflow snippets. They are normally called by workflows or acceptance automation rather than run directly by operators.
