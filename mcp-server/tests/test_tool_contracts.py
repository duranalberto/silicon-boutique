"""Tests for test tool contracts."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = REPO_ROOT / "mcp-server" / "src"
sys.path.insert(0, str(MCP_SRC))

from silicon_boutique_mcp.fixtures import (  # noqa: E402
    SummaryStoreFixtureAdapter,
    WorkflowTraceFixtureAdapter,
)
from silicon_boutique_mcp.models import (  # noqa: E402
    BenchmarkRunRequest,
    HistoricalMetricsQuery,
    RunIdentity,
)
from silicon_boutique_mcp.tools import (  # noqa: E402
    ToolContractError,
    get_benchmark_status,
    query_historical_metrics,
    trigger_benchmark_run,
    tool_definitions_as_dicts,
)


class ToolContractTest(unittest.TestCase):
    """Unit tests covering tool Contract behavior.
    """
    def env(self):
        """Compute environment.


        Returns:
            Result produced by environment.
        """
        return {**os.environ, "PYTHONPATH": str(MCP_SRC)}

    def write_trace_fixture(self, tmpdir):
        """Write trace fixture.


        Args:
            tmpdir: tmpdir used by this operation.

        Returns:
            Result produced by write trace fixture.
        """
        path = Path(tmpdir) / "workflow-traces.json"
        payload = {
            "runs": [
                {
                    "run_id": "queued-run",
                    "status": "queued",
                    "environment": "gcp",
                    "cloud_provider": "gcp",
                    "machine_type": "e2-standard-4",
                    "processor_family": "e2",
                    "architecture": "x86_64",
                },
                {
                    "benchmark": {
                        "run_id": "running-run",
                        "environment": "gcp",
                        "cloud_provider": "gcp",
                        "machine_type": "c3-standard-4",
                        "processor_family": "c3",
                        "architecture": "x86_64",
                        "benchmark_start": "2026-05-07T12:00:00Z",
                    }
                },
                {
                    "benchmark": {
                        "run_id": "completed-run",
                        "environment": "gcp",
                        "cloud_provider": "gcp",
                        "machine_type": "t2a-standard-4",
                        "processor_family": "t2a",
                        "architecture": "arm64",
                        "benchmark_start": "2026-05-07T12:00:00Z",
                        "benchmark_end": "2026-05-07T12:20:00Z",
                    },
                    "artifacts": {
                        "artifact_name": "benchmark-gha-1-1",
                        "summary_path": "artifacts/benchmark-summary.json",
                        "summary_store_path": "artifacts/benchmark-summaries.ndjson",
                    },
                    "teardown": {"destroy_succeeded": "true"},
                    "inputs": {"failure_stage": "none"},
                },
                {
                    "benchmark": {
                        "run_id": "failed-run",
                        "environment": "gcp",
                        "cloud_provider": "gcp",
                        "machine_type": "c3-standard-4",
                        "processor_family": "c3",
                        "architecture": "x86_64",
                        "benchmark_start": "2026-05-07T12:00:00Z",
                    },
                    "inputs": {"failure_stage": "before_extract"},
                },
            ]
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_summary_store(self, tmpdir, rows):
        """Write summary store.


        Args:
            tmpdir: tmpdir used by this operation.
            rows: rows used by this operation.

        Returns:
            Result produced by write summary store.
        """
        path = Path(tmpdir) / "benchmark-summaries.ndjson"
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        return path

    def summary_rows(self):
        """Compute summary rows.


        Returns:
            Result produced by summary rows.
        """
        return [
            {
                "run_id": "run-a",
                "namespace": "run-a",
                "environment": "gcp",
                "cloud_provider": "gcp",
                "region": "us-central1",
                "zone": "us-central1-a",
                "machine_type": "c3-standard-4",
                "processor_family": "c3",
                "cpu_platform": "intel-sapphire-rapids",
                "architecture": "x86_64",
                "node_count": 1,
                "pricing_model": "spot",
                "benchmark_start": "2026-05-07T12:00:00Z",
                "benchmark_end": "2026-05-07T12:20:00Z",
                "summary_status": "complete",
                "avg_cpu_usage_cores": 2.1,
                "max_memory_used_gb": 1.5,
                "frontend_latency_p99_ms": 145.0,
                "cost_per_1m_requests_usd": 0.42,
                "metrics_coverage_ratio": 1.0,
                "missing_metrics": [],
                "empty_metrics": [],
            },
            {
                "run_id": "run-b",
                "namespace": "run-b",
                "environment": "gcp",
                "cloud_provider": "gcp",
                "region": "us-central1",
                "zone": "us-central1-a",
                "machine_type": "t2a-standard-4",
                "processor_family": "t2a",
                "cpu_platform": None,
                "architecture": "arm64",
                "node_count": 1,
                "pricing_model": "spot",
                "benchmark_start": "2026-05-07T13:00:00Z",
                "benchmark_end": "2026-05-07T13:20:00Z",
                "summary_status": "partial",
                "frontend_latency_p99_ms": 180.0,
                "metrics_coverage_ratio": 0.9,
                "missing_metrics": ["cpu_usage_cores"],
                "empty_metrics": [],
            },
        ]

    def benchmark_request(self, **overrides):
        """Compute benchmark request.


        Args:
            overrides: overrides used by this operation.

        Returns:
            Result produced by benchmark request.
        """
        values = {
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
            "pricing_model": "spot",
        }
        values.update(overrides)
        return BenchmarkRunRequest(**values)

    def test_tool_registry_lists_p5_2_operations(self):
        """Verify tool registry lists p5 2 operations.


        Returns:
            None.
        """
        tool_names = {tool["name"] for tool in tool_definitions_as_dicts()}

        self.assertEqual(
            tool_names,
            {
                "trigger_benchmark_run",
                "get_benchmark_status",
                "query_historical_metrics",
            },
        )

    def test_trigger_benchmark_run_validates_and_delegates(self):
        """Verify trigger benchmark run validates and delegates.


        Returns:
            None.
        """
        controller = RecordingRunController()

        identity = trigger_benchmark_run(self.benchmark_request(), controller)

        self.assertEqual(identity.run_id, "gha-123-1")
        self.assertEqual(controller.requests[0].machine_type, "c3-standard-4")

    def test_invalid_trigger_requests_fail_validation(self):
        """Verify invalid trigger requests fail validation.


        Returns:
            None.
        """
        invalid_requests = [
            self.benchmark_request(cloud_provider="aws"),
            self.benchmark_request(project_id="   "),
            self.benchmark_request(architecture="x86"),
            self.benchmark_request(pricing_model="preemptible"),
            self.benchmark_request(node_count=0),
            self.benchmark_request(concurrent_users=False),
            self.benchmark_request(users_per_second=-1),
            self.benchmark_request(test_duration="0m"),
            self.benchmark_request(test_duration="soon"),
        ]
        for request in invalid_requests:
            with self.subTest(request=request):
                with self.assertRaises(ToolContractError):
                    trigger_benchmark_run(request, RecordingRunController())

    def test_status_lookup_returns_fixture_status_cases(self):
        """Verify status lookup returns fixture status cases.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = WorkflowTraceFixtureAdapter(self.write_trace_fixture(tmpdir))

            expected = {
                "queued-run": "queued",
                "running-run": "running",
                "completed-run": "completed",
                "failed-run": "failed",
                "missing-run": "unknown",
            }
            for run_id, status in expected.items():
                response = get_benchmark_status(run_id, adapter)
                self.assertEqual(response.status, status)
                self.assertEqual(response.run_id, run_id)

    def test_blank_run_id_fails_validation(self):
        """Verify blank run ID fails validation.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = WorkflowTraceFixtureAdapter(self.write_trace_fixture(tmpdir))

            with self.assertRaises(ToolContractError):
                get_benchmark_status("   ", adapter)

    def test_history_query_filters_by_machine_metadata(self):
        """Verify history query filters by machine metadata.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SummaryStoreFixtureAdapter(
                self.write_summary_store(tmpdir, self.summary_rows())
            )

            response = query_historical_metrics(
                HistoricalMetricsQuery(
                    machine_type="t2a-standard-4",
                    processor_family="t2a",
                    architecture="arm64",
                ),
                store,
            )

            self.assertEqual(len(response.results), 1)
            self.assertEqual(response.results[0].run_id, "run-b")
            self.assertEqual(response.results[0].region, "us-central1")
            self.assertEqual(response.results[0].zone, "us-central1-a")
            self.assertEqual(response.results[0].node_count, 1)
            self.assertEqual(response.results[0].pricing_model, "spot")
            self.assertIsNone(response.results[0].cpu_platform)
            self.assertEqual(response.results[0].frontend_latency_p99_ms, 180.0)
            self.assertEqual(response.results[0].missing_metrics, ("cpu_usage_cores",))

    def test_empty_history_returns_valid_empty_response(self):
        """Verify empty history returns valid empty response.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SummaryStoreFixtureAdapter(self.write_summary_store(tmpdir, []))

            response = query_historical_metrics(HistoricalMetricsQuery(), store)

            self.assertEqual(response.results, ())
            self.assertEqual(response.query.limit, 10)

    def test_invalid_history_query_fails_validation(self):
        """Verify invalid history query fails validation.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SummaryStoreFixtureAdapter(
                self.write_summary_store(tmpdir, self.summary_rows())
            )

            with self.assertRaises(ToolContractError):
                query_historical_metrics(HistoricalMetricsQuery(limit=0), store)

            with self.assertRaises(ToolContractError):
                query_historical_metrics(
                    HistoricalMetricsQuery(machine_type="   "),
                    store,
                )

    def test_cli_tools_status_and_history_emit_json(self):
        """Verify cLI tools status and history emit JSON.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_fixture = self.write_trace_fixture(tmpdir)
            summary_store = self.write_summary_store(tmpdir, self.summary_rows())

            tools_result = subprocess.run(
                [sys.executable, "-m", "silicon_boutique_mcp", "--tools"],
                cwd=REPO_ROOT,
                env=self.env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(tools_result.returncode, 0, tools_result.stderr)
            self.assertEqual(
                {tool["name"] for tool in json.loads(tools_result.stdout)},
                {
                    "trigger_benchmark_run",
                    "get_benchmark_status",
                    "query_historical_metrics",
                },
            )

            status_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "silicon_boutique_mcp",
                    "status",
                    "--run-id",
                    "completed-run",
                    "--trace-fixture",
                    str(trace_fixture),
                ],
                cwd=REPO_ROOT,
                env=self.env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            self.assertEqual(json.loads(status_result.stdout)["status"], "completed")

            history_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "silicon_boutique_mcp",
                    "history",
                    "--summary-store",
                    str(summary_store),
                    "--architecture",
                    "x86_64",
                    "--limit",
                    "1",
                ],
                cwd=REPO_ROOT,
                env=self.env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(history_result.returncode, 0, history_result.stderr)
            history_payload = json.loads(history_result.stdout)
            self.assertEqual(len(history_payload["results"]), 1)
            self.assertEqual(history_payload["results"][0]["run_id"], "run-a")

    def test_cli_history_uses_bigquery_when_summary_store_is_omitted(self):
        """Verify cLI history uses BigQuery when summary store is omitted.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bq = Path(tmpdir) / "fake-bq.py"
            rows = [self.summary_rows()[0]]
            fake_bq.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                f"print(json.dumps({rows!r}))\n",
                encoding="utf-8",
            )
            fake_bq.chmod(0o755)
            env = {
                **self.env(),
                "SILICON_BOUTIQUE_BIGQUERY_PROJECT_ID": "example-project",
                "SILICON_BOUTIQUE_BQ_COMMAND": str(fake_bq),
            }

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "silicon_boutique_mcp",
                    "history",
                    "--machine-type",
                    "c3-standard-4",
                    "--limit",
                    "1",
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["results"][0]["run_id"], "run-a")


class RecordingRunController:
    """Unit tests covering recording Run Controller behavior.
    """
    def __init__(self):
        """Initialize the object with the provided configuration.


        Returns:
            None.
        """
        self.requests = []

    def trigger_benchmark_run(self, request):
        """Trigger benchmark run.


        Args:
            request: request used by this operation.

        Returns:
            Result produced by trigger benchmark run.
        """
        self.requests.append(request)
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
            None.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        raise NotImplementedError


if __name__ == "__main__":
    unittest.main()
