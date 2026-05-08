# Automation

This directory contains scripts and helpers that extract benchmark metrics, generate summaries, and prepare structured outputs for downstream use.

Current subdirectories:

- `scripts/`: executable automation helpers
- `templates/`: report templates, schemas, and structured output definitions

## Local Benchmark Orchestration

`scripts/run_local_benchmark.py` runs the local Kubernetes benchmark flow without GitHub Actions. It provisions the Terraform-owned namespace, deploys the workload and monitoring charts, restarts the load generator for the measured window, extracts Prometheus metrics, generates and validates the summary, writes workflow-shaped trace artifacts, and tears the namespace down.

```bash
python3 automation/scripts/run_local_benchmark.py \
  --run-id local-smoke \
  --test-duration 2m \
  --min-duration-seconds 60
```

Use `--skip-destroy` only for debugging a local run; the default path cleans up the Terraform-owned namespace.

## Prometheus Extraction

`scripts/extract_prometheus_metrics.py` queries the SiliconBoutique Prometheus recording rules for a benchmark window and writes deterministic JSON for the next pipeline stage.

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

`scripts/generate_benchmark_summary.py` consumes the Prometheus metrics JSON, writes one canonical benchmark summary, and persists a compact NDJSON row that is ready for a later BigQuery load step. Direct BigQuery insertion is intentionally deferred to keep P3.2 local-first and dependency-free.

```bash
python3 automation/scripts/generate_benchmark_summary.py \
  --metrics-input artifacts/prometheus-metrics.json \
  --summary-output artifacts/benchmark-summary.json \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --environment "$environment" \
  --machine-type "$machine_type" \
  --processor-family "$processor_family" \
  --architecture "$architecture" \
  --cloud-provider local \
  --strict
```

The local summary store fails on duplicate `run_id` values by default. Use `--replace` only when intentionally regenerating a summary for the same benchmark run.

## Summary and Comparability Validation

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
