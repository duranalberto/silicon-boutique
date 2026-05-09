#!/usr/bin/env python3
"""Generate comparison reports from historical SiliconBoutique summaries."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import load_benchmark_summary_to_bigquery as bigquery
import validate_benchmark_comparability as comparability


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


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]


def parse_args() -> argparse.Namespace:
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
    except (ComparisonReportError, comparability.ComparabilityError, bigquery.BigQueryLoadError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def load_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
        "summary_table": bigquery.table_sql_name(
            args.project_id, args.dataset_id, args.table_id
        ),
        "location": args.location,
    }


def read_summary_store(path: Path) -> list[dict[str, Any]]:
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
    bigquery.validate_destination(project_id, dataset_id, table_id, location)
    where_parts = [
        f"{field} = {bigquery.sql_string(value)}"
        for field, value in filters.items()
        if value is not None
    ]
    query = (
        "SELECT * FROM "
        f"`{bigquery.table_sql_name(project_id, dataset_id, table_id)}`"
    )
    if where_parts:
        query += " WHERE " + " AND ".join(where_parts)
    query += " ORDER BY benchmark_start DESC"
    if limit is not None:
        query += f" LIMIT {limit}"
    result = runner(
        [
            "bq",
            "query",
            "--nouse_legacy_sql",
            "--format=json",
            "--project_id",
            project_id,
            "--location",
            location,
            query,
        ]
    )
    if result.returncode != 0:
        raise ComparisonReportError("failed to query BigQuery summaries: " + result.stderr.strip())
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise ComparisonReportError("bq query did not return valid JSON") from exc
    if not isinstance(payload, list):
        raise ComparisonReportError("bq query did not return a row array")
    return [row for row in payload if isinstance(row, dict)]


def build_comparison_report(
    *,
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    schema: dict[str, Any],
    schema_path: Path,
    min_duration_seconds: int,
    min_coverage_ratio: float,
) -> dict[str, Any]:
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
        "warnings": warnings,
    }


def reject_field_set_drift(
    accepted_rows: list[dict[str, Any]], rejected_runs: list[dict[str, Any]]
) -> bool:
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
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(group_key(row), []).append(row)
    groups = [aggregate_group(index, rows, warnings) for index, rows in enumerate(buckets.values(), 1)]
    return sorted(groups, key=lambda group: group["group_id"])


def aggregate_group(
    index: int, rows: list[dict[str, Any]], warnings: list[dict[str, Any]]
) -> dict[str, Any]:
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
        "| Rank | Machine | Processor | Arch | Pricing | Runs | Avg RPS | P99 Latency ms | Cost / 1M | Req / CPU Core | Failure Ratio | Coverage |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    latency_ranks = ranking_lookup(report["rankings"].get("frontend_latency_p99_ms", []))
    for group in report["comparison_groups"]:
        metadata = group["metadata"]
        metrics = group["metrics"]
        lines.append(
            "| {rank} | {machine} | {processor} | {arch} | {pricing} | {runs} | {rps} | {p99} | {cost} | {efficiency} | {failure} | {coverage} |".format(
                rank=latency_ranks.get(group["group_id"], ""),
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
    if total_rows == 0 or group_count == 0 or schema_drift_found:
        return "fail"
    if rejected_count or warning_count:
        return "warn"
    return "pass"


def filter_values(args: argparse.Namespace) -> dict[str, str]:
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
    return [
        row
        for row in rows
        if all(str(row.get(field)) == value for field, value in filters.items())
    ]


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get("benchmark_start") or ""), reverse=True)


def group_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in GROUP_FIELDS)


def sum_int(values: Any) -> int:
    total = 0
    for value in values:
        parsed = number_or_none(value)
        if parsed is not None:
            total += int(parsed)
    return total


def mean_number(values: Any) -> float | None:
    numbers = [number for number in (number_or_none(value) for value in values) if number is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 6)


def ratio(numerator: Any, denominator: Any) -> float | None:
    numerator_value = number_or_none(numerator)
    denominator_value = number_or_none(denominator)
    if numerator_value is None or denominator_value is None or denominator_value <= 0:
        return None
    return round(numerator_value / denominator_value, 6)


def number_or_none(value: Any) -> float | None:
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
    strings = [str(value) for value in values if value]
    return max(strings) if strings else None


def ranking_lookup(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {entry["group_id"]: entry["rank"] for entry in entries}


def format_number(value: Any) -> str:
    number = number_or_none(value)
    if number is None:
        return ""
    return f"{number:.6g}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def run_bq(command: list[str]) -> CommandResult:
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ComparisonReportError("bq command was not found in PATH") from exc
    return CommandResult(result.returncode, result.stdout, result.stderr)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
