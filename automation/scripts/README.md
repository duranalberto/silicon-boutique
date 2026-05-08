# Automation Scripts

This directory contains Python or shell helpers that extract metrics and prepare benchmark summaries.

- `extract_prometheus_metrics.py`: queries Prometheus `query_range` data for one benchmark run and emits structured JSON with metric aggregates and quality fields.
- `generate_benchmark_summary.py`: converts extracted metrics into one query-friendly benchmark summary and persists a local BigQuery-ready NDJSON row.
- `validate_benchmark_comparability.py`: validates per-run summary quality and, in comparability mode, verifies enough compatible rows exist before benchmark rows are compared.
- `run_local_benchmark.py`: orchestrates the local provision, deploy, benchmark, extract, summarize, validate, and cleanup flow without GitHub Actions.
