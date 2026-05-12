#!/usr/bin/env python3
"""Validate SiliconBoutique benchmark summary comparability."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BASELINE_LABEL_FIELDS = (
    "run_id",
    "environment",
    "cloud_provider",
    "region",
    "zone",
    "machine_type",
    "processor_family",
    "architecture",
    "pricing_model",
)

QUALITY_LIST_FIELDS = ("missing_metrics", "empty_metrics")
QUALITY_MAP_FIELDS = ("invalid_metric_samples",)
NULLABLE_COMPARABILITY_FIELDS = (
    "benchmark_compute_cost_usd",
    "cost_per_1m_requests_usd",
    "node_hourly_price_usd",
)
NON_NULLABLE_COMPARABLE_METRIC_FIELDS = (
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
    "request_count_total",
    "request_success_count",
    "request_failure_count",
    "avg_requests_per_second",
    "load_concurrent_users",
    "load_users_per_second",
    "load_profile_source",
    "node_count",
)


class ComparabilityError(RuntimeError):
    """Raised when the comparability validator cannot inspect inputs."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate benchmark summary quality and comparability."
    )
    parser.add_argument("--summary-store", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument(
        "--run-id",
        help=(
            "Validate only one run_id from a multi-row store. Without this, "
            "all rows in the store are validated."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("summary", "comparability"),
        default="comparability",
        help=(
            "summary validates each row independently; comparability also requires "
            "at least two comparable rows."
        ),
    )
    parser.add_argument("--min-duration-seconds", type=int, default=1200)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when the selected validation mode does not pass.",
    )
    args = parser.parse_args()
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if not 0 <= args.min_coverage_ratio <= 1:
        parser.error("--min-coverage-ratio must be between 0 and 1")
    return args


def main() -> int:
    args = parse_args()
    try:
        schema = load_json(args.schema, "schema")
        rows = read_summary_store(args.summary_store)
        selected_rows = select_rows(rows, args.run_id)
        report = build_report(
            summary_store=args.summary_store,
            schema_path=args.schema,
            schema=schema,
            rows=selected_rows,
            source_total_rows=len(rows),
            selected_run_id=args.run_id,
            mode=args.mode,
            min_duration_seconds=args.min_duration_seconds,
            min_coverage_ratio=args.min_coverage_ratio,
        )
        write_json(args.report_output, report)
    except ComparabilityError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    status_field = f"{args.mode}_validation_status"
    if args.strict and report[status_field] != "pass":
        print(
            f"{args.mode} validation {report[status_field]}; see {args.report_output}",
            file=sys.stderr,
        )
        detail = strict_failure_detail(report)
        if detail:
            print(detail, file=sys.stderr)
        return 2
    return 0


def build_report(
    *,
    summary_store: Path,
    schema_path: Path,
    schema: dict[str, Any],
    rows: list[dict[str, Any]],
    source_total_rows: int,
    selected_run_id: str | None,
    mode: str,
    min_duration_seconds: int,
    min_coverage_ratio: float,
) -> dict[str, Any]:
    schema_fields = schema_field_set(schema)
    comparable_run_ids: list[str] = []
    rejected_runs: list[dict[str, Any]] = []
    schema_drift_found = False

    for index, row in enumerate(rows, 1):
        reasons = rejection_reasons(
            row=row,
            row_index=index,
            schema_fields=schema_fields,
            min_duration_seconds=min_duration_seconds,
            min_coverage_ratio=min_coverage_ratio,
        )
        if any(reason.startswith("schema_") for reason in reasons):
            schema_drift_found = True
        if reasons:
            rejected_runs.append(
                {
                    "run_id": row.get("run_id") or f"row-{index}",
                    "reasons": reasons,
                }
            )
        else:
            comparable_run_ids.append(row["run_id"])

    comparable_field_sets = [
        sorted(field for field in row if field not in NULLABLE_COMPARABILITY_FIELDS)
        for row in rows
        if row.get("run_id") in comparable_run_ids
    ]
    if comparable_field_sets and any(
        field_set != comparable_field_sets[0] for field_set in comparable_field_sets
    ):
        schema_drift_found = True
        rejected_runs.append(
            {
                "run_id": "__comparable_field_set__",
                "reasons": ["comparable_rows_do_not_share_the_same_field_set"],
            }
        )

    summary_status = summary_validation_status(
        total_rows=len(rows),
        rejected_count=len(rejected_runs),
        schema_drift_found=schema_drift_found,
    )
    cross_run_status = comparability_status(
        total_rows=len(rows),
        comparable_count=len(comparable_run_ids),
        rejected_count=len(rejected_runs),
        schema_drift_found=schema_drift_found,
    )

    return {
        "summary_store": str(summary_store),
        "schema": str(schema_path),
        "validation_mode": mode,
        "selected_run_id": selected_run_id,
        "source_total_rows": source_total_rows,
        "min_duration_seconds": min_duration_seconds,
        "min_coverage_ratio": min_coverage_ratio,
        "total_rows": len(rows),
        "comparable_run_ids": comparable_run_ids,
        "rejected_runs": rejected_runs,
        "schema_field_count": len(schema_fields),
        "summary_validation_status": summary_status,
        "comparability_validation_status": cross_run_status,
        "comparability_status": cross_run_status,
    }


def select_rows(rows: list[dict[str, Any]], run_id: str | None) -> list[dict[str, Any]]:
    if run_id:
        selected = [row for row in rows if row.get("run_id") == run_id]
        if len(selected) != 1:
            raise ComparabilityError(
                f"expected exactly one summary row for run_id {run_id!r}, found {len(selected)}"
            )
        return selected
    return rows


def rejection_reasons(
    *,
    row: dict[str, Any],
    row_index: int,
    schema_fields: set[str],
    min_duration_seconds: int,
    min_coverage_ratio: float,
) -> list[str]:
    reasons: list[str] = []
    row_fields = set(row)
    extra_fields = sorted(row_fields - schema_fields)
    missing_fields = sorted(schema_fields - row_fields)
    if extra_fields:
        reasons.append("schema_extra_fields:" + ",".join(extra_fields))
    if missing_fields:
        reasons.append("schema_missing_fields:" + ",".join(missing_fields))

    missing_labels = [
        field for field in BASELINE_LABEL_FIELDS if not non_empty_string(row.get(field))
    ]
    if missing_labels:
        reasons.append("missing_baseline_labels:" + ",".join(missing_labels))

    node_count = numeric_value(row.get("node_count"))
    if node_count is None or node_count < 1 or int(node_count) != node_count:
        reasons.append("invalid_node_count")

    if row.get("pricing_model") not in {"local", "spot", "on_demand"}:
        reasons.append("invalid_pricing_model")

    if row.get("summary_status") != "complete":
        reasons.append("summary_status_not_complete")

    duration = numeric_value(row.get("duration_seconds"))
    if duration is None:
        reasons.append("duration_seconds_missing")
    elif duration < min_duration_seconds:
        reasons.append(
            f"duration_seconds_below_min:{int(duration)}<{min_duration_seconds}"
        )

    coverage = numeric_value(row.get("metrics_coverage_ratio"))
    if coverage is None:
        reasons.append("metrics_coverage_ratio_missing")
    elif coverage < min_coverage_ratio:
        reasons.append(
            f"metrics_coverage_ratio_below_min:{coverage:g}<{min_coverage_ratio:g}"
        )

    for field in QUALITY_LIST_FIELDS:
        value = row.get(field)
        if value:
            reasons.append(f"{field}_not_empty")
        elif not isinstance(value, list):
            reasons.append(f"{field}_not_list")

    for field in QUALITY_MAP_FIELDS:
        value = row.get(field)
        if value:
            reasons.append(f"{field}_not_empty")
        elif not isinstance(value, dict):
            reasons.append(f"{field}_not_object")

    missing_metric_fields = [
        field for field in NON_NULLABLE_COMPARABLE_METRIC_FIELDS if row.get(field) is None
    ]
    if missing_metric_fields:
        reasons.append("missing_comparable_metric_fields:" + ",".join(missing_metric_fields))

    if not row_fields:
        reasons.append(f"row_{row_index}_empty")

    return reasons


def comparability_status(
    *,
    total_rows: int,
    comparable_count: int,
    rejected_count: int,
    schema_drift_found: bool,
) -> str:
    if schema_drift_found or rejected_count or comparable_count < 2:
        return "fail"
    if total_rows == 0:
        return "fail"
    if comparable_count == total_rows:
        return "pass"
    return "warn"


def summary_validation_status(
    *,
    total_rows: int,
    rejected_count: int,
    schema_drift_found: bool,
) -> str:
    if total_rows == 0 or rejected_count or schema_drift_found:
        return "fail"
    return "pass"


def schema_field_set(schema: dict[str, Any]) -> set[str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ComparabilityError("schema does not define object properties")
    return set(properties)


def read_summary_store(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ComparabilityError(f"summary store does not exist: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComparabilityError(
                f"summary store contains invalid JSON on line {line_number}: {path}"
            ) from exc
        if not isinstance(row, dict):
            raise ComparabilityError(
                f"summary store line {line_number} is not a JSON object: {path}"
            )
        rows.append(row)
    return rows


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ComparabilityError(f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ComparabilityError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ComparabilityError(f"{label} is not a JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def strict_failure_detail(report: dict[str, Any]) -> str:
    rejected_runs = report.get("rejected_runs")
    if not isinstance(rejected_runs, list) or not rejected_runs:
        return ""

    lines = ["rejected runs:"]
    for rejected in rejected_runs:
        if not isinstance(rejected, dict):
            continue
        run_id = rejected.get("run_id", "<unknown>")
        reasons = rejected.get("reasons")
        if isinstance(reasons, list) and reasons:
            reason_text = "; ".join(str(reason) for reason in reasons)
        else:
            reason_text = "<no reasons recorded>"
        lines.append(f"- {run_id}: {reason_text}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
