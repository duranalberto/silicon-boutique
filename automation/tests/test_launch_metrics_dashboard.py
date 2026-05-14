"""Tests for test launch metrics dashboard."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "launch_metrics_dashboard.py"
SCHEMA = REPO_ROOT / "automation" / "templates" / "benchmark-summary.schema.json"

sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("launch_metrics_dashboard", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = launcher
spec.loader.exec_module(launcher)


class LaunchMetricsDashboardTest(unittest.TestCase):
    """Unit tests covering launch Metrics Dashboard behavior.
    """
    def test_parse_args_defaults_to_local_summary_store(self):
        """Verify parse arguments defaults to local summary store.


        Returns:
            None.
        """
        with mock.patch.object(sys, "argv", ["launch_metrics_dashboard.py"]):
            args = launcher.parse_args()

        self.assertEqual(args.summary_store, Path("artifacts/benchmark-summaries.ndjson"))
        self.assertEqual(args.output_dir, Path("artifacts/dashboard"))

    def test_builds_dashboard_from_local_ndjson_with_rankings_and_latest_run(self):
        """Verify builds dashboard from local NDJSON with rankings and latest run.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = base / "benchmark-summaries.ndjson"
            output_dir = base / "dashboard"
            write_store(
                store,
                [
                    valid_summary("run-a", benchmark_start="2026-05-07T12:00:00Z"),
                    valid_summary(
                        "run-b",
                        benchmark_start="2026-05-07T13:00:00Z",
                        machine_type="t2a-standard-4",
                        processor_family="t2a",
                        architecture="arm64",
                        avg_rps=80,
                        p99=150,
                    ),
                ],
            )

            result = launcher.build_dashboard(
                args=dashboard_args(summary_store=store),
                output_dir=output_dir,
                schema_path=SCHEMA,
                min_duration_seconds=1200,
                min_coverage_ratio=0.95,
            )

            data = json.loads((output_dir / "dashboard-data.json").read_text(encoding="utf-8"))
            self.assertTrue((output_dir / "index.html").exists())
            self.assertEqual(result["outputs"]["dashboard_data"], str(output_dir / "dashboard-data.json"))
            self.assertEqual(data["source"]["type"], "ndjson")
            self.assertEqual(data["source"]["summary_store"], str(store))
            self.assertEqual(data["latest_run"]["run_id"], "run-b")
            self.assertEqual(data["comparison"]["comparison_group_count"], 2)
            self.assertEqual(
                data["comparison"]["rankings"]["avg_requests_per_second"][0]["machine_type"],
                "c3-standard-4",
            )

    def test_dashboard_data_lists_rejected_runs_duplicates_and_nullable_local_costs(self):
        """Verify dashboard data lists rejected runs duplicates and nullable local costs.


        Returns:
            None.
        """
        row_a = valid_summary("duplicate", cloud_provider="local", pricing_model="local")
        row_a["node_hourly_price_usd"] = None
        row_a["benchmark_compute_cost_usd"] = None
        row_a["cost_per_1m_requests_usd"] = None
        row_b = valid_summary(
            "duplicate",
            cloud_provider="local",
            pricing_model="local",
            benchmark_start="2026-05-07T13:00:00Z",
        )
        row_b["node_hourly_price_usd"] = None
        row_b["benchmark_compute_cost_usd"] = None
        row_b["cost_per_1m_requests_usd"] = None
        smoke = valid_summary("smoke", benchmark_start="2026-05-07T14:00:00Z")
        smoke["duration_seconds"] = 30

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = base / "benchmark-summaries.ndjson"
            output_dir = base / "dashboard"
            write_store(store, [row_a, row_b, smoke])

            launcher.build_dashboard(
                args=dashboard_args(summary_store=store),
                output_dir=output_dir,
                schema_path=SCHEMA,
                min_duration_seconds=1200,
                min_coverage_ratio=0.95,
            )

            data = json.loads((output_dir / "dashboard-data.json").read_text(encoding="utf-8"))
            self.assertEqual(data["summary_store"]["duplicate_run_ids"], ["duplicate"])
            self.assertEqual(data["comparison"]["status"], "warn")
            self.assertEqual(data["comparison"]["rejected_runs"][0]["run_id"], "smoke")
            self.assertIn(
                "duration_seconds_below_min:30<1200",
                data["comparison"]["rejected_runs"][0]["reasons"],
            )
            self.assertEqual(data["comparison"]["warnings"][0]["reason"], "missing_cost_fields")

    def test_bigquery_mode_queries_history_and_sets_source_metadata(self):
        """Verify BigQuery mode queries history and sets source metadata.


        Returns:
            None.
        """
        run_a = valid_summary("run-a")
        run_b = valid_summary(
            "run-b",
            machine_type="t2a-standard-4",
            processor_family="t2a",
            architecture="arm64",
        )
        runner = FakeRunner([run_a, run_b])
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "dashboard"

            launcher.build_dashboard(
                args=dashboard_args(
                    summary_store=None,
                    project_id="example-project",
                    dataset_id="silicon_boutique",
                    table_id="benchmark_summaries",
                    location="US",
                    machine_type="c3-standard-4",
                    pricing_model="spot",
                    limit=5,
                ),
                output_dir=output_dir,
                schema_path=SCHEMA,
                min_duration_seconds=1200,
                min_coverage_ratio=0.95,
                runner=runner,
            )

            data = json.loads((output_dir / "dashboard-data.json").read_text(encoding="utf-8"))
            query = runner.commands[0][-1]
            self.assertEqual(data["source"]["type"], "bigquery")
            self.assertEqual(
                data["source"]["summary_table"],
                "example-project.silicon_boutique.benchmark_summaries",
            )
            self.assertEqual(data["source"]["location"], "US")
            self.assertEqual(data["comparison"]["comparable_run_count"], 1)
            self.assertIn("machine_type = 'c3-standard-4'", query)
            self.assertIn("pricing_model = 'spot'", query)
            self.assertIn("LIMIT 5", query)

    def test_dashboard_filters_match_comparison_report_filters(self):
        """Verify dashboard filters match comparison report filters.


        Returns:
            None.
        """
        args = dashboard_args(
            summary_store=Path("unused.ndjson"),
            machine_type="c3-standard-4",
            processor_family="c3",
            architecture="x86_64",
            cloud_provider="gcp",
            pricing_model="spot",
        )

        self.assertEqual(
            launcher.comparison.filter_values(args),
            {
                "machine_type": "c3-standard-4",
                "processor_family": "c3",
                "architecture": "x86_64",
                "cloud_provider": "gcp",
                "pricing_model": "spot",
            },
        )

    def test_incomplete_bigquery_args_fail_before_querying(self):
        """Verify incomplete BigQuery arguments fail before querying.


        Returns:
            None.
        """
        argv = [
            "launch_metrics_dashboard.py",
            "--project-id",
            "example-project",
            "--dataset-id",
            "silicon_boutique",
            "--no-serve",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            exit_code = launcher.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("--dataset-id, --table-id, and --location", stderr.getvalue())

    def test_summary_store_and_project_id_fail_clearly(self):
        """Verify summary store and project ID fail clearly.


        Returns:
            None.
        """
        argv = [
            "launch_metrics_dashboard.py",
            "--summary-store",
            "artifacts/benchmark-summaries.ndjson",
            "--project-id",
            "example-project",
            "--dataset-id",
            "silicon_boutique",
            "--table-id",
            "benchmark_summaries",
            "--location",
            "US",
            "--no-serve",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            exit_code = launcher.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("--summary-store cannot be used with --project-id", stderr.getvalue())

    def test_bigquery_query_failure_returns_clear_error(self):
        """Verify BigQuery query failure returns clear error.


        Returns:
            None.
        """
        runner = FakeRunner([], returncode=1, stderr="access denied")
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(launcher.comparison.ComparisonReportError) as context:
                launcher.build_dashboard(
                    args=dashboard_args(
                        summary_store=None,
                        project_id="example-project",
                        dataset_id="silicon_boutique",
                        table_id="benchmark_summaries",
                        location="US",
                    ),
                    output_dir=Path(tmpdir) / "dashboard",
                    schema_path=SCHEMA,
                    min_duration_seconds=1200,
                    min_coverage_ratio=0.95,
                    runner=runner,
                )

        self.assertIn("failed to query BigQuery summaries: access denied", str(context.exception))

    def test_bigquery_malformed_json_returns_clear_error(self):
        """Verify BigQuery malformed JSON returns clear error.


        Returns:
            None.
        """
        runner = FakeRunner("not-json")
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(launcher.comparison.ComparisonReportError) as context:
                launcher.build_dashboard(
                    args=dashboard_args(
                        summary_store=None,
                        project_id="example-project",
                        dataset_id="silicon_boutique",
                        table_id="benchmark_summaries",
                        location="US",
                    ),
                    output_dir=Path(tmpdir) / "dashboard",
                    schema_path=SCHEMA,
                    min_duration_seconds=1200,
                    min_coverage_ratio=0.95,
                    runner=runner,
                )

        self.assertIn("bq query did not return valid JSON", str(context.exception))

    def test_visual_dashboard_html_is_self_contained_and_references_data_file(self):
        """Verify visual dashboard HTML is self contained and references data file.


        Returns:
            None.
        """
        html = launcher.render_html()

        self.assertIn("<style>", html)
        self.assertIn("<script>", html)
        self.assertIn('fetch("dashboard-data.json")', html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        for label in (
            "Latest Run",
            "Run Metrics",
            "Throughput",
            "Frontend P99 Latency",
            "Avg CPU Utilization",
            "Max CPU Utilization",
            "Max Memory",
            "Cost / 1M Requests",
            "Coverage",
            "Rankings",
            "Warnings",
            "Rejected Runs",
        ):
            self.assertIn(label, html)

    def test_no_comparable_groups_render_empty_state(self):
        """Verify no comparable groups render empty state.


        Returns:
            None.
        """
        partial = valid_summary("partial")
        partial["summary_status"] = "partial"
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = base / "benchmark-summaries.ndjson"
            output_dir = base / "dashboard"
            write_store(store, [partial])

            launcher.build_dashboard(
                args=dashboard_args(summary_store=store),
                output_dir=output_dir,
                schema_path=SCHEMA,
                min_duration_seconds=1200,
                min_coverage_ratio=0.95,
            )

            data = json.loads((output_dir / "dashboard-data.json").read_text(encoding="utf-8"))
            html = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertEqual(data["comparison"]["comparison_group_count"], 0)
            self.assertIn("No comparable groups.", html)

    def test_mixed_provider_rows_are_preserved_for_visual_dashboard(self):
        """Verify mixed provider rows are preserved for visual dashboard.


        Returns:
            None.
        """
        rows = [
            valid_summary("local-a", cloud_provider="local", pricing_model="local", region="local", zone="local"),
            valid_summary("gcp-a", cloud_provider="gcp", pricing_model="spot"),
            valid_summary(
                "aws-a",
                cloud_provider="aws",
                pricing_model="on_demand",
                machine_type="m7i.xlarge",
                processor_family="m7i",
                region="us-east-1",
                zone="us-east-1a",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = base / "benchmark-summaries.ndjson"
            output_dir = base / "dashboard"
            write_store(store, rows)

            launcher.build_dashboard(
                args=dashboard_args(summary_store=store),
                output_dir=output_dir,
                schema_path=SCHEMA,
                min_duration_seconds=1200,
                min_coverage_ratio=0.95,
            )

            data = json.loads((output_dir / "dashboard-data.json").read_text(encoding="utf-8"))
            providers = {
                group["metadata"]["cloud_provider"]
                for group in data["comparison"]["comparison_groups"]
            }
            self.assertEqual(providers, {"local", "gcp", "aws"})

    def test_missing_summary_store_returns_cli_error(self):
        """Verify missing summary store returns CLI error.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            argv = [
                "launch_metrics_dashboard.py",
                "--summary-store",
                str(base / "missing.ndjson"),
                "--output-dir",
                str(base / "dashboard"),
                "--no-serve",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch(
                "sys.stderr", new_callable=io.StringIO
            ) as stderr:
                exit_code = launcher.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("summary store does not exist", stderr.getvalue())

    def test_no_serve_does_not_open_browser(self):
        """Verify no serve does not open browser.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = base / "benchmark-summaries.ndjson"
            write_store(store, [valid_summary("run-a")])
            argv = [
                "launch_metrics_dashboard.py",
                "--summary-store",
                str(store),
                "--output-dir",
                str(base / "dashboard"),
                "--no-browser",
                "--no-serve",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                launcher.webbrowser, "open"
            ) as open_browser, mock.patch("sys.stdout", new_callable=io.StringIO):
                exit_code = launcher.main()

        self.assertEqual(exit_code, 0)
        open_browser.assert_not_called()

    def test_create_server_selects_localhost_url_for_ephemeral_port(self):
        """Verify create server selects localhost URL for ephemeral port.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            server, url = launcher.create_server(Path(tmpdir), host="127.0.0.1", port=0)
            try:
                self.assertRegex(url, r"^http://127\.0\.0\.1:\d+/index\.html$")
            finally:
                server.server_close()


class FakeRunner:
    """Test double that records runner interactions.
    """
    def __init__(self, rows, *, returncode=0, stderr=""):
        """Initialize the object with the provided configuration.


        Args:
            rows: rows used by this operation.
            returncode: returncode used by this operation.
            stderr: standard error used by this operation.

        Returns:
            None.
        """
        self.rows = rows
        self.returncode = returncode
        self.stderr = stderr
        self.commands = []

    def __call__(self, command):
        """Handle the object call using the supplied arguments.


        Args:
            command: command used by this operation.

        Returns:
            Result produced by call.
        """
        self.commands.append(command)
        stdout = self.rows if isinstance(self.rows, str) else json.dumps(self.rows)
        return launcher.comparison.CommandResult(self.returncode, stdout, self.stderr)


def dashboard_args(
    *,
    summary_store,
    project_id=None,
    dataset_id=None,
    table_id=None,
    location=None,
    machine_type=None,
    processor_family=None,
    architecture=None,
    cloud_provider=None,
    pricing_model=None,
    limit=None,
):
    """Compute dashboard arguments.


    Args:
        summary_store: summary store used by this operation.
        project_id: project ID used by this operation.
        dataset_id: dataset ID used by this operation.
        table_id: table ID used by this operation.
        location: location used by this operation.
        machine_type: machine type used by this operation.
        processor_family: processor family used by this operation.
        architecture: architecture used by this operation.
        cloud_provider: cloud provider used by this operation.
        pricing_model: pricing model used by this operation.
        limit: limit used by this operation.

    Returns:
        Result produced by dashboard arguments.
    """
    return launcher.argparse.Namespace(
        summary_store=summary_store,
        project_id=project_id,
        dataset_id=dataset_id,
        table_id=table_id,
        location=location,
        machine_type=machine_type,
        processor_family=processor_family,
        architecture=architecture,
        cloud_provider=cloud_provider,
        pricing_model=pricing_model,
        limit=limit,
    )


def write_store(path, rows):
    """Write store.


    Args:
        path: path used by this operation.
        rows: rows used by this operation.

    Returns:
        None.
    """
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def valid_summary(
    run_id,
    *,
    machine_type="c3-standard-4",
    processor_family="c3",
    architecture="x86_64",
    avg_rps=100.0,
    cpu_cores=2.0,
    p99=120.0,
    memory_gb=1.0,
    cost=0.4,
    failures=1,
    request_total=120000,
    benchmark_start="2026-05-07T12:00:00Z",
    cloud_provider="gcp",
    pricing_model="spot",
    region="us-central1",
    zone="us-central1-a",
):
    """Compute valid summary.


    Args:
        run_id: run ID used by this operation.
        machine_type: machine type used by this operation.
        processor_family: processor family used by this operation.
        architecture: architecture used by this operation.
        avg_rps: avg rps used by this operation.
        cpu_cores: CPU cores used by this operation.
        p99: p99 used by this operation.
        memory_gb: memory GB used by this operation.
        cost: cost used by this operation.
        failures: failures used by this operation.
        request_total: request total used by this operation.
        benchmark_start: benchmark start used by this operation.
        cloud_provider: cloud provider used by this operation.
        pricing_model: pricing model used by this operation.
        region: region used by this operation.
        zone: zone used by this operation.

    Returns:
        Result produced by valid summary.
    """
    return {
        "architecture": architecture,
        "avg_cpu_throttling_ratio": 0.01,
        "avg_cpu_usage_cores": cpu_cores,
        "avg_cpu_utilization_pct": 80.0,
        "avg_memory_working_set_bytes": memory_gb * 1_000_000_000,
        "avg_requests_per_second": avg_rps,
        "avg_ready_pods": 12.0,
        "benchmark_compute_cost_usd": 0.001,
        "benchmark_end": "2026-05-07T12:20:00Z",
        "benchmark_start": benchmark_start,
        "cloud_provider": cloud_provider,
        "cost_per_1m_requests_usd": cost,
        "cpu_platform": "intel-sapphire-rapids",
        "duration_seconds": 1200,
        "empty_metrics": [],
        "environment": cloud_provider,
        "frontend_latency_max_ms": p99 + 10,
        "frontend_latency_p50_ms": p99 / 2,
        "frontend_latency_p95_ms": p99 - 10,
        "frontend_latency_p99_ms": p99,
        "generated_at": "2026-05-07T12:21:00Z",
        "invalid_metric_samples": {},
        "load_concurrent_users": 10,
        "load_profile_source": "manual",
        "load_users_per_second": 1.0,
        "machine_type": machine_type,
        "max_cpu_throttling_ratio": 0.02,
        "max_cpu_usage_cores": cpu_cores + 0.5,
        "max_cpu_utilization_pct": 90.0,
        "max_memory_used_gb": memory_gb,
        "max_memory_working_set_bytes": memory_gb * 1_000_000_000,
        "max_ready_pods": 12.0,
        "max_restarts_total": 0.0,
        "metrics_coverage_ratio": 0.99,
        "min_ready_pods": 12.0,
        "missing_metrics": [],
        "namespace": run_id,
        "node_count": 1,
        "node_hourly_price_usd": 0.03,
        "pricing_model": pricing_model,
        "processor_family": processor_family,
        "region": region,
        "request_count_total": request_total,
        "request_failure_count": failures,
        "request_success_count": request_total - failures,
        "run_id": run_id,
        "summary_status": "complete",
        "zone": zone,
    }


if __name__ == "__main__":
    unittest.main()
