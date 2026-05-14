"""MCP SDK stdio server entrypoint for SiliconBoutique."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from silicon_boutique_mcp.bigquery_history import BigQueryHistoryStore
from silicon_boutique_mcp.boundary import BenchmarkHistoryStore, BenchmarkRunController
from silicon_boutique_mcp.fixtures import (
    SummaryStoreFixtureAdapter,
    WorkflowTraceFixtureAdapter,
)
from silicon_boutique_mcp.github_actions import GitHubActionsBenchmarkRunController
from silicon_boutique_mcp.models import BenchmarkRunRequest, HistoricalMetricsQuery
from silicon_boutique_mcp.tools import (
    ToolContractError,
    get_benchmark_status,
    query_historical_metrics,
    response_to_dict,
    trigger_benchmark_run,
    tool_definitions_as_dicts,
)


ADAPTER_MODE_PRODUCTION = "production"
ADAPTER_MODE_FIXTURE = "fixture"


class AdapterResolver:
    """Resolve production or fixture adapters lazily for MCP tool calls."""

    def __init__(
        self,
        *,
        run_controller: BenchmarkRunController | None = None,
        history_store: BenchmarkHistoryStore | None = None,
        adapter_mode: str | None = None,
        env: Mapping[str, str] | None = None,
    ):
        """Initialize the object with the provided configuration.


        Args:
            run_controller: run controller (BenchmarkRunController | None) used by this operation.
            history_store: history store (BenchmarkHistoryStore | None) used by this operation.
            adapter_mode: adapter mode (str | None) used by this operation.
            env: environment (Mapping[str, str] | None) used by this operation.

        Returns:
            None.
        """
        self._run_controller = run_controller
        self._history_store = history_store
        self.env = env if env is not None else os.environ
        self.adapter_mode = (
            adapter_mode
            or self.env.get("SILICON_BOUTIQUE_MCP_ADAPTER_MODE")
            or ADAPTER_MODE_PRODUCTION
        )

    def run_controller(self) -> BenchmarkRunController:
        """Run controller.


        Returns:
            BenchmarkRunController value produced by run controller.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        if self._run_controller is not None:
            return self._run_controller
        if self.adapter_mode == ADAPTER_MODE_FIXTURE:
            path = required_path(self.env, "SILICON_BOUTIQUE_TRACE_FIXTURE")
            self._run_controller = WorkflowTraceFixtureAdapter(path)
            return self._run_controller
        if self.adapter_mode == ADAPTER_MODE_PRODUCTION:
            self._run_controller = GitHubActionsBenchmarkRunController.from_env()
            return self._run_controller
        raise ToolError(f"unsupported MCP adapter mode: {self.adapter_mode}")

    def history_store(self) -> BenchmarkHistoryStore:
        """Compute history store.


        Returns:
            BenchmarkHistoryStore value produced by history store.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        if self._history_store is not None:
            return self._history_store
        if self.adapter_mode == ADAPTER_MODE_FIXTURE:
            path = required_path(self.env, "SILICON_BOUTIQUE_SUMMARY_STORE")
            self._history_store = SummaryStoreFixtureAdapter(path)
            return self._history_store
        if self.adapter_mode == ADAPTER_MODE_PRODUCTION:
            self._history_store = BigQueryHistoryStore.from_env()
            return self._history_store
        raise ToolError(f"unsupported MCP adapter mode: {self.adapter_mode}")

    def trigger_supported(self) -> bool:
        """Trigger supported.


        Returns:
            bool value produced by trigger supported.
        """
        return self.adapter_mode != ADAPTER_MODE_FIXTURE or self._run_controller is not None


def build_mcp_app(
    *,
    run_controller: BenchmarkRunController | None = None,
    history_store: BenchmarkHistoryStore | None = None,
    adapter_mode: str | None = None,
    env: Mapping[str, str] | None = None,
) -> FastMCP:
    """Build mCP app.


    Args:
        run_controller: run controller (BenchmarkRunController | None) used by this operation.
        history_store: history store (BenchmarkHistoryStore | None) used by this operation.
        adapter_mode: adapter mode (str | None) used by this operation.
        env: environment (Mapping[str, str] | None) used by this operation.

    Returns:
        FastMCP value produced by build MCP app.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    resolver = AdapterResolver(
        run_controller=run_controller,
        history_store=history_store,
        adapter_mode=adapter_mode,
        env=env,
    )
    app = FastMCP(
        "silicon-boutique-mcp",
        instructions="Trigger SiliconBoutique benchmarks and query run status/history.",
    )

    @app.tool(
        name="trigger_benchmark_run",
        description=tool_description("trigger_benchmark_run"),
    )
    def trigger_tool(
        cloud_provider: str,
        project_id: str,
        region: str,
        zone: str,
        machine_type: str,
        node_count: int,
        processor_family: str,
        architecture: str,
        concurrent_users: int,
        users_per_second: int,
        test_duration: str,
        pricing_model: str = "spot",
        cpu_platform: str | None = None,
    ) -> dict[str, object]:
        """Trigger tool.


        Args:
            cloud_provider: cloud provider (str) used by this operation.
            project_id: project ID (str) used by this operation.
            region: region (str) used by this operation.
            zone: zone (str) used by this operation.
            machine_type: machine type (str) used by this operation.
            node_count: node count (int) used by this operation.
            processor_family: processor family (str) used by this operation.
            architecture: architecture (str) used by this operation.
            concurrent_users: concurrent users (int) used by this operation.
            users_per_second: users per second (int) used by this operation.
            test_duration: test duration (str) used by this operation.
            pricing_model: pricing model (str) used by this operation.
            cpu_platform: CPU platform (str | None) used by this operation.

        Returns:
            dict[str, object] value produced by trigger tool.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        if resolver.adapter_mode == ADAPTER_MODE_FIXTURE and run_controller is None:
            raise ToolError("fixture adapter mode does not support trigger_benchmark_run")
        return mcp_tool_result(
            lambda: trigger_benchmark_run(
                BenchmarkRunRequest(
                    cloud_provider=cloud_provider,
                    project_id=project_id,
                    region=region,
                    zone=zone,
                    machine_type=machine_type,
                    node_count=node_count,
                    processor_family=processor_family,
                    architecture=architecture,
                    concurrent_users=concurrent_users,
                    users_per_second=users_per_second,
                    test_duration=test_duration,
                    pricing_model=pricing_model,
                    cpu_platform=cpu_platform,
                ),
                resolver.run_controller(),
            )
        )

    @app.tool(
        name="get_benchmark_status",
        description=tool_description("get_benchmark_status"),
    )
    def status_tool(run_id: str) -> dict[str, object]:
        """Compute status tool.


        Args:
            run_id: run ID (str) used by this operation.

        Returns:
            dict[str, object] value produced by status tool.
        """
        return mcp_tool_result(
            lambda: get_benchmark_status(run_id, resolver.run_controller())
        )

    @app.tool(
        name="query_historical_metrics",
        description=tool_description("query_historical_metrics"),
    )
    def history_tool(
        machine_type: str | None = None,
        processor_family: str | None = None,
        architecture: str | None = None,
        limit: int = 10,
    ) -> dict[str, object]:
        """Compute history tool.


        Args:
            machine_type: machine type (str | None) used by this operation.
            processor_family: processor family (str | None) used by this operation.
            architecture: architecture (str | None) used by this operation.
            limit: limit (int) used by this operation.

        Returns:
            dict[str, object] value produced by history tool.
        """
        return mcp_tool_result(
            lambda: query_historical_metrics(
                HistoricalMetricsQuery(
                    machine_type=machine_type,
                    processor_family=processor_family,
                    architecture=architecture,
                    limit=limit,
                ),
                resolver.history_store(),
            )
        )

    return app


def mcp_tool_result(callback) -> dict[str, object]:
    """Compute mCP tool result.


    Args:
        callback: callback used by this operation.

    Returns:
        dict[str, object] value produced by mCP tool result.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        return response_to_dict(callback())
    except (ToolContractError, OSError, ValueError, NotImplementedError) as exc:
        raise ToolError(safe_error_message(exc)) from exc


def tool_description(name: str) -> str:
    """Compute tool description.


    Args:
        name: name (str) used by this operation.

    Returns:
        str value produced by tool description.
    """
    for definition in tool_definitions_as_dicts():
        if definition["name"] == name:
            return str(definition["description"])
    return ""


def safe_error_message(exc: BaseException) -> str:
    """Compute safe error message.


    Args:
        exc: exc (BaseException) used by this operation.

    Returns:
        str value produced by safe error message.
    """
    message = str(exc) or exc.__class__.__name__
    return message.replace("Authorization", "[redacted]")


def required_path(env: Mapping[str, str], name: str) -> Path:
    """Compute required path.


    Args:
        env: environment (Mapping[str, str]) used by this operation.
        name: name (str) used by this operation.

    Returns:
        Path value produced by required path.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    value = env.get(name, "").strip()
    if not value:
        raise ToolError(f"{name} is required for fixture adapter mode")
    return Path(value)


def registered_tool_names(app: FastMCP) -> set[str]:
    """Compute registered tool names.


    Args:
        app: app (FastMCP) used by this operation.

    Returns:
        set[str] value produced by registered tool names.
    """
    return set(getattr(app._tool_manager, "_tools").keys())  # noqa: SLF001


def main() -> None:
    """Run the command-line entrypoint.


    Returns:
        None.
    """
    build_mcp_app().run(transport="stdio")


if __name__ == "__main__":
    main()
