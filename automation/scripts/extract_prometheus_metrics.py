#!/usr/bin/env python3
"""Extract structured SiliconBoutique benchmark metrics from Prometheus."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


QUERY_RANGE_PATH = "/api/v1/query_range"


@dataclass(frozen=True)
class MetricSpec:
    output_name: str
    query: str
    unit: str
    aggregations: tuple[str, ...]
    required: bool = True


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        output_name="cpu_usage_cores",
        query="silicon_boutique:workload_cpu_usage_cores:rate5m",
        unit="cores",
        aggregations=("avg", "max"),
    ),
    MetricSpec(
        output_name="memory_working_set_bytes",
        query="silicon_boutique:workload_memory_working_set_bytes",
        unit="bytes",
        aggregations=("avg", "max"),
    ),
    MetricSpec(
        output_name="cpu_throttling_ratio",
        query="silicon_boutique:workload_cpu_throttling_ratio:rate5m",
        unit="ratio",
        aggregations=("avg", "max"),
    ),
    MetricSpec(
        output_name="ready_pods",
        query="silicon_boutique:workload_ready_pods",
        unit="pods",
        aggregations=("min", "avg", "max"),
    ),
    MetricSpec(
        output_name="restarts_total",
        query="silicon_boutique:workload_restarts_total",
        unit="restarts",
        aggregations=("max",),
    ),
    MetricSpec(
        output_name="frontend_probe_latency_seconds",
        query="silicon_boutique:frontend_probe_latency_seconds",
        unit="seconds",
        aggregations=("p50", "p95", "p99", "max"),
    ),
)


class PrometheusError(RuntimeError):
    """Raised when Prometheus returns an unusable response."""


class PrometheusClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def query_range(
        self,
        query: str,
        start: str,
        end: str,
        step: str,
        run_id: str,
        namespace: str,
    ) -> dict[str, Any]:
        scoped_query = add_label_matchers(
            query,
            {"run_id": run_id, "workload_namespace": namespace},
        )
        params = urlencode(
            {
                "query": scoped_query,
                "start": start,
                "end": end,
                "step": step,
            }
        )
        url = f"{self.base_url}{QUERY_RANGE_PATH}?{params}"
        with urlopen(url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        validate_prometheus_response(payload, query)
        return payload


class FixturePrometheusClient:
    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir

    def query_range(
        self,
        query: str,
        start: str,
        end: str,
        step: str,
        run_id: str,
        namespace: str,
    ) -> dict[str, Any]:
        del start, end, step, run_id, namespace
        fixture_path = self.fixture_dir / f"{slugify(query)}.json"
        if not fixture_path.exists():
            raise PrometheusError(f"missing fixture for query {query!r}: {fixture_path}")
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        validate_prometheus_response(payload, query)
        return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract SiliconBoutique benchmark metrics from Prometheus."
    )
    parser.add_argument("--prometheus-url", help="Base URL for Prometheus.")
    parser.add_argument("--fixture-dir", type=Path, help="Read query responses from fixtures.")
    parser.add_argument("--run-id", required=True, help="Benchmark run ID.")
    parser.add_argument("--namespace", required=True, help="Benchmark workload namespace.")
    parser.add_argument("--start", required=True, help="Benchmark window start timestamp.")
    parser.add_argument("--end", required=True, help="Benchmark window end timestamp.")
    parser.add_argument("--step", default="15s", help="Prometheus query_range step.")
    parser.add_argument("--output", type=Path, help="Write JSON output to this path.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when any required metric is missing, empty, or invalid.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP timeout for live Prometheus queries.",
    )
    args = parser.parse_args()
    if bool(args.prometheus_url) == bool(args.fixture_dir):
        parser.error("provide exactly one of --prometheus-url or --fixture-dir")
    return args


def main() -> int:
    args = parse_args()
    client: PrometheusClient | FixturePrometheusClient
    if args.fixture_dir:
        client = FixturePrometheusClient(args.fixture_dir)
    else:
        client = PrometheusClient(args.prometheus_url, args.timeout_seconds)

    start_dt = parse_timestamp(args.start)
    end_dt = parse_timestamp(args.end)
    if end_dt <= start_dt:
        raise SystemExit("--end must be later than --start")

    step_seconds = parse_duration_seconds(args.step)
    output = extract_metrics(
        client=client,
        run_id=args.run_id,
        namespace=args.namespace,
        start=args.start,
        end=args.end,
        step=args.step,
        step_seconds=step_seconds,
        expected_samples=expected_sample_count(start_dt, end_dt, step_seconds),
    )

    if args.strict and (
        output["quality"]["missing_series"]
        or output["quality"]["empty_series"]
        or output["quality"]["invalid_samples"]
    ):
        print(
            "required metrics are missing, empty, or invalid; see quality fields in output",
            file=sys.stderr,
        )
        return 2

    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def extract_metrics(
    *,
    client: PrometheusClient | FixturePrometheusClient,
    run_id: str,
    namespace: str,
    start: str,
    end: str,
    step: str,
    step_seconds: int,
    expected_samples: int,
) -> dict[str, Any]:
    metrics: dict[str, dict[str, float | int | str | None]] = {}
    missing_series: list[str] = []
    empty_series: list[str] = []
    invalid_samples: dict[str, int] = {}
    sample_counts: list[int] = []

    for spec in METRIC_SPECS:
        payload = client.query_range(spec.query, start, end, step, run_id, namespace)
        series_values, invalid_count = collect_values(payload)
        values = [value for series in series_values for value in series]
        if invalid_count:
            invalid_samples[spec.output_name] = invalid_count
        if not series_values:
            missing_series.append(spec.output_name)
        elif not values:
            empty_series.append(spec.output_name)
        sample_counts.append(len(values))

        metric_output: dict[str, float | int | str | None] = {
            "sample_count": len(values),
            "unit": spec.unit,
        }
        for aggregation in spec.aggregations:
            metric_output[aggregation] = aggregate(values, aggregation)
        metrics[spec.output_name] = metric_output

    min_samples = min(sample_counts) if sample_counts else 0
    coverage_ratio = min(1.0, min_samples / expected_samples) if expected_samples else 0.0

    return {
        "run_id": run_id,
        "namespace": namespace,
        "window": {
            "start": normalize_timestamp(start),
            "end": normalize_timestamp(end),
            "step_seconds": step_seconds,
        },
        "metrics": metrics,
        "quality": {
            "missing_series": missing_series,
            "empty_series": empty_series,
            "invalid_samples": invalid_samples,
            "expected_samples_per_metric": expected_samples,
            "coverage_ratio": round(coverage_ratio, 6),
        },
    }


def add_label_matchers(query: str, matchers: dict[str, str]) -> str:
    matcher_text = ",".join(f'{key}="{escape_label_value(value)}"' for key, value in matchers.items())
    if "{" in query:
        return re.sub(r"\{", "{" + matcher_text + ",", query, count=1)
    return f"{query}{{{matcher_text}}}"


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def collect_values(payload: dict[str, Any]) -> tuple[list[list[float]], int]:
    result = payload.get("data", {}).get("result", [])
    series_values: list[list[float]] = []
    invalid_count = 0
    for series in result:
        values: list[float] = []
        for sample in series.get("values", []):
            if len(sample) != 2:
                invalid_count += 1
                continue
            raw_value = sample[1]
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                invalid_count += 1
                continue
            if not math.isfinite(value):
                invalid_count += 1
                continue
            values.append(value)
        series_values.append(values)
    return series_values, invalid_count


def aggregate(values: list[float], aggregation: str) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    if aggregation == "avg":
        return round(sum(values) / len(values), 6)
    if aggregation == "min":
        return round(sorted_values[0], 6)
    if aggregation == "max":
        return round(sorted_values[-1], 6)
    if aggregation == "p50":
        return round(percentile(sorted_values, 0.50), 6)
    if aggregation == "p95":
        return round(percentile(sorted_values, 0.95), 6)
    if aggregation == "p99":
        return round(percentile(sorted_values, 0.99), 6)
    raise ValueError(f"unsupported aggregation: {aggregation}")


def percentile(sorted_values: list[float], quantile: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[int(index)]
    fraction = index - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def validate_prometheus_response(payload: dict[str, Any], query: str) -> None:
    if payload.get("status") != "success":
        error = payload.get("error") or payload.get("errorType") or "unknown error"
        raise PrometheusError(f"Prometheus query failed for {query!r}: {error}")
    result_type = payload.get("data", {}).get("resultType")
    if result_type != "matrix":
        raise PrometheusError(
            f"Prometheus query for {query!r} returned {result_type!r}, expected 'matrix'"
        )


def parse_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"(\d+)(ms|s|m|h)?", value)
    if not match:
        raise SystemExit(f"invalid --step duration: {value}")
    amount = int(match.group(1))
    unit = match.group(2) or "s"
    multipliers = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    seconds = amount * multipliers[unit]
    if seconds < 1:
        raise SystemExit("--step must be at least 1 second")
    return int(seconds)


def parse_timestamp(value: str) -> datetime:
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return datetime.fromtimestamp(float(value), timezone.utc)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SystemExit(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_timestamp(value: str) -> str:
    return parse_timestamp(value).isoformat().replace("+00:00", "Z")


def expected_sample_count(start: datetime, end: datetime, step_seconds: int) -> int:
    duration_seconds = (end - start).total_seconds()
    return int(math.floor(duration_seconds / step_seconds)) + 1


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


if __name__ == "__main__":
    raise SystemExit(main())
