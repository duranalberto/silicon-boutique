"""Local fixture-backed adapters for P5.2 contract validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from silicon_boutique_mcp.models import (
    BenchmarkRunRequest,
    BenchmarkRunStatus,
    BenchmarkSummaryReference,
    RunIdentity,
    WorkflowTrace,
)


class WorkflowTraceFixtureAdapter:
    """Read benchmark status data from local workflow trace JSON fixtures."""

    def __init__(self, trace_fixture: Path):
        self.trace_fixture = trace_fixture
        self.records = load_trace_records(trace_fixture)

    def trigger_benchmark_run(self, request: BenchmarkRunRequest) -> RunIdentity:
        raise NotImplementedError("fixture adapter does not trigger benchmark runs")

    def get_benchmark_status(self, run_id: str) -> WorkflowTrace:
        record = find_trace_record(self.records, run_id)
        if record is None:
            return WorkflowTrace(
                identity=RunIdentity(run_id=run_id),
                status=BenchmarkRunStatus.UNKNOWN,
                environment="",
                cloud_provider="",
                region="",
                zone="",
                machine_type="",
                processor_family="",
                architecture="",
            )
        return workflow_trace_from_record(record, run_id)


class SummaryStoreFixtureAdapter:
    """Read historical benchmark summaries from a local NDJSON store."""

    def __init__(self, summary_store: Path):
        self.summary_store = summary_store
        self.rows = load_summary_rows(summary_store)

    def query_historical_metrics(
        self,
        *,
        machine_type: str | None = None,
        processor_family: str | None = None,
        architecture: str | None = None,
        limit: int = 10,
    ) -> list[BenchmarkSummaryReference]:
        matches = []
        for row in self.rows:
            if machine_type is not None and row.get("machine_type") != machine_type:
                continue
            if (
                processor_family is not None
                and row.get("processor_family") != processor_family
            ):
                continue
            if architecture is not None and row.get("architecture") != architecture:
                continue
            matches.append(summary_reference_from_row(row))
            if len(matches) >= limit:
                break
        return matches


def load_trace_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("runs"), list):
        return [record for record in payload["runs"] if isinstance(record, dict)]
    if isinstance(payload, dict):
        return [payload]
    raise ValueError(f"trace fixture must be a JSON object or array: {path}")


def load_summary_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"summary row {line_number} must be a JSON object")
        rows.append(row)
    return rows


def find_trace_record(
    records: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any] | None:
    for record in records:
        if trace_value(record, "run_id") == run_id:
            return record
    return None


def workflow_trace_from_record(record: dict[str, Any], requested_run_id: str) -> WorkflowTrace:
    benchmark = record.get("benchmark") if isinstance(record.get("benchmark"), dict) else {}
    artifacts = record.get("artifacts") if isinstance(record.get("artifacts"), dict) else {}
    teardown = record.get("teardown") if isinstance(record.get("teardown"), dict) else {}
    inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
    run_id = string_or_default(benchmark.get("run_id") or record.get("run_id"), requested_run_id)
    return WorkflowTrace(
        identity=RunIdentity(
            run_id=run_id,
            external_run_id=string_or_none(record.get("external_run_id")),
            external_run_url=string_or_none(record.get("external_run_url")),
        ),
        status=trace_status(record),
        environment=string_or_default(benchmark.get("environment") or record.get("environment")),
        cloud_provider=string_or_default(
            benchmark.get("cloud_provider") or record.get("cloud_provider")
        ),
        region=string_or_default(benchmark.get("region") or record.get("region")),
        zone=string_or_default(benchmark.get("zone") or record.get("zone")),
        machine_type=string_or_default(benchmark.get("machine_type") or record.get("machine_type")),
        processor_family=string_or_default(
            benchmark.get("processor_family") or record.get("processor_family")
        ),
        architecture=string_or_default(benchmark.get("architecture") or record.get("architecture")),
        node_count=int_or_none(benchmark.get("node_count") or record.get("node_count")),
        pricing_model=string_or_none(
            benchmark.get("pricing_model") or record.get("pricing_model")
        ),
        cpu_platform=string_or_none(
            benchmark.get("cpu_platform") or record.get("cpu_platform")
        ),
        benchmark_start=string_or_none(
            benchmark.get("benchmark_start") or record.get("benchmark_start")
        ),
        benchmark_end=string_or_none(
            benchmark.get("benchmark_end") or record.get("benchmark_end")
        ),
        summary_artifact_name=string_or_none(
            artifacts.get("artifact_name") or record.get("summary_artifact_name")
        ),
        summary_path=string_or_none(artifacts.get("summary_path") or record.get("summary_path")),
        summary_store_path=string_or_none(
            artifacts.get("summary_store_path") or record.get("summary_store_path")
        ),
        teardown_succeeded=optional_bool(
            teardown.get("destroy_succeeded") or record.get("teardown_succeeded")
        ),
        failure_stage=string_or_none(inputs.get("failure_stage") or record.get("failure_stage")),
    )


def trace_value(record: dict[str, Any], field_name: str) -> str | None:
    benchmark = record.get("benchmark") if isinstance(record.get("benchmark"), dict) else {}
    value = record.get(field_name) or benchmark.get(field_name)
    return string_or_none(value)


def trace_status(record: dict[str, Any]) -> BenchmarkRunStatus:
    explicit_status = trace_value(record, "status")
    if explicit_status:
        try:
            return BenchmarkRunStatus(explicit_status)
        except ValueError:
            return BenchmarkRunStatus.UNKNOWN

    inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
    failure_stage = trace_value(record, "failure_stage") or string_or_none(
        inputs.get("failure_stage")
    )
    if failure_stage and failure_stage != "none":
        return BenchmarkRunStatus.FAILED

    benchmark_start = trace_value(record, "benchmark_start")
    benchmark_end = trace_value(record, "benchmark_end")
    if benchmark_end:
        teardown = record.get("teardown") if isinstance(record.get("teardown"), dict) else {}
        teardown_succeeded = optional_bool(
            teardown.get("destroy_succeeded") or record.get("teardown_succeeded")
        )
        if teardown_succeeded is False:
            return BenchmarkRunStatus.FAILED
        return BenchmarkRunStatus.COMPLETED
    if benchmark_start:
        return BenchmarkRunStatus.RUNNING
    return BenchmarkRunStatus.QUEUED


def summary_reference_from_row(row: dict[str, Any]) -> BenchmarkSummaryReference:
    return BenchmarkSummaryReference(
        run_id=string_or_default(row.get("run_id")),
        machine_type=string_or_default(row.get("machine_type")),
        processor_family=string_or_default(row.get("processor_family")),
        architecture=string_or_default(row.get("architecture")),
        cloud_provider=string_or_default(row.get("cloud_provider")),
        region=string_or_default(row.get("region")),
        zone=string_or_default(row.get("zone")),
        node_count=int_or_none(row.get("node_count")) or 0,
        pricing_model=string_or_default(row.get("pricing_model")),
        summary_status=string_or_default(row.get("summary_status")),
        cpu_platform=string_or_none(row.get("cpu_platform")),
        benchmark_start=string_or_none(row.get("benchmark_start")),
        benchmark_end=string_or_none(row.get("benchmark_end")),
        summary_location=string_or_none(row.get("summary_location")),
        avg_cpu_usage_cores=number_or_none(row.get("avg_cpu_usage_cores")),
        max_cpu_usage_cores=number_or_none(row.get("max_cpu_usage_cores")),
        avg_cpu_utilization_pct=number_or_none(row.get("avg_cpu_utilization_pct")),
        max_cpu_utilization_pct=number_or_none(row.get("max_cpu_utilization_pct")),
        max_memory_used_gb=number_or_none(row.get("max_memory_used_gb")),
        frontend_latency_p50_ms=number_or_none(row.get("frontend_latency_p50_ms")),
        frontend_latency_p95_ms=number_or_none(row.get("frontend_latency_p95_ms")),
        frontend_latency_p99_ms=number_or_none(row.get("frontend_latency_p99_ms")),
        frontend_latency_max_ms=number_or_none(row.get("frontend_latency_max_ms")),
        request_count_total=int_or_none(row.get("request_count_total")),
        request_success_count=int_or_none(row.get("request_success_count")),
        request_failure_count=int_or_none(row.get("request_failure_count")),
        avg_requests_per_second=number_or_none(row.get("avg_requests_per_second")),
        load_concurrent_users=int_or_none(row.get("load_concurrent_users")),
        load_users_per_second=number_or_none(row.get("load_users_per_second")),
        load_profile_source=string_or_none(row.get("load_profile_source")),
        node_hourly_price_usd=number_or_none(row.get("node_hourly_price_usd")),
        benchmark_compute_cost_usd=number_or_none(row.get("benchmark_compute_cost_usd")),
        cost_per_1m_requests_usd=number_or_none(row.get("cost_per_1m_requests_usd")),
        metrics_coverage_ratio=number_or_none(row.get("metrics_coverage_ratio")),
        missing_metrics=tuple(row.get("missing_metrics") or ()),
        empty_metrics=tuple(row.get("empty_metrics") or ()),
    )


def string_or_default(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def string_or_none(value: object) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    return rendered if rendered else None


def number_or_none(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def int_or_none(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None
