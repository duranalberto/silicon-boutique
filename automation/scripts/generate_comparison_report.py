#!/usr/bin/env python3
"""Generate comparison reports from historical SiliconBoutique summaries."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import load_benchmark_summary_to_bigquery as BigQuery
import audit_bigquery_benchmark_summaries as summary_audit
import validate_benchmark_comparability as comparability

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared import bigquery as bq_helpers
from silicon_boutique_shared.automation import utc_now, write_json


GROUP_FIELDS = (
    "cloud_provider",
    "region",
    "zone",
    "machine_type",
    "processor_family",
    "cpu_platform",
    "architecture",
    "node_count",
    "pricing_model",
    "load_profile_source",
    "load_concurrent_users",
    "load_users_per_second",
)
FILTER_FIELDS = (
    "machine_type",
    "processor_family",
    "architecture",
    "cloud_provider",
    "pricing_model",
)
MEAN_FIELDS = (
    "avg_cpu_usage_cores",
    "max_cpu_usage_cores",
    "avg_cpu_utilization_pct",
    "max_cpu_utilization_pct",
    "avg_memory_working_set_bytes",
    "max_memory_working_set_bytes",
    "max_memory_used_gb",
    "avg_cpu_throttling_ratio",
    "max_cpu_throttling_ratio",
    "frontend_latency_p50_ms",
    "frontend_latency_p95_ms",
    "frontend_latency_p99_ms",
    "frontend_latency_max_ms",
    "avg_requests_per_second",
    "metrics_coverage_ratio",
    "node_hourly_price_usd",
    "benchmark_compute_cost_usd",
    "cost_per_1m_requests_usd",
)
RANKINGS = {
    "avg_requests_per_second": "desc",
    "requests_per_cpu_core": "desc",
    "metrics_coverage_ratio": "desc",
    "frontend_latency_p99_ms": "asc",
    "max_memory_used_gb": "asc",
    "cost_per_1m_requests_usd": "asc",
    "request_failure_ratio": "asc",
}
DEFAULT_SCHEMA = Path("automation/templates/benchmark-summary.schema.json")


class ComparisonReportError(RuntimeError):
    """Raised when a comparison report cannot be generated."""


CommandResult = bq_helpers.CommandResult
Runner = bq_helpers.Runner


def parse_args() -> argparse.Namespace:
    """Parse arguments.


    Returns:
        argparse.Namespace value produced by parse arguments.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    parser = argparse.ArgumentParser(
        description="Generate machine comparison reports from benchmark summaries."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--summary-store", type=Path)
    source.add_argument("--project-id")
    parser.add_argument("--dataset-id")
    parser.add_argument("--table-id")
    parser.add_argument("--location")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--machine-type")
    parser.add_argument("--processor-family")
    parser.add_argument("--architecture")
    parser.add_argument("--cloud-provider")
    parser.add_argument("--pricing-model", choices=("local", "spot", "on_demand"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-duration-seconds", type=int, default=1200)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    args = parser.parse_args()
    if args.project_id and not (args.dataset_id and args.table_id and args.location):
        parser.error("--dataset-id, --table-id, and --location are required with --project-id")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if not 0 <= args.min_coverage_ratio <= 1:
        parser.error("--min-coverage-ratio must be between 0 and 1")
    return args


def main() -> int:
    """Run the command-line entrypoint.


    Returns:
        Process exit code for the command.
    """
    args = parse_args()
    try:
        rows, source = load_rows(args)
        schema = comparability.load_json(args.schema, "schema")
        filtered_rows = apply_filters(rows, filter_values(args))
        if args.limit is not None and args.summary_store:
            filtered_rows = sort_rows(filtered_rows)[: args.limit]
        report = build_comparison_report(
            rows=filtered_rows,
            source=source,
            schema=schema,
            schema_path=args.schema,
            min_duration_seconds=args.min_duration_seconds,
            min_coverage_ratio=args.min_coverage_ratio,
        )
        write_json(args.report_output, report)
        write_text(args.markdown_output, render_markdown(report))
    except (ComparisonReportError, comparability.ComparabilityError, BigQuery.BigQueryLoadError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def load_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load rows.


    Args:
        args: arguments (argparse.Namespace) used by this operation.

    Returns:
        tuple[list[dict[str, Any]], dict[str, Any]] value produced by load rows.
    """
    if args.summary_store:
        return read_summary_store(args.summary_store), {
            "type": "ndjson",
            "summary_store": str(args.summary_store),
        }
    rows = query_bigquery_rows(
        project_id=args.project_id,
        dataset_id=args.dataset_id,
        table_id=args.table_id,
        location=args.location,
        filters=filter_values(args),
        limit=args.limit,
        runner=run_bq,
    )
    return rows, {
        "type": "bigquery",
        "summary_table": bq_helpers.table_sql_name(
            args.project_id, args.dataset_id, args.table_id
        ),
        "location": args.location,
    }


def read_summary_store(path: Path) -> list[dict[str, Any]]:
    """Read summary store.


    Args:
        path: path (Path) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by read summary store.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    if not path.exists():
        raise ComparisonReportError(f"summary store does not exist: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComparisonReportError(
                f"summary store contains invalid JSON on line {line_number}: {path}"
            ) from exc
        if not isinstance(row, dict):
            raise ComparisonReportError(
                f"summary store line {line_number} is not a JSON object: {path}"
            )
        rows.append(row)
    if not rows:
        raise ComparisonReportError(f"summary store contains no rows: {path}")
    return rows


def query_bigquery_rows(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    location: str,
    filters: dict[str, str],
    limit: int | None,
    runner: Runner,
) -> list[dict[str, Any]]:
    """Query BigQuery rows.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        location: location (str) used by this operation.
        filters: filters (dict[str, str]) used by this operation.
        limit: limit (int | None) used by this operation.
        runner: runner (Runner) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by query BigQuery rows.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    BigQuery.validate_destination(project_id, dataset_id, table_id, location)
    where_parts = [
        f"{field} = {bq_helpers.sql_string(value)}"
        for field, value in filters.items()
        if value is not None
    ]
    query = (
        "SELECT * FROM "
        f"`{bq_helpers.table_sql_name(project_id, dataset_id, table_id)}`"
    )
    if where_parts:
        query += " WHERE " + " AND ".join(where_parts)
    query += " ORDER BY benchmark_start DESC"
    if limit is not None:
        query += f" LIMIT {limit}"
    result = runner(
        bq_helpers.query_command(project_id, location, query)
    )
    if result.returncode != 0:
        raise ComparisonReportError("failed to query BigQuery summaries: " + result.stderr.strip())
    try:
        rows = bq_helpers.parse_bq_json_array(result.stdout)
    except bq_helpers.BigQueryHelperError as exc:
        raise ComparisonReportError(str(exc)) from exc
    return normalize_bigquery_rows(rows)


def normalize_bigquery_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize BigQuery rows.


    Args:
        rows: rows (list[dict[str, Any]]) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by normalize BigQuery rows.
    """
    return [normalize_bigquery_row(row) for row in rows]


def normalize_bigquery_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize BigQuery row.


    Args:
        row: row (dict[str, Any]) used by this operation.

    Returns:
        dict[str, Any] value produced by normalize BigQuery row.
    """
    normalized = dict(row)
    integer_fields = {
        "node_count",
        "duration_seconds",
        "request_count_total",
        "request_success_count",
        "request_failure_count",
        "load_concurrent_users",
    }
    float_fields = {
        "avg_cpu_usage_cores",
        "max_cpu_usage_cores",
        "avg_cpu_utilization_pct",
        "max_cpu_utilization_pct",
        "avg_memory_working_set_bytes",
        "max_memory_working_set_bytes",
        "max_memory_used_gb",
        "avg_cpu_throttling_ratio",
        "max_cpu_throttling_ratio",
        "min_ready_pods",
        "avg_ready_pods",
        "max_ready_pods",
        "max_restarts_total",
        "frontend_latency_p50_ms",
        "frontend_latency_p95_ms",
        "frontend_latency_p99_ms",
        "frontend_latency_max_ms",
        "avg_requests_per_second",
        "load_users_per_second",
        "node_hourly_price_usd",
        "benchmark_compute_cost_usd",
        "cost_per_1m_requests_usd",
        "metrics_coverage_ratio",
    }
    for field in integer_fields:
        if field in normalized:
            normalized[field] = parse_int_field(normalized[field])
    for field in float_fields:
        if field in normalized:
            normalized[field] = parse_float_field(normalized[field])
    if isinstance(normalized.get("invalid_metric_samples"), str):
        normalized["invalid_metric_samples"] = parse_json_object_field(
            normalized["invalid_metric_samples"],
            field="invalid_metric_samples",
            run_id=str(normalized.get("run_id") or ""),
        )
    return normalized


def parse_int_field(value: Any) -> int | None:
    """Parse integer field.


    Args:
        value: value (Any) used by this operation.

    Returns:
        int | None value produced by parse integer field.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if re_fullmatch_int(stripped):
            return int(stripped)
    return value


def parse_float_field(value: Any) -> float | None:
    """Parse float field.


    Args:
        value: value (Any) used by this operation.

    Returns:
        float | None value produced by parse float field.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return value
        return parsed if math.isfinite(parsed) else None
    return value


def parse_json_object_field(value: str, *, field: str, run_id: str) -> dict[str, Any]:
    """Parse jSON object field.


    Args:
        value: value (str) used by this operation.
        field: field (str) used by this operation.
        run_id: run ID (str) used by this operation.

    Returns:
        dict[str, Any] value produced by parse JSON object field.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        label = f" for run_id {run_id}" if run_id else ""
        raise ComparisonReportError(f"BigQuery field {field}{label} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        label = f" for run_id {run_id}" if run_id else ""
        raise ComparisonReportError(f"BigQuery field {field}{label} is not a JSON object")
    return parsed


def re_fullmatch_int(value: str) -> bool:
    """Compute re fullmatch integer.


    Args:
        value: value (str) used by this operation.

    Returns:
        bool value produced by re fullmatch integer.
    """
    return value.isdigit() or (value.startswith("-") and value[1:].isdigit())


def build_comparison_report(
    *,
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    schema: dict[str, Any],
    schema_path: Path,
    min_duration_seconds: int,
    min_coverage_ratio: float,
) -> dict[str, Any]:
    """Build comparison report.


    Args:
        rows: rows (list[dict[str, Any]]) used by this operation.
        source: source (dict[str, Any]) used by this operation.
        schema: schema (dict[str, Any]) used by this operation.
        schema_path: schema path (Path) used by this operation.
        min_duration_seconds: min duration seconds (int) used by this operation.
        min_coverage_ratio: min coverage ratio (float) used by this operation.

    Returns:
        dict[str, Any] value produced by build comparison report.
    """
    schema_fields = comparability.schema_field_set(schema)
    accepted_rows: list[dict[str, Any]] = []
    rejected_runs: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    schema_drift_found = False
    for index, row in enumerate(rows, 1):
        reasons = comparability.rejection_reasons(
            row=row,
            row_index=index,
            schema_fields=schema_fields,
            min_duration_seconds=min_duration_seconds,
            min_coverage_ratio=min_coverage_ratio,
        )
        if any(reason.startswith("schema_") for reason in reasons):
            schema_drift_found = True
        audit_findings = summary_audit.row_findings(
            row,
            row_index=index,
            min_duration_seconds=min_duration_seconds,
            min_coverage_ratio=min_coverage_ratio,
        )
        suspect_findings = summary_audit.suspect_findings(audit_findings)
        if suspect_findings:
            reasons.extend(suspect_findings)
        if reasons:
            rejected_runs.append({"run_id": row.get("run_id") or f"row-{index}", "reasons": reasons})
        else:
            accepted_rows.append(row)

    schema_drift_found = schema_drift_found or reject_field_set_drift(
        accepted_rows, rejected_runs
    )
    groups = aggregate_groups(accepted_rows, warnings)
    rankings = build_rankings(groups)
    status = report_status(
        total_rows=len(rows),
        group_count=len(groups),
        rejected_count=len(rejected_runs),
        warning_count=len(warnings),
        schema_drift_found=schema_drift_found,
    )
    return {
        "status": status,
        "source": source,
        "generated_at": utc_now(),
        "schema": str(schema_path),
        "total_rows": len(rows),
        "comparable_run_count": len(accepted_rows),
        "comparison_group_count": len(groups),
        "comparison_groups": groups,
        "rankings": rankings,
        "rejected_runs": rejected_runs,
        "suspect_run_ids": [
            rejected["run_id"]
            for rejected in rejected_runs
            if summary_audit.suspect_findings(rejected.get("reasons", []))
        ],
        "warnings": warnings,
    }


def reject_field_set_drift(
    accepted_rows: list[dict[str, Any]], rejected_runs: list[dict[str, Any]]
) -> bool:
    """Compute reject field set drift.


    Args:
        accepted_rows: accepted rows (list[dict[str, Any]]) used by this operation.
        rejected_runs: rejected runs (list[dict[str, Any]]) used by this operation.

    Returns:
        bool value produced by reject field set drift.
    """
    field_sets = [
        sorted(field for field in row if field not in comparability.NULLABLE_COMPARABILITY_FIELDS)
        for row in accepted_rows
    ]
    if field_sets and any(field_set != field_sets[0] for field_set in field_sets):
        rejected_runs.append(
            {
                "run_id": "__comparable_field_set__",
                "reasons": ["comparable_rows_do_not_share_the_same_field_set"],
            }
        )
        return True
    return False


def aggregate_groups(
    rows: list[dict[str, Any]], warnings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Aggregate groups.


    Args:
        rows: rows (list[dict[str, Any]]) used by this operation.
        warnings: warnings (list[dict[str, Any]]) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by aggregate groups.
    """
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(group_key(row), []).append(row)
    groups = [aggregate_group(index, rows, warnings) for index, rows in enumerate(buckets.values(), 1)]
    return sorted(groups, key=lambda group: group["group_id"])


def aggregate_group(
    index: int, rows: list[dict[str, Any]], warnings: list[dict[str, Any]]
) -> dict[str, Any]:
    """Aggregate group.


    Args:
        index: index (int) used by this operation.
        rows: rows (list[dict[str, Any]]) used by this operation.
        warnings: warnings (list[dict[str, Any]]) used by this operation.

    Returns:
        dict[str, Any] value produced by aggregate group.
    """
    first = rows[0]
    metrics = {
        field: mean_number(row.get(field) for row in rows)
        for field in MEAN_FIELDS
    }
    request_total = sum_int(row.get("request_count_total") for row in rows)
    request_failure = sum_int(row.get("request_failure_count") for row in rows)
    avg_rps = metrics["avg_requests_per_second"]
    avg_cpu = metrics["avg_cpu_usage_cores"]
    group_id = f"group-{index:03d}"
    if metrics["cost_per_1m_requests_usd"] is None:
        warnings.append(
            {
                "group_id": group_id,
                "reason": "missing_cost_fields",
                "run_ids": sorted(str(row.get("run_id")) for row in rows),
            }
        )
    return {
        "group_id": group_id,
        "metadata": {field: first.get(field) for field in GROUP_FIELDS},
        "run_count": len(rows),
        "run_ids": sorted(str(row.get("run_id")) for row in rows),
        "latest_benchmark_start": max_string(row.get("benchmark_start") for row in rows),
        "latest_benchmark_end": max_string(row.get("benchmark_end") for row in rows),
        "metrics": {
            **metrics,
            "request_failure_ratio": ratio(request_failure, request_total),
            "requests_per_cpu_core": ratio(avg_rps, avg_cpu),
        },
    }


def build_rankings(groups: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Build rankings.


    Args:
        groups: groups (list[dict[str, Any]]) used by this operation.

    Returns:
        dict[str, list[dict[str, Any]]] value produced by build rankings.
    """
    rankings: dict[str, list[dict[str, Any]]] = {}
    for metric, direction in RANKINGS.items():
        entries = []
        for group in groups:
            value = number_or_none(group["metrics"].get(metric))
            if value is None:
                continue
            metadata = group["metadata"]
            entries.append(
                {
                    "group_id": group["group_id"],
                    "machine_type": metadata.get("machine_type"),
                    "processor_family": metadata.get("processor_family"),
                    "pricing_model": metadata.get("pricing_model"),
                    "value": value,
                }
            )
        entries.sort(key=lambda entry: entry["value"], reverse=direction == "desc")
        rankings[metric] = [
            {"rank": rank, **entry} for rank, entry in enumerate(entries, 1)
        ]
    return rankings


def render_markdown(report: dict[str, Any]) -> str:
    """Render markdown.


    Args:
        report: report (dict[str, Any]) used by this operation.

    Returns:
        str value produced by render markdown.
    """
    lines = [
        "# SiliconBoutique Comparison Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Source: `{report['source'].get('type')}`",
        f"- Comparable runs: `{report['comparable_run_count']}`",
        f"- Rejected runs: `{len(report['rejected_runs'])}`",
        "",
        "## Comparison Groups",
        "",
        "| Rank | Provider | Region | Machine | Processor | Arch | Pricing | Runs | Avg RPS | P99 Latency ms | Cost / 1M | Req / CPU Core | Failure Ratio | Coverage |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    latency_ranks = ranking_lookup(report["rankings"].get("frontend_latency_p99_ms", []))
    for group in report["comparison_groups"]:
        metadata = group["metadata"]
        metrics = group["metrics"]
        lines.append(
            "| {rank} | {provider} | {region} | {machine} | {processor} | {arch} | {pricing} | {runs} | {rps} | {p99} | {cost} | {efficiency} | {failure} | {coverage} |".format(
                rank=latency_ranks.get(group["group_id"], ""),
                provider=metadata.get("cloud_provider") or "",
                region=metadata.get("region") or "",
                machine=metadata.get("machine_type") or "",
                processor=metadata.get("processor_family") or "",
                arch=metadata.get("architecture") or "",
                pricing=metadata.get("pricing_model") or "",
                runs=group["run_count"],
                rps=format_number(metrics.get("avg_requests_per_second")),
                p99=format_number(metrics.get("frontend_latency_p99_ms")),
                cost=format_number(metrics.get("cost_per_1m_requests_usd")),
                efficiency=format_number(metrics.get("requests_per_cpu_core")),
                failure=format_number(metrics.get("request_failure_ratio")),
                coverage=format_number(metrics.get("metrics_coverage_ratio")),
            )
        )
    if report["rejected_runs"]:
        lines.extend(["", "## Rejected Runs", "", "| Run ID | Reasons |", "| --- | --- |"])
        for rejected in report["rejected_runs"]:
            lines.append(
                f"| {rejected['run_id']} | {', '.join(rejected.get('reasons', []))} |"
            )
    if report["warnings"]:
        lines.extend(["", "## Warnings", "", "| Group | Reason |", "| --- | --- |"])
        for warning in report["warnings"]:
            lines.append(f"| {warning.get('group_id', '')} | {warning.get('reason', '')} |")
    return "\n".join(lines) + "\n"


def report_status(
    *,
    total_rows: int,
    group_count: int,
    rejected_count: int,
    warning_count: int,
    schema_drift_found: bool,
) -> str:
    """Compute report status.


    Args:
        total_rows: total rows (int) used by this operation.
        group_count: group count (int) used by this operation.
        rejected_count: rejected count (int) used by this operation.
        warning_count: warning count (int) used by this operation.
        schema_drift_found: schema drift found (bool) used by this operation.

    Returns:
        str value produced by report status.
    """
    if total_rows == 0 or group_count == 0 or schema_drift_found:
        return "fail"
    if rejected_count or warning_count:
        return "warn"
    return "pass"


def filter_values(args: argparse.Namespace) -> dict[str, str]:
    """Filter values.


    Args:
        args: arguments (argparse.Namespace) used by this operation.

    Returns:
        dict[str, str] value produced by filter values.
    """
    return {
        field: value
        for field, value in (
            ("machine_type", args.machine_type),
            ("processor_family", args.processor_family),
            ("architecture", args.architecture),
            ("cloud_provider", args.cloud_provider),
            ("pricing_model", args.pricing_model),
        )
        if value is not None
    }


def apply_filters(rows: list[dict[str, Any]], filters: dict[str, str]) -> list[dict[str, Any]]:
    """Apply filters.


    Args:
        rows: rows (list[dict[str, Any]]) used by this operation.
        filters: filters (dict[str, str]) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by apply filters.
    """
    return [
        row
        for row in rows
        if all(str(row.get(field)) == value for field, value in filters.items())
    ]


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort rows.


    Args:
        rows: rows (list[dict[str, Any]]) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by sort rows.
    """
    return sorted(rows, key=lambda row: str(row.get("benchmark_start") or ""), reverse=True)


def group_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Compute group key.


    Args:
        row: row (dict[str, Any]) used by this operation.

    Returns:
        tuple[Any, ...] value produced by group key.
    """
    return tuple(row.get(field) for field in GROUP_FIELDS)


def sum_int(values: Any) -> int:
    """Compute sum integer.


    Args:
        values: values (Any) used by this operation.

    Returns:
        int value produced by sum integer.
    """
    total = 0
    for value in values:
        parsed = number_or_none(value)
        if parsed is not None:
            total += int(parsed)
    return total


def mean_number(values: Any) -> float | None:
    """Compute mean number.


    Args:
        values: values (Any) used by this operation.

    Returns:
        float | None value produced by mean number.
    """
    numbers = [number for number in (number_or_none(value) for value in values) if number is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 6)


def ratio(numerator: Any, denominator: Any) -> float | None:
    """Compute ratio.


    Args:
        numerator: numerator (Any) used by this operation.
        denominator: denominator (Any) used by this operation.

    Returns:
        float | None value produced by ratio.
    """
    numerator_value = number_or_none(numerator)
    denominator_value = number_or_none(denominator)
    if numerator_value is None or denominator_value is None or denominator_value <= 0:
        return None
    return round(numerator_value / denominator_value, 6)


def number_or_none(value: Any) -> float | None:
    """Compute number or none.


    Args:
        value: value (Any) used by this operation.

    Returns:
        float | None value produced by number or none.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def max_string(values: Any) -> str | None:
    """Compute max string.


    Args:
        values: values (Any) used by this operation.

    Returns:
        str | None value produced by max string.
    """
    strings = [str(value) for value in values if value]
    return max(strings) if strings else None


def ranking_lookup(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Compute ranking lookup.


    Args:
        entries: entries (list[dict[str, Any]]) used by this operation.

    Returns:
        dict[str, int] value produced by ranking lookup.
    """
    return {entry["group_id"]: entry["rank"] for entry in entries}


def format_number(value: Any) -> str:
    """Format number.


    Args:
        value: value (Any) used by this operation.

    Returns:
        str value produced by format number.
    """
    number = number_or_none(value)
    if number is None:
        return ""
    return f"{number:.6g}"


def run_bq(command: list[str]) -> CommandResult:
    """Run bigQuery.


    Args:
        command: command (list[str]) used by this operation.

    Returns:
        CommandResult value produced by run bigquery.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        return bq_helpers.run_bq(command)
    except bq_helpers.BigQueryHelperError as exc:
        raise ComparisonReportError(str(exc)) from exc


def write_text(path: Path, content: str) -> None:
    """Write text.


    Args:
        path: path (Path) used by this operation.
        content: content (str) used by this operation.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
