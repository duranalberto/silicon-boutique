# Automation

This directory contains scripts and helpers that extract benchmark metrics, generate summaries, and prepare structured outputs for downstream use.

Current subdirectories:

- `scripts/`: executable automation helpers
- `templates/`: report templates, schemas, and structured output definitions

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

## Comparability Validation

`scripts/validate_benchmark_comparability.py` checks the local summary store for schema drift, stable baseline labels, complete metric quality, and enough comparable runs. This is a local quality gate; direct BigQuery loading and cost comparability remain future work.

```bash
python3 automation/scripts/validate_benchmark_comparability.py \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --schema automation/templates/benchmark-summary.schema.json \
  --report-output artifacts/comparability-report.json \
  --min-duration-seconds 1200 \
  --min-coverage-ratio 0.95 \
  --strict
```

The report lists comparable run IDs, rejected runs with reasons, schema field count, and a `comparability_status` of `pass`, `warn`, or `fail`.
