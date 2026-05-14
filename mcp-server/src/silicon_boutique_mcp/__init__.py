"""SiliconBoutique MCP boundary package."""

from silicon_boutique_mcp.boundary import BenchmarkHistoryStore, BenchmarkRunController
from silicon_boutique_mcp.models import (
    BenchmarkRunRequest,
    BenchmarkRunStatus,
    BenchmarkSummaryReference,
    BoundaryCapability,
    BoundaryManifest,
    GetBenchmarkStatusResponse,
    HistoricalMetricsQuery,
    HistoricalMetricsResponse,
    RunIdentity,
    ToolDefinition,
    WorkflowTrace,
)
from silicon_boutique_mcp.server import build_boundary_manifest
from silicon_boutique_mcp.tools import (
    get_benchmark_status,
    query_historical_metrics,
    trigger_benchmark_run,
)

__all__ = [
    "BenchmarkHistoryStore",
    "BenchmarkRunController",
    "BenchmarkRunRequest",
    "BenchmarkRunStatus",
    "BenchmarkSummaryReference",
    "BoundaryCapability",
    "BoundaryManifest",
    "GetBenchmarkStatusResponse",
    "HistoricalMetricsQuery",
    "HistoricalMetricsResponse",
    "RunIdentity",
    "ToolDefinition",
    "WorkflowTrace",
    "build_boundary_manifest",
    "get_benchmark_status",
    "query_historical_metrics",
    "trigger_benchmark_run",
]
