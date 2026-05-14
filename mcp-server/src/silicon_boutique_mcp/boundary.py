"""Abstract ports for the MCP service boundary.

The interfaces in this module intentionally describe what the MCP layer needs
without binding it to GitHub Actions, bigquery, Terraform, Helm, or automation
script internals.
"""

from __future__ import annotations

from typing import Protocol

from silicon_boutique_mcp.models import (
    BenchmarkRunRequest,
    BenchmarkSummaryReference,
    RunIdentity,
    WorkflowTrace,
)


class BenchmarkRunController(Protocol):
    """Port for benchmark run control behind the MCP boundary."""

    def trigger_benchmark_run(self, request: BenchmarkRunRequest) -> RunIdentity:
        """Start a benchmark run and return its external identity."""
        ...

    def get_benchmark_status(self, run_id: str) -> WorkflowTrace:
        """Return benchmark status.


        Args:
            run_id: run ID (str) used by this operation.

        Returns:
            WorkflowTrace value produced by get benchmark status.
        """
        ...


class BenchmarkHistoryStore(Protocol):
    """Port for historical benchmark summary lookup behind the MCP boundary."""

    def query_historical_metrics(
        self,
        *,
        machine_type: str | None = None,
        processor_family: str | None = None,
        architecture: str | None = None,
        limit: int = 10,
    ) -> list[BenchmarkSummaryReference]:
        """Query historical metrics.


        Args:
            machine_type: machine type (str | None) used by this operation.
            processor_family: processor family (str | None) used by this operation.
            architecture: architecture (str | None) used by this operation.
            limit: limit (int) used by this operation.

        Returns:
            list[BenchmarkSummaryReference] value produced by query historical metrics.
        """
        ...
