"""Boundary-only data models for future SiliconBoutique MCP tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class BenchmarkRunStatus(StrEnum):
    """High-level benchmark run status values exposed across the boundary."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Stable identifiers for a benchmark run."""

    run_id: str
    external_run_id: str | None = None
    external_run_url: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkRunRequest:
    """Future-facing benchmark request metadata.

    This mirrors the workflow inputs at a boundary level while leaving the
    eventual workflow-dispatch adapter responsible for GitHub-specific details.
    """

    cloud_provider: str
    project_id: str
    region: str
    zone: str
    machine_type: str
    node_count: int
    processor_family: str
    architecture: str
    concurrent_users: int
    users_per_second: int
    test_duration: str


@dataclass(frozen=True, slots=True)
class WorkflowTrace:
    """Non-secret trace metadata returned for status checks."""

    identity: RunIdentity
    status: BenchmarkRunStatus
    environment: str
    cloud_provider: str
    machine_type: str
    processor_family: str
    architecture: str
    benchmark_start: str | None = None
    benchmark_end: str | None = None
    summary_artifact_name: str | None = None
    summary_path: str | None = None
    summary_store_path: str | None = None
    teardown_succeeded: bool | None = None
    failure_stage: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkSummaryReference:
    """Reference to a stored benchmark summary row or artifact."""

    run_id: str
    machine_type: str
    processor_family: str
    architecture: str
    cloud_provider: str
    summary_status: str
    benchmark_start: str | None = None
    benchmark_end: str | None = None
    summary_location: str | None = None
    avg_cpu_usage_cores: float | None = None
    max_cpu_usage_cores: float | None = None
    avg_cpu_utilization_pct: float | None = None
    max_memory_used_gb: float | None = None
    frontend_latency_p50_ms: float | None = None
    frontend_latency_p95_ms: float | None = None
    frontend_latency_p99_ms: float | None = None
    frontend_latency_max_ms: float | None = None
    cost_per_1m_requests_usd: float | None = None
    metrics_coverage_ratio: float | None = None
    missing_metrics: tuple[str, ...] = field(default_factory=tuple)
    empty_metrics: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GetBenchmarkStatusRequest:
    """Input contract for the benchmark status operation."""

    run_id: str


@dataclass(frozen=True, slots=True)
class GetBenchmarkStatusResponse:
    """Output contract for the benchmark status operation."""

    run_id: str
    status: BenchmarkRunStatus
    trace: WorkflowTrace

    def to_dict(self) -> dict[str, Any]:
        """Render the response as JSON-serializable data."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HistoricalMetricsQuery:
    """Input contract for historical benchmark summary lookup."""

    machine_type: str | None = None
    processor_family: str | None = None
    architecture: str | None = None
    limit: int = 10


@dataclass(frozen=True, slots=True)
class HistoricalMetricsResponse:
    """Output contract for historical benchmark summary lookup."""

    query: HistoricalMetricsQuery
    results: tuple[BenchmarkSummaryReference, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Render the response as JSON-serializable data."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BoundaryCapability:
    """Named planned capability for the MCP boundary."""

    name: str
    description: str
    readiness: str = "planned"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """MCP-shaped tool contract metadata."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    readiness: str = "contract_ready"

    def to_dict(self) -> dict[str, Any]:
        """Render the tool definition as JSON-serializable data."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BoundaryManifest:
    """Discoverable manifest for the current boundary scaffold."""

    service_name: str
    boundary_version: str
    capabilities: tuple[BoundaryCapability, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Render the manifest as JSON-serializable data."""
        return asdict(self)
