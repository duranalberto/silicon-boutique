"""Tests for test mcp app."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = REPO_ROOT / "mcp-server" / "src"
sys.path.insert(0, str(MCP_SRC))

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.server.fastmcp.exceptions import ToolError

    from silicon_boutique_mcp.mcp_app import build_mcp_app, registered_tool_names

    MCP_AVAILABLE = True
except ModuleNotFoundError:
    MCP_AVAILABLE = False

from silicon_boutique_mcp.models import (  # noqa: E402
    BenchmarkRunStatus,
    BenchmarkSummaryReference,
    RunIdentity,
    WorkflowTrace,
)
from silicon_boutique_mcp.tools import tool_definitions_as_dicts  # noqa: E402


@unittest.skipUnless(MCP_AVAILABLE, "mcp SDK is not installed")
class McpAppTest(unittest.TestCase):
    """Unit tests covering mCP App behavior.
    """
    def test_registered_tool_names_match_contract_registry(self):
        """Verify registered tool names match contract registry.


        Returns:
            None.
        """
        app = build_mcp_app(
            run_controller=FakeRunController(),
            history_store=FakeHistoryStore(),
        )

        self.assertEqual(
            registered_tool_names(app),
            {tool["name"] for tool in tool_definitions_as_dicts()},
        )

    def test_list_tools_preserves_contract_names_and_descriptions(self):
        """Verify list tools preserves contract names and descriptions.


        Returns:
            None.
        """
        async def scenario():
            """Compute scenario.


            Returns:
                None.
            """
            app = build_mcp_app(
                run_controller=FakeRunController(),
                history_store=FakeHistoryStore(),
            )
            tools = await app.list_tools()
            by_name = {tool.name: tool for tool in tools}
            contracts = {tool["name"]: tool for tool in tool_definitions_as_dicts()}

            self.assertEqual(set(by_name), set(contracts))
            for name, contract in contracts.items():
                self.assertEqual(by_name[name].description, contract["description"])

        asyncio.run(scenario())

    def test_call_tools_return_contract_shaped_json(self):
        """Verify call tools return contract shaped JSON.


        Returns:
            None.
        """
        async def scenario():
            """Compute scenario.


            Returns:
                None.
            """
            app = build_mcp_app(
                run_controller=FakeRunController(),
                history_store=FakeHistoryStore(),
            )

            trigger = await app.call_tool(
                "trigger_benchmark_run",
                {
                    "cloud_provider": "gcp",
                    "project_id": "test-project",
                    "region": "us-central1",
                    "zone": "us-central1-a",
                    "machine_type": "c3-standard-4",
                    "node_count": 1,
                    "processor_family": "c3",
                    "architecture": "x86_64",
                    "concurrent_users": 10,
                    "users_per_second": 1,
                    "test_duration": "20m",
                },
            )
            status = await app.call_tool(
                "get_benchmark_status",
                {"run_id": "gha-123-1"},
            )
            history = await app.call_tool(
                "query_historical_metrics",
                {"machine_type": "c3-standard-4", "limit": 1},
            )

            self.assertEqual(json_payload(trigger)["run_id"], "gha-123-1")
            self.assertEqual(json_payload(status)["status"], "running")
            self.assertEqual(json_payload(history)["results"][0]["run_id"], "run-a")

        asyncio.run(scenario())

    def test_invalid_tool_input_returns_tool_error(self):
        """Verify invalid tool input returns tool error.


        Returns:
            None.
        """
        async def scenario():
            """Compute scenario.


            Returns:
                None.
            """
            app = build_mcp_app(
                run_controller=FakeRunController(),
                history_store=FakeHistoryStore(),
            )

            with self.assertRaises(ToolError):
                await app.call_tool(
                    "trigger_benchmark_run",
                    {
                        "cloud_provider": "aws",
                        "project_id": "test-project",
                        "region": "us-central1",
                        "zone": "us-central1-a",
                        "machine_type": "c3-standard-4",
                        "node_count": 1,
                        "processor_family": "c3",
                        "architecture": "x86_64",
                        "concurrent_users": 10,
                        "users_per_second": 1,
                        "test_duration": "20m",
                    },
                )

        asyncio.run(scenario())

    def test_fixture_mode_rejects_trigger_but_serves_status_and_history(self):
        """Verify fixture mode rejects trigger but serves status and history.


        Returns:
            None.
        """
        async def scenario():
            """Compute scenario.


            Returns:
                None.
            """
            with tempfile.TemporaryDirectory() as tmpdir:
                trace_fixture = Path(tmpdir) / "trace.json"
                summary_store = Path(tmpdir) / "summaries.ndjson"
                trace_fixture.write_text(
                    json.dumps(
                        {
                            "run_id": "fixture-run",
                            "status": "completed",
                            "environment": "gcp",
                            "cloud_provider": "gcp",
                            "machine_type": "c3-standard-4",
                            "processor_family": "c3",
                            "architecture": "x86_64",
                        }
                    ),
                    encoding="utf-8",
                )
                summary_store.write_text(
                    json.dumps(summary_row("run-a")) + "\n",
                    encoding="utf-8",
                )
                app = build_mcp_app(
                    adapter_mode="fixture",
                    env={
                        "SILICON_BOUTIQUE_TRACE_FIXTURE": str(trace_fixture),
                        "SILICON_BOUTIQUE_SUMMARY_STORE": str(summary_store),
                    },
                )

                status = await app.call_tool(
                    "get_benchmark_status",
                    {"run_id": "fixture-run"},
                )
                history = await app.call_tool(
                    "query_historical_metrics",
                    {"limit": 1},
                )
                with self.assertRaises(ToolError):
                    await app.call_tool("trigger_benchmark_run", {})

            self.assertEqual(json_payload(status)["status"], "completed")
            self.assertEqual(json_payload(history)["results"][0]["run_id"], "run-a")

        asyncio.run(scenario())

    def test_stdio_process_lists_and_calls_fixture_tools(self):
        """Verify stdio process lists and calls fixture tools.


        Returns:
            None.
        """
        async def scenario():
            """Compute scenario.


            Returns:
                None.
            """
            with tempfile.TemporaryDirectory() as tmpdir:
                trace_fixture = Path(tmpdir) / "trace.json"
                summary_store = Path(tmpdir) / "summaries.ndjson"
                trace_fixture.write_text(
                    json.dumps(
                        {
                            "run_id": "fixture-run",
                            "status": "completed",
                            "environment": "gcp",
                            "cloud_provider": "gcp",
                            "machine_type": "c3-standard-4",
                            "processor_family": "c3",
                            "architecture": "x86_64",
                        }
                    ),
                    encoding="utf-8",
                )
                summary_store.write_text(
                    json.dumps(summary_row("run-a")) + "\n",
                    encoding="utf-8",
                )
                server = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "silicon_boutique_mcp.mcp_app"],
                    env={
                        **os.environ,
                        "PYTHONPATH": str(MCP_SRC),
                        "SILICON_BOUTIQUE_MCP_ADAPTER_MODE": "fixture",
                        "SILICON_BOUTIQUE_TRACE_FIXTURE": str(trace_fixture),
                        "SILICON_BOUTIQUE_SUMMARY_STORE": str(summary_store),
                    },
                )
                async with stdio_client(server) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        status = await session.call_tool(
                            "get_benchmark_status",
                            {"run_id": "fixture-run"},
                        )

                self.assertIn(
                    "get_benchmark_status",
                    {tool.name for tool in tools.tools},
                )
                self.assertEqual(call_result_payload(status)["status"], "completed")

        asyncio.run(scenario())


class FakeRunController:
    """Test double that records run Controller interactions.
    """
    def trigger_benchmark_run(self, request):
        """Trigger benchmark run.


        Args:
            request: request used by this operation.

        Returns:
            Result produced by trigger benchmark run.
        """
        return RunIdentity(
            run_id="gha-123-1",
            external_run_id="123",
            external_run_url="https://github.example/runs/123",
        )

    def get_benchmark_status(self, run_id):
        """Return benchmark status.


        Args:
            run_id: run ID used by this operation.

        Returns:
            Result produced by get benchmark status.
        """
        return WorkflowTrace(
            identity=RunIdentity(run_id=run_id),
            status=BenchmarkRunStatus.RUNNING,
            environment="gcp",
            cloud_provider="gcp",
            region="us-central1",
            zone="us-central1-a",
            machine_type="c3-standard-4",
            processor_family="c3",
            architecture="x86_64",
        )


class FakeHistoryStore:
    """Test double that records history Store interactions.
    """
    def query_historical_metrics(
        self,
        *,
        machine_type=None,
        processor_family=None,
        architecture=None,
        limit=10,
    ):
        """Query historical metrics.


        Args:
            machine_type: machine type used by this operation.
            processor_family: processor family used by this operation.
            architecture: architecture used by this operation.
            limit: limit used by this operation.

        Returns:
            Result produced by query historical metrics.
        """
        return [BenchmarkSummaryReference(**summary_row("run-a"))][:limit]


def json_payload(blocks):
    """Compute jSON payload.


    Args:
        blocks: blocks used by this operation.

    Returns:
        Result produced by jSON payload.
    """
    if isinstance(blocks, tuple):
        if len(blocks) > 1 and isinstance(blocks[1], dict):
            return blocks[1]
        blocks = blocks[0]
    return json.loads(blocks[0].text)


def call_result_payload(result):
    """Compute call result payload.


    Args:
        result: result used by this operation.

    Returns:
        Result produced by call result payload.
    """
    return json.loads(result.content[0].text)


def summary_row(run_id):
    """Compute summary row.


    Args:
        run_id: run ID used by this operation.

    Returns:
        Result produced by summary row.
    """
    return {
        "run_id": run_id,
        "machine_type": "c3-standard-4",
        "processor_family": "c3",
        "architecture": "x86_64",
        "cloud_provider": "gcp",
        "region": "us-central1",
        "zone": "us-central1-a",
        "node_count": 1,
        "pricing_model": "spot",
        "summary_status": "complete",
    }


if __name__ == "__main__":
    unittest.main()
