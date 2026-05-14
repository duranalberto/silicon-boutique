"""MCP-shaped tool contracts and dependency-free operation functions."""

from __future__ import annotations

from dataclasses import asdict

from silicon_boutique_mcp.boundary import BenchmarkHistoryStore, BenchmarkRunController
from silicon_boutique_mcp.models import (
    BenchmarkRunRequest,
    GetBenchmarkStatusResponse,
    HistoricalMetricsQuery,
    HistoricalMetricsResponse,
    RunIdentity,
    ToolDefinition,
)


DEFAULT_HISTORY_LIMIT = 10
MAX_HISTORY_LIMIT = 100


class ToolContractError(ValueError):
    """Raised when a tool request does not satisfy the local contract."""


TRIGGER_BENCHMARK_RUN_TOOL = ToolDefinition(
    name="trigger_benchmark_run",
    description="Dispatch the production GCP benchmark workflow through GitHub Actions.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "cloud_provider",
            "project_id",
            "region",
            "zone",
            "machine_type",
            "node_count",
            "processor_family",
            "architecture",
            "concurrent_users",
            "users_per_second",
            "test_duration",
        ],
        "properties": {
            "cloud_provider": {"type": "string", "const": "gcp"},
            "project_id": {"type": "string", "minLength": 1},
            "region": {"type": "string", "minLength": 1},
            "zone": {"type": "string", "minLength": 1},
            "machine_type": {"type": "string", "minLength": 1},
            "node_count": {"type": "integer", "minimum": 1},
            "processor_family": {"type": "string", "minLength": 1},
            "architecture": {"type": "string", "enum": ["x86_64", "arm64"]},
            "concurrent_users": {"type": "integer", "minimum": 1},
            "users_per_second": {"type": "integer", "minimum": 1},
            "test_duration": {"type": "string", "minLength": 1},
            "pricing_model": {
                "type": "string",
                "enum": ["spot", "on_demand"],
                "default": "spot",
            },
            "cpu_platform": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["run_id"],
        "properties": {
            "run_id": {"type": "string"},
            "external_run_id": {"type": ["string", "null"]},
            "external_run_url": {"type": ["string", "null"]},
        },
    },
    readiness="production_adapter_ready",
)


GET_BENCHMARK_STATUS_TOOL = ToolDefinition(
    name="get_benchmark_status",
    description="Check benchmark status from GitHub Actions run state.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["run_id"],
        "properties": {
            "run_id": {"type": "string", "minLength": 1},
        },
    },
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["run_id", "status", "trace"],
        "properties": {
            "run_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["queued", "running", "completed", "failed", "unknown"],
            },
            "trace": {"type": "object"},
        },
    },
    readiness="production_adapter_ready",
)

QUERY_HISTORICAL_METRICS_TOOL = ToolDefinition(
    name="query_historical_metrics",
    description="Query BigQuery benchmark summary history by machine metadata.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "machine_type": {"type": "string", "minLength": 1},
            "processor_family": {"type": "string", "minLength": 1},
            "architecture": {"type": "string", "minLength": 1},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_HISTORY_LIMIT,
                "default": DEFAULT_HISTORY_LIMIT,
            },
        },
    },
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["query", "results"],
        "properties": {
            "query": {"type": "object"},
            "results": {"type": "array", "items": {"type": "object"}},
        },
    },
    readiness="production_adapter_ready",
)

TOOL_DEFINITIONS = (
    TRIGGER_BENCHMARK_RUN_TOOL,
    GET_BENCHMARK_STATUS_TOOL,
    QUERY_HISTORICAL_METRICS_TOOL,
)


def tool_definitions_as_dicts() -> list[dict[str, object]]:
    """Compute tool definitions as dicts.


    Returns:
        list[dict[str, object]] value produced by tool definitions as dicts.
    """
    return [tool.to_dict() for tool in TOOL_DEFINITIONS]


def get_benchmark_status(
    run_id: str,
    run_controller: BenchmarkRunController,
) -> GetBenchmarkStatusResponse:
    """Execute the status contract against a boundary run controller."""
    cleaned_run_id = require_non_empty_string(run_id, "run_id")
    trace = run_controller.get_benchmark_status(cleaned_run_id)
    return GetBenchmarkStatusResponse(
        run_id=cleaned_run_id,
        status=trace.status,
        trace=trace,
    )


def trigger_benchmark_run(
    request: BenchmarkRunRequest,
    run_controller: BenchmarkRunController,
) -> RunIdentity:
    """Execute the benchmark trigger contract against a boundary run controller."""
    validate_benchmark_run_request(request)
    return run_controller.trigger_benchmark_run(request)


def query_historical_metrics(
    query: HistoricalMetricsQuery,
    history_store: BenchmarkHistoryStore,
) -> HistoricalMetricsResponse:
    """Execute the historical query contract against a boundary history store."""
    validate_history_query(query)
    rows = history_store.query_historical_metrics(
        machine_type=clean_optional_string(query.machine_type, "machine_type"),
        processor_family=clean_optional_string(
            query.processor_family,
            "processor_family",
        ),
        architecture=clean_optional_string(query.architecture, "architecture"),
        limit=query.limit,
    )
    return HistoricalMetricsResponse(query=query, results=tuple(rows))


def response_to_dict(response: object) -> dict[str, object]:
    """Compute response to dict.


    Args:
        response: response (object) used by this operation.

    Returns:
        dict[str, object] value produced by response to dict.
    """
    if hasattr(response, "to_dict"):
        return response.to_dict()  # type: ignore[no-any-return]
    return asdict(response)  # type: ignore[arg-type]


def validate_benchmark_run_request(request: BenchmarkRunRequest) -> None:
    """Validate benchmark run request.


    Args:
        request: request (BenchmarkRunRequest) used by this operation.

    Returns:
        None.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    cloud_provider = require_non_empty_string(request.cloud_provider, "cloud_provider")
    if cloud_provider != "gcp":
        raise ToolContractError("cloud_provider must be gcp for P9.1")

    require_non_empty_string(request.project_id, "project_id")
    require_non_empty_string(request.region, "region")
    require_non_empty_string(request.zone, "zone")
    require_non_empty_string(request.machine_type, "machine_type")
    require_non_empty_string(request.processor_family, "processor_family")

    architecture = require_non_empty_string(request.architecture, "architecture")
    if architecture not in {"x86_64", "arm64"}:
        raise ToolContractError("architecture must be x86_64 or arm64")

    pricing_model = require_non_empty_string(request.pricing_model, "pricing_model")
    if pricing_model not in {"spot", "on_demand"}:
        raise ToolContractError("pricing_model must be spot or on_demand")

    require_positive_int(request.node_count, "node_count")
    require_positive_int(request.concurrent_users, "concurrent_users")
    require_positive_int(request.users_per_second, "users_per_second")
    require_duration(request.test_duration, "test_duration")
    clean_optional_string(request.cpu_platform, "cpu_platform")


def validate_history_query(query: HistoricalMetricsQuery) -> None:
    """Validate history query.


    Args:
        query: query (HistoricalMetricsQuery) used by this operation.

    Returns:
        None.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    clean_optional_string(query.machine_type, "machine_type")
    clean_optional_string(query.processor_family, "processor_family")
    clean_optional_string(query.architecture, "architecture")
    if not isinstance(query.limit, int):
        raise ToolContractError("limit must be an integer")
    if query.limit < 1 or query.limit > MAX_HISTORY_LIMIT:
        raise ToolContractError(
            f"limit must be between 1 and {MAX_HISTORY_LIMIT}; got {query.limit}"
        )


def require_non_empty_string(value: str, field_name: str) -> str:
    """Compute require non empty string.


    Args:
        value: value (str) used by this operation.
        field_name: field name (str) used by this operation.

    Returns:
        str value produced by require non empty string.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ToolContractError(f"{field_name} must be a non-empty string")
    return cleaned


def require_positive_int(value: int, field_name: str) -> int:
    """Compute require positive integer.


    Args:
        value: value (int) used by this operation.
        field_name: field name (str) used by this operation.

    Returns:
        int value produced by require positive integer.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolContractError(f"{field_name} must be a positive integer")
    if value < 1:
        raise ToolContractError(f"{field_name} must be a positive integer")
    return value


def require_duration(value: str, field_name: str) -> str:
    """Compute require duration.


    Args:
        value: value (str) used by this operation.
        field_name: field name (str) used by this operation.

    Returns:
        str value produced by require duration.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    cleaned = require_non_empty_string(value, field_name)
    if cleaned[-1] in {"s", "m", "h"}:
        number = cleaned[:-1]
    else:
        number = cleaned
    if not number.isdigit() or int(number) < 1:
        raise ToolContractError(f"{field_name} must be positive seconds, Nm, or Nh")
    return cleaned


def clean_optional_string(value: str | None, field_name: str) -> str | None:
    """Compute clean optional string.


    Args:
        value: value (str | None) used by this operation.
        field_name: field name (str) used by this operation.

    Returns:
        str | None value produced by clean optional string.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ToolContractError(f"{field_name} must be a non-empty string when set")
    return cleaned
