#!/usr/bin/env python3
"""Extract structured SiliconBoutique benchmark metrics from Prometheus.

The script reads either live Prometheus query_range responses or checked-in
fixtures, scopes each query to a benchmark run and namespace, aggregates the
samples defined in ``METRIC_SPECS``, and emits a JSON payload consumed by later
benchmark summary and validation steps.
"""

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

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared.automation import parse_duration_seconds


QUERY_RANGE_PATH = "/api/v1/query_range"


@dataclass(frozen=True)
class MetricSpec:
    """Define one Prometheus metric to extract and aggregate.

    Attributes:
        output_name: Field name used for this metric in the emitted JSON.
        query: PromQL expression or recording rule name to query.
        unit: Human-readable unit attached to the metric output.
        aggregations: Aggregation names to compute from the collected samples.
        required: Whether strict mode should treat missing or empty series as a
            quality failure for this metric.
    """

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
        output_name="cpu_utilization_pct",
        query="silicon_boutique:workload_cpu_utilization_pct",
        unit="percent",
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
    """Container for Prometheus Client state and behavior.
    """

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        """Initialize a live Prometheus client.

        Args:
            base_url: Base URL for the Prometheus server, without the
                ``/api/v1/query_range`` path.
            timeout_seconds: Maximum number of seconds to wait for each HTTP
                request.
        """
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
        """Run a scoped Prometheus range query.

        Args:
            query: PromQL expression or recording rule name to evaluate.
            start: Benchmark window start timestamp accepted by Prometheus.
            end: Benchmark window end timestamp accepted by Prometheus.
            step: Prometheus range query step duration.
            run_id: Benchmark run identifier added as a ``run_id`` matcher.
            namespace: Workload namespace added as a ``workload_namespace``
                matcher.

        Returns:
            Decoded Prometheus JSON response payload.

        Raises:
            PrometheusError: If Prometheus returns a failed response or a result
                type other than ``matrix``.
        """
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
    """Container for fixture Prometheus Client state and behavior.
    """

    def __init__(self, fixture_dir: Path) -> None:
        """Initialize a fixture-backed Prometheus client.

        Args:
            fixture_dir: Directory containing one JSON file per query, named
                with ``slugify(query)`` and a ``.json`` suffix.
        """
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
        """Load and validate a fixture payload for a range query.

        Args:
            query: PromQL expression or recording rule name whose slug selects
                the fixture file.
            start: Ignored benchmark window start timestamp.
            end: Ignored benchmark window end timestamp.
            step: Ignored range query step duration.
            run_id: Ignored benchmark run identifier.
            namespace: Ignored workload namespace.

        Returns:
            Decoded fixture JSON response payload.

        Raises:
            PrometheusError: If the expected fixture file is missing or contains
                an unusable Prometheus response.
        """
        del start, end, step, run_id, namespace
        fixture_path = self.fixture_dir / f"{slugify(query)}.json"
        if not fixture_path.exists():
            raise PrometheusError(f"missing fixture for query {query!r}: {fixture_path}")
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        validate_prometheus_response(payload, query)
        return payload


def parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments.

    Returns:
        Parsed argparse namespace containing either ``prometheus_url`` or
        ``fixture_dir`` plus the benchmark window, run metadata, and output
        options.

    Raises:
        SystemExit: If the user provides invalid CLI arguments.
    """
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
    """Run the command-line entrypoint.

    Returns:
        Process exit code. ``0`` means metrics were extracted successfully;
        ``2`` means strict mode found missing, empty, or invalid required metric
        data.

    Raises:
        SystemExit: If timestamps or duration arguments are invalid.
    """
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

    try:
        step_seconds = parse_duration_seconds(args.step, allow_milliseconds=True)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
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

    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

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
    """Extract and aggregate all configured benchmark metrics.

    Args:
        client: Live or fixture-backed Prometheus client used to retrieve range
            query payloads.
        run_id: Benchmark run identifier included in query label matchers and
            copied into the output payload.
        namespace: Workload namespace included in query label matchers and
            copied into the output payload.
        start: Benchmark window start timestamp.
        end: Benchmark window end timestamp.
        step: Prometheus range query step duration.
        step_seconds: Parsed step duration in seconds.
        expected_samples: Expected sample count for each metric series over the
            benchmark window.

    Returns:
        JSON-serializable metrics payload with run metadata, normalized window
        data, per-metric aggregate values, and quality fields describing missing,
        empty, invalid, and coverage status.
    """
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
    """Add exact-match label selectors to a PromQL query.

    Args:
        query: PromQL expression or recording rule name.
        matchers: Label names and values to inject into the first selector, or
            into a new selector if the query has none.

    Returns:
        Query text with escaped label matchers applied.
    """
    matcher_text = ",".join(f'{key}="{escape_label_value(value)}"' for key, value in matchers.items())
    if "{" in query:
        return re.sub(r"\{", "{" + matcher_text + ",", query, count=1)
    return f"{query}{{{matcher_text}}}"


def escape_label_value(value: str) -> str:
    """Escape a string for use inside a Prometheus label matcher.

    Args:
        value: Raw label value.

    Returns:
        Label value with backslashes and double quotes escaped.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def collect_values(payload: dict[str, Any]) -> tuple[list[list[float]], int]:
    """Collect finite sample values from a Prometheus matrix response.

    Args:
        payload: Decoded Prometheus query_range response.

    Returns:
        A tuple containing one list of float samples per returned series and the
        number of malformed, non-numeric, or non-finite samples skipped.
    """
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
    """Compute one aggregate over a set of sample values.

    Args:
        values: Sample values collected for a metric.
        aggregation: Aggregation name. Supported values are ``avg``, ``min``,
            ``max``, ``p50``, ``p95``, and ``p99``.

    Returns:
        Rounded aggregate value, or ``None`` when no samples are available.

    Raises:
        ValueError: If ``aggregation`` is not supported.
    """
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
    """Calculate an interpolated percentile from sorted samples.

    Args:
        sorted_values: Sample values sorted in ascending order.
        quantile: Desired quantile as a number between ``0`` and ``1``.

    Returns:
        Interpolated percentile value.
    """
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
    """Validate the shape of a Prometheus range-query response.

    Args:
        payload: Decoded Prometheus response payload.
        query: Original query, used only for diagnostic error messages.

    Raises:
        PrometheusError: If Prometheus reported a failure or did not return a
            matrix result.
    """
    if payload.get("status") != "success":
        error = payload.get("error") or payload.get("errorType") or "unknown error"
        raise PrometheusError(f"Prometheus query failed for {query!r}: {error}")
    result_type = payload.get("data", {}).get("resultType")
    if result_type != "matrix":
        raise PrometheusError(
            f"Prometheus query for {query!r} returned {result_type!r}, expected 'matrix'"
        )


def parse_timestamp(value: str) -> datetime:
    """Parse a benchmark timestamp into a UTC datetime.

    Args:
        value: Unix timestamp string or ISO-8601 datetime. Naive ISO values are
            treated as UTC.

    Returns:
        Timezone-aware UTC datetime.

    Raises:
        SystemExit: If ``value`` is not a supported timestamp format.
    """
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
    """Normalize a timestamp to an ISO-8601 UTC string.

    Args:
        value: Unix timestamp string or ISO-8601 datetime.

    Returns:
        ISO-8601 timestamp with a trailing ``Z`` UTC designator.
    """
    return parse_timestamp(value).isoformat().replace("+00:00", "Z")


def expected_sample_count(start: datetime, end: datetime, step_seconds: int) -> int:
    """Calculate expected Prometheus samples for an inclusive query window.

    Args:
        start: Benchmark window start time.
        end: Benchmark window end time.
        step_seconds: Query step duration in seconds.

    Returns:
        Expected number of samples per metric series.
    """
    duration_seconds = (end - start).total_seconds()
    return int(math.floor(duration_seconds / step_seconds)) + 1


def slugify(value: str) -> str:
    """Convert query text into a stable fixture filename stem.

    Args:
        value: Raw query string.

    Returns:
        Lowercase string containing only alphanumeric words separated by
        underscores.
    """
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


if __name__ == "__main__":
    raise SystemExit(main())
