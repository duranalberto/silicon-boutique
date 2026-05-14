#!/usr/bin/env python3
"""Read-only audit for SiliconBoutique BigQuery benchmark summaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import load_benchmark_summary_to_bigquery as BigQuery

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared import bigquery as bq_helpers
from silicon_boutique_shared.automation import utc_now, write_json


DEFAULT_MIN_DURATION_SECONDS = 1200
DEFAULT_MIN_COVERAGE_RATIO = 0.95
DEFAULT_MIN_REQUEST_RPS_WINDOW_RATIO = 0.5
REQUIRED_FIELDS = (
    "run_id",
    "namespace",
    "environment",
    "cloud_provider",
    "region",
    "zone",
    "machine_type",
    "processor_family",
    "architecture",
    "node_count",
    "pricing_model",
    "benchmark_start",
    "benchmark_end",
    "duration_seconds",
    "generated_at",
    "summary_status",
)


class BigQueryAuditError(RuntimeError):
    """Raised when the audit cannot inspect BigQuery safely."""


CommandResult = bq_helpers.CommandResult
Runner = bq_helpers.Runner


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Audit benchmark summary rows in BigQuery without mutating them."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-duration-seconds", type=int, default=DEFAULT_MIN_DURATION_SECONDS)
    parser.add_argument("--min-coverage-ratio", type=float, default=DEFAULT_MIN_COVERAGE_RATIO)
    parser.add_argument(
        "--min-request-rps-window-ratio",
        type=float,
        default=DEFAULT_MIN_REQUEST_RPS_WINDOW_RATIO,
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if not 0 <= args.min_coverage_ratio <= 1:
        parser.error("--min-coverage-ratio must be between 0 and 1")
    if not 0 <= args.min_request_rps_window_ratio <= 1:
        parser.error("--min-request-rps-window-ratio must be between 0 and 1")
    return args


def main() -> int:
    """Run the command-line entrypoint."""
    args = parse_args()
    try:
        schema = BigQuery.load_bigquery_schema(args.schema)
        BigQuery.validate_destination(
            args.project_id, args.dataset_id, args.table_id, args.location
        )
        BigQuery.validate_table_schema(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            expected_schema=schema,
            runner=run_bq,
        )
        rows = query_rows(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            location=args.location,
            run_id=args.run_id,
            limit=args.limit,
            runner=run_bq,
        )
        report = build_audit_report(
            rows=rows,
            source={
                "type": "bigquery",
                "summary_table": bq_helpers.table_sql_name(
                    args.project_id, args.dataset_id, args.table_id
                ),
                "location": args.location,
            },
            schema_path=args.schema,
            min_duration_seconds=args.min_duration_seconds,
            min_coverage_ratio=args.min_coverage_ratio,
            min_request_rps_window_ratio=args.min_request_rps_window_ratio,
        )
        write_json(args.report_output, report)
    except (BigQueryAuditError, BigQuery.BigQueryLoadError) as exc:
        write_json(
            args.report_output,
            {
                "status": "failed",
                "generated_at": utc_now(),
                "error": str(exc),
            },
        )
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def query_rows(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    location: str,
    run_id: str | None,
    limit: int | None,
    runner: Runner,
) -> list[dict[str, Any]]:
    """Query benchmark summary rows."""
    where = f" WHERE run_id = {bq_helpers.sql_string(run_id)}" if run_id else ""
    query = (
        "SELECT * FROM "
        f"`{bq_helpers.table_sql_name(project_id, dataset_id, table_id)}`"
        f"{where} ORDER BY benchmark_start DESC"
    )
    if limit is not None:
        query += f" LIMIT {limit}"
    result = runner(bq_helpers.query_command(project_id, location, query))
    if result.returncode != 0:
        raise BigQueryAuditError("failed to query BigQuery summaries: " + result.stderr.strip())
    try:
        rows = bq_helpers.parse_bq_json_array(result.stdout)
    except bq_helpers.BigQueryHelperError as exc:
        raise BigQueryAuditError(str(exc)) from exc
    return rows


def build_audit_report(
    *,
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    schema_path: Path,
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
    min_coverage_ratio: float = DEFAULT_MIN_COVERAGE_RATIO,
    min_request_rps_window_ratio: float = DEFAULT_MIN_REQUEST_RPS_WINDOW_RATIO,
) -> dict[str, Any]:
    """Build a read-only audit report for rows."""
    normalized_rows = [normalize_row(row) for row in rows]
    duplicate_ids = duplicate_run_ids(normalized_rows)
    row_reports = []
    for index, row in enumerate(normalized_rows, 1):
        findings = row_findings(
            row,
            row_index=index,
            min_duration_seconds=min_duration_seconds,
            min_coverage_ratio=min_coverage_ratio,
            min_request_rps_window_ratio=min_request_rps_window_ratio,
        )
        if row.get("run_id") in duplicate_ids:
            findings.append("duplicate_run_id")
        row_reports.append(
            {
                "run_id": row.get("run_id") or f"row-{index}",
                "findings": findings,
            }
        )
    suspect_run_ids = [
        report["run_id"] for report in row_reports if suspect_findings(report["findings"])
    ]
    status = "pass"
    if any(report["findings"] for report in row_reports):
        status = "warn"
    if not normalized_rows or duplicate_ids or any(
        critical_findings(report["findings"]) for report in row_reports
    ):
        status = "fail"
    return {
        "status": status,
        "generated_at": utc_now(),
        "source": source,
        "schema": str(schema_path),
        "total_rows": len(normalized_rows),
        "distinct_run_ids": len({row.get("run_id") for row in normalized_rows if row.get("run_id")}),
        "duplicate_run_ids": duplicate_ids,
        "suspect_run_ids": suspect_run_ids,
        "rows": row_reports,
        "thresholds": {
            "min_duration_seconds": min_duration_seconds,
            "min_coverage_ratio": min_coverage_ratio,
            "min_request_rps_window_ratio": min_request_rps_window_ratio,
        },
    }


def row_findings(
    row: dict[str, Any],
    *,
    row_index: int = 1,
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
    min_coverage_ratio: float = DEFAULT_MIN_COVERAGE_RATIO,
    min_request_rps_window_ratio: float = DEFAULT_MIN_REQUEST_RPS_WINDOW_RATIO,
) -> list[str]:
    """Return audit findings for one row."""
    del row_index
    findings: list[str] = []
    for field in REQUIRED_FIELDS:
        if missing_value(row.get(field)):
            findings.append(f"required_field_missing:{field}")
    duration = number_or_none(row.get("duration_seconds"))
    if duration is not None and duration < min_duration_seconds:
        findings.append(f"duration_below_comparability_min:{int(duration)}<{min_duration_seconds}")
    coverage = number_or_none(row.get("metrics_coverage_ratio"))
    if coverage is None or coverage < min_coverage_ratio:
        findings.append("coverage_below_min_or_missing")
    if row.get("summary_status") != "complete":
        findings.append("summary_not_complete")
    if row.get("missing_metrics"):
        findings.append("missing_metrics_present")
    if row.get("empty_metrics"):
        findings.append("empty_metrics_present")
    invalid_samples = row.get("invalid_metric_samples") or {}
    if invalid_samples != {}:
        findings.append("invalid_metric_samples_present")
    request_total = number_or_none(row.get("request_count_total"))
    request_success = number_or_none(row.get("request_success_count"))
    request_failure = number_or_none(row.get("request_failure_count"))
    avg_rps = number_or_none(row.get("avg_requests_per_second"))
    if None in (request_total, request_success, request_failure, avg_rps):
        findings.append("loadgenerator_stats_missing")
    elif int(request_total) != int(request_success) + int(request_failure):
        findings.append("request_total_mismatch")
    ratio = request_rps_window_ratio(row)
    if ratio is not None and ratio < min_request_rps_window_ratio:
        findings.append("request_total_far_below_avg_rps_window")
    if row.get("cloud_provider") != "local" and any(
        row.get(field) is None
        for field in (
            "node_hourly_price_usd",
            "benchmark_compute_cost_usd",
            "cost_per_1m_requests_usd",
        )
    ):
        findings.append("cloud_cost_fields_missing")
    if row.get("cloud_provider") in {"gcp", "aws"} and missing_value(row.get("cpu_platform")):
        findings.append("cloud_cpu_platform_missing")
    return findings


def request_rps_window_ratio(row: dict[str, Any]) -> float | None:
    """Compute request total to RPS-window ratio for a row."""
    request_total = number_or_none(row.get("request_count_total"))
    avg_rps = number_or_none(row.get("avg_requests_per_second"))
    duration = number_or_none(row.get("duration_seconds"))
    if request_total is None or avg_rps is None or duration is None or avg_rps <= 0:
        return None
    return round(request_total / (avg_rps * duration), 6)


def suspect_findings(findings: list[str]) -> list[str]:
    """Return findings that make a row suspect for request-derived reporting."""
    return [
        finding
        for finding in findings
        if finding
        in {
            "request_total_far_below_avg_rps_window",
            "loadgenerator_stats_missing",
            "request_total_mismatch",
        }
    ]


def critical_findings(findings: list[str]) -> list[str]:
    """Return findings that should fail the audit."""
    return [
        finding
        for finding in findings
        if finding.startswith("required_field_missing:") or finding == "duplicate_run_id"
    ]


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize BigQuery JSON scalar strings for audit comparisons."""
    normalized = dict(row)
    for field in (
        "node_count",
        "duration_seconds",
        "request_count_total",
        "request_success_count",
        "request_failure_count",
        "load_concurrent_users",
    ):
        if field in normalized:
            parsed = int_or_none(normalized[field])
            if parsed is not None:
                normalized[field] = parsed
    for field in (
        "avg_requests_per_second",
        "metrics_coverage_ratio",
        "node_hourly_price_usd",
        "benchmark_compute_cost_usd",
        "cost_per_1m_requests_usd",
    ):
        if field in normalized:
            parsed = number_or_none(normalized[field])
            if parsed is not None:
                normalized[field] = parsed
    if isinstance(normalized.get("invalid_metric_samples"), str):
        try:
            parsed = json.loads(normalized["invalid_metric_samples"] or "{}")
        except json.JSONDecodeError:
            parsed = {"__invalid_json__": 1}
        normalized["invalid_metric_samples"] = parsed if isinstance(parsed, dict) else {}
    return normalized


def duplicate_run_ids(rows: list[dict[str, Any]]) -> list[str]:
    """Return sorted duplicate run IDs."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            continue
        if run_id in seen:
            duplicates.add(run_id)
        seen.add(run_id)
    return sorted(duplicates)


def missing_value(value: Any) -> bool:
    """Return whether a scalar value is missing."""
    return value is None or value == ""


def int_or_none(value: Any) -> int | None:
    """Parse an integer value."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def number_or_none(value: Any) -> float | None:
    """Parse a numeric value."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run_bq(command: list[str]) -> CommandResult:
    """Run the BigQuery CLI."""
    try:
        return bq_helpers.run_bq(command)
    except bq_helpers.BigQueryHelperError as exc:
        raise BigQueryAuditError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
