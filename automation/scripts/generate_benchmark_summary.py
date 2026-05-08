#!/usr/bin/env python3
"""Generate and persist a SiliconBoutique benchmark summary."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BYTES_PER_GB = 1_000_000_000
MS_PER_SECOND = 1000
REQUIRED_DERIVED_FIELDS = (
    "duration_seconds",
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
    "metrics_coverage_ratio",
)


class SummaryError(RuntimeError):
    """Raised when a benchmark summary cannot be generated safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a query-friendly SiliconBoutique benchmark summary."
    )
    parser.add_argument("--metrics-input", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--summary-store", type=Path, required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--machine-type", required=True)
    parser.add_argument("--processor-family", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--cloud-provider", required=True)
    parser.add_argument("--region", default=None)
    parser.add_argument("--node-count", type=int, default=1)
    parser.add_argument("--pricing-model", default="spot")
    parser.add_argument("--concurrent-users")
    parser.add_argument("--users-per-second")
    parser.add_argument("--load-profile-source", default="manual")
    parser.add_argument("--loadgenerator-stats", type=Path)
    parser.add_argument("--pricing-table", type=Path)
    parser.add_argument(
        "--generated-at",
        help="UTC timestamp to use for generated_at. Defaults to the current time.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing summary row with the same run_id in the local store.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when required metadata, metric quality, or derived fields are invalid.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        metrics_payload = load_json(args.metrics_input)
        loadgenerator_stats = (
            load_json(args.loadgenerator_stats) if args.loadgenerator_stats else None
        )
        pricing_table = load_pricing_table(args.pricing_table) if args.pricing_table else None
        summary = build_summary(
            metrics_payload=metrics_payload,
            loadgenerator_stats=loadgenerator_stats,
            pricing_table=pricing_table,
            environment=args.environment,
            machine_type=args.machine_type,
            processor_family=args.processor_family,
            architecture=args.architecture,
            cloud_provider=args.cloud_provider,
            region=args.region,
            node_count=args.node_count,
            pricing_model=args.pricing_model,
            concurrent_users=args.concurrent_users,
            users_per_second=args.users_per_second,
            load_profile_source=args.load_profile_source,
            generated_at=args.generated_at,
        )
        validate_summary(summary, strict=args.strict)
        assert_summary_store_accepts(
            args.summary_store, summary["run_id"], replace=args.replace
        )
        write_json(args.summary_output, summary)
        persist_summary(args.summary_store, summary, replace=args.replace)
    except SummaryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SummaryError(f"metrics input does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SummaryError(f"metrics input is not valid JSON: {path}") from exc


def build_summary(
    *,
    metrics_payload: dict[str, Any],
    loadgenerator_stats: dict[str, Any] | None,
    pricing_table: list[dict[str, Any]] | None,
    environment: str,
    machine_type: str,
    processor_family: str,
    architecture: str,
    cloud_provider: str,
    region: str | None,
    node_count: int,
    pricing_model: str,
    concurrent_users: str | None,
    users_per_second: str | None,
    load_profile_source: str,
    generated_at: str | None,
) -> dict[str, Any]:
    window = metrics_payload.get("window", {})
    quality = metrics_payload.get("quality", {})
    metrics = metrics_payload.get("metrics", {})
    benchmark_start = normalize_timestamp(window.get("start"))
    benchmark_end = normalize_timestamp(window.get("end"))
    duration = duration_seconds(benchmark_start, benchmark_end)
    request_total = int_or_none(
        (loadgenerator_stats or {}).get("request_count_total")
    )
    request_success = int_or_none(
        (loadgenerator_stats or {}).get("request_success_count")
    )
    request_failure = int_or_none(
        (loadgenerator_stats or {}).get("request_failure_count")
    )
    avg_rps = number_or_none(
        (loadgenerator_stats or {}).get("avg_requests_per_second")
    )
    node_hourly_price = lookup_hourly_price(
        pricing_table=pricing_table,
        cloud_provider=cloud_provider,
        region=region,
        machine_type=machine_type,
        pricing_model=pricing_model,
    )
    compute_cost = benchmark_compute_cost(
        node_hourly_price_usd=node_hourly_price,
        node_count=node_count,
        duration_seconds=duration,
    )

    summary = {
        "run_id": metrics_payload.get("run_id"),
        "namespace": metrics_payload.get("namespace"),
        "environment": clean_required_value(environment),
        "cloud_provider": clean_required_value(cloud_provider),
        "machine_type": clean_required_value(machine_type),
        "processor_family": clean_required_value(processor_family),
        "architecture": clean_required_value(architecture),
        "benchmark_start": benchmark_start,
        "benchmark_end": benchmark_end,
        "duration_seconds": duration,
        "generated_at": normalize_timestamp(generated_at) if generated_at else utc_now(),
        "avg_cpu_usage_cores": metric_value(metrics, "cpu_usage_cores", "avg"),
        "max_cpu_usage_cores": metric_value(metrics, "cpu_usage_cores", "max"),
        "avg_cpu_utilization_pct": metric_value(metrics, "cpu_utilization_pct", "avg"),
        "max_cpu_utilization_pct": metric_value(metrics, "cpu_utilization_pct", "max"),
        "avg_memory_working_set_bytes": metric_value(
            metrics, "memory_working_set_bytes", "avg"
        ),
        "max_memory_working_set_bytes": metric_value(
            metrics, "memory_working_set_bytes", "max"
        ),
        "max_memory_used_gb": bytes_to_gb(
            metric_value(metrics, "memory_working_set_bytes", "max")
        ),
        "avg_cpu_throttling_ratio": metric_value(
            metrics, "cpu_throttling_ratio", "avg"
        ),
        "max_cpu_throttling_ratio": metric_value(
            metrics, "cpu_throttling_ratio", "max"
        ),
        "min_ready_pods": metric_value(metrics, "ready_pods", "min"),
        "avg_ready_pods": metric_value(metrics, "ready_pods", "avg"),
        "max_ready_pods": metric_value(metrics, "ready_pods", "max"),
        "max_restarts_total": metric_value(metrics, "restarts_total", "max"),
        "frontend_latency_p50_ms": seconds_to_ms(
            metric_value(metrics, "frontend_probe_latency_seconds", "p50")
        ),
        "frontend_latency_p95_ms": seconds_to_ms(
            metric_value(metrics, "frontend_probe_latency_seconds", "p95")
        ),
        "frontend_latency_p99_ms": seconds_to_ms(
            metric_value(metrics, "frontend_probe_latency_seconds", "p99")
        ),
        "frontend_latency_max_ms": seconds_to_ms(
            metric_value(metrics, "frontend_probe_latency_seconds", "max")
        ),
        "request_count_total": request_total,
        "request_success_count": request_success,
        "request_failure_count": request_failure,
        "avg_requests_per_second": avg_rps,
        "load_concurrent_users": int_or_none(concurrent_users),
        "load_users_per_second": number_or_none(users_per_second),
        "load_profile_source": clean_required_value(load_profile_source),
        "node_hourly_price_usd": node_hourly_price,
        "benchmark_compute_cost_usd": compute_cost,
        "cost_per_1m_requests_usd": cost_per_1m_requests(
            compute_cost_usd=compute_cost,
            request_success_count=request_success,
        ),
        "metrics_coverage_ratio": quality.get("coverage_ratio"),
        "missing_metrics": quality.get("missing_series", []),
        "empty_metrics": quality.get("empty_series", []),
        "invalid_metric_samples": quality.get("invalid_samples", {}),
    }
    summary["summary_status"] = summary_status(summary)
    return summary


def validate_summary(summary: dict[str, Any], *, strict: bool) -> None:
    identity_fields = (
        "run_id",
        "namespace",
        "environment",
        "cloud_provider",
        "machine_type",
        "processor_family",
        "architecture",
    )
    missing_identity = [
        field for field in identity_fields if not clean_required_value(summary.get(field))
    ]
    if missing_identity:
        raise SummaryError(
            "required identity metadata is missing: " + ", ".join(missing_identity)
        )

    if not strict:
        return

    quality_fields = ("missing_metrics", "empty_metrics", "invalid_metric_samples")
    failed_quality = [field for field in quality_fields if summary.get(field)]
    if failed_quality:
        raise SummaryError(
            "required metric quality checks failed: " + ", ".join(failed_quality)
        )

    request_fields = (
        "request_count_total",
        "request_success_count",
        "request_failure_count",
        "avg_requests_per_second",
    )
    missing_requests = [field for field in request_fields if summary.get(field) is None]
    if missing_requests:
        raise SummaryError(
            "required loadgenerator stats are missing: " + ", ".join(missing_requests)
        )
    if summary.get("request_success_count") == 0:
        raise SummaryError("request_success_count must be greater than zero in strict mode")

    priced_run = summary.get("cloud_provider") != "local" or summary.get("node_hourly_price_usd") is not None
    if priced_run:
        cost_fields = (
            "node_hourly_price_usd",
            "benchmark_compute_cost_usd",
            "cost_per_1m_requests_usd",
        )
        missing_cost = [field for field in cost_fields if summary.get(field) is None]
        if missing_cost:
            raise SummaryError(
                "required pricing fields are missing: " + ", ".join(missing_cost)
            )

    validate_cpu_utilization_bounds(summary)

    missing_derived = [
        field for field in REQUIRED_DERIVED_FIELDS if summary.get(field) is None
    ]
    if missing_derived:
        raise SummaryError(
            "required derived summary fields are missing: "
            + ", ".join(missing_derived)
        )


def validate_cpu_utilization_bounds(summary: dict[str, Any]) -> None:
    node_count = int_or_none(summary.get("node_count")) or 1
    upper_bound = max(100.0, 100.0 * node_count)
    invalid_fields: list[str] = []
    for field in ("avg_cpu_utilization_pct", "max_cpu_utilization_pct"):
        value = summary.get(field)
        if value is None:
            continue
        numeric = number_or_none(value)
        if numeric is None or not math.isfinite(numeric) or numeric < 0 or numeric > upper_bound:
            invalid_fields.append(field)
    if invalid_fields:
        raise SummaryError(
            "CPU utilization fields are outside the expected range 0-"
            f"{upper_bound:g}: " + ", ".join(invalid_fields)
        )


def persist_summary(path: Path, summary: dict[str, Any], *, replace: bool) -> None:
    existing_rows = read_store_rows(path)
    run_id = summary["run_id"]
    retained_rows = [row for row in existing_rows if row.get("run_id") != run_id]
    retained_rows.append(summary)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        for row in retained_rows
    )
    path.write_text(rendered, encoding="utf-8")


def assert_summary_store_accepts(path: Path, run_id: str, *, replace: bool) -> None:
    existing_rows = read_store_rows(path)
    duplicate_found = any(row.get("run_id") == run_id for row in existing_rows)
    if duplicate_found and not replace:
        raise SummaryError(
            f"summary store already contains run_id {run_id!r}; use --replace to update it"
        )


def read_store_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SummaryError(
                f"summary store contains invalid JSON on line {line_number}: {path}"
            ) from exc
        if not isinstance(row, dict):
            raise SummaryError(
                f"summary store line {line_number} is not a JSON object: {path}"
            )
        rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_pricing_table(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    prices = payload.get("prices")
    if not isinstance(prices, list):
        raise SummaryError(f"pricing table does not contain a prices array: {path}")
    return [entry for entry in prices if isinstance(entry, dict)]


def lookup_hourly_price(
    *,
    pricing_table: list[dict[str, Any]] | None,
    cloud_provider: str,
    region: str | None,
    machine_type: str,
    pricing_model: str,
) -> float | None:
    if not pricing_table:
        return None
    for entry in pricing_table:
        if (
            str(entry.get("cloud_provider")) == cloud_provider
            and str(entry.get("region")) == str(region)
            and str(entry.get("machine_type")) == machine_type
            and str(entry.get("pricing_model")) == pricing_model
        ):
            return number_or_none(entry.get("hourly_usd"))
    return None


def benchmark_compute_cost(
    *, node_hourly_price_usd: float | None, node_count: int, duration_seconds: int | None
) -> float | None:
    if node_hourly_price_usd is None or duration_seconds is None:
        return None
    return round(node_hourly_price_usd * node_count * duration_seconds / 3600, 8)


def cost_per_1m_requests(
    *, compute_cost_usd: float | None, request_success_count: int | None
) -> float | None:
    if compute_cost_usd is None or request_success_count is None or request_success_count <= 0:
        return None
    return round(compute_cost_usd / request_success_count * 1_000_000, 8)


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def metric_value(metrics: dict[str, Any], metric_name: str, aggregate: str) -> float | None:
    value = metrics.get(metric_name, {}).get(aggregate)
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def bytes_to_gb(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / BYTES_PER_GB, 6)


def seconds_to_ms(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * MS_PER_SECOND, 6)


def summary_status(summary: dict[str, Any]) -> str:
    if (
        summary.get("missing_metrics")
        or summary.get("empty_metrics")
        or summary.get("invalid_metric_samples")
    ):
        return "partial"
    if any(summary.get(field) is None for field in REQUIRED_DERIVED_FIELDS):
        return "partial"
    if summary.get("metrics_coverage_ratio", 0) < 1:
        return "partial"
    return "complete"


def duration_seconds(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    start_dt = parse_timestamp(start)
    end_dt = parse_timestamp(end)
    if not start_dt or not end_dt or end_dt <= start_dt:
        return None
    return int((end_dt - start_dt).total_seconds())


def normalize_timestamp(value: Any) -> str | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def clean_required_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


if __name__ == "__main__":
    raise SystemExit(main())
