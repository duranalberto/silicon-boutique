# Automation Scripts

This directory contains Python or shell helpers that extract metrics and prepare benchmark summaries.

- `extract_prometheus_metrics.py`: queries Prometheus `query_range` data for one benchmark run and emits structured JSON with metric aggregates and quality fields.
- `generate_benchmark_summary.py`: converts extracted metrics into one query-friendly benchmark summary and persists a local BigQuery-ready NDJSON row.
- `validate_benchmark_comparability.py`: validates per-run summary quality and, in comparability mode, verifies enough compatible rows exist before benchmark rows are compared.
- `launch_metrics_dashboard.py`: generates `artifacts/dashboard/index.html` plus `dashboard-data.json` from local NDJSON summaries or optional BigQuery history, serves them on localhost, and uses the same comparison grouping, ranking, warning, and rejected-run behavior as `generate_comparison_report.py`.
- `run_local_benchmark_workflow.py`: one-command local workflow that verifies/repairs local Kubernetes, runs a smoke benchmark with BigQuery persistence, validates the remote row, and writes debug logs.
- `run_local_benchmark.py`: orchestrates the local provision, deploy, benchmark, extract, summarize, validate, and cleanup flow without GitHub Actions.
- `run_acceptance_demo.py`: runs or verifies the acceptance demo and writes `acceptance-demo-report.json` with summary, strict Grafana API dashboard, optional BigQuery, and teardown evidence.
- `run_acceptance_matrix.py`: runs or verifies the multi-cloud acceptance matrix and writes `acceptance-matrix-report.json` tying local, GCP, AWS, dashboard, summary, comparison, storage, and teardown evidence together.
- `calibrate_load_profile.py`: selects reusable load settings from fixtures, local runs, or GCP workflow trials.
- `load_benchmark_summary_to_bigquery.py`: loads one canonical summary row into durable BigQuery history with immutable duplicate handling.
- `validate_bigquery_summary_load.py`: guarded BigQuery load/query proof for test summary rows.
- `validate_local_comparison.py`: local-only comparison evidence helper that avoids cloud credentials.
- `write_workflow_trace.py`: workflow helper that writes non-secret trace artifacts.
- `render_acceptance_summary.py`: workflow helper that renders acceptance evidence into the GitHub step summary.
