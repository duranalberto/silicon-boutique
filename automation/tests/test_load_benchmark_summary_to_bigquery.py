"""Tests for test load benchmark summary to bigquery."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "load_benchmark_summary_to_bigquery.py"
CANONICAL_SCHEMA = REPO_ROOT / "automation" / "templates" / "benchmark-summary.schema.json"
BIGQUERY_SCHEMA = (
    REPO_ROOT / "automation" / "templates" / "benchmark-summary.bigquery-schema.json"
)

spec = importlib.util.spec_from_file_location("load_benchmark_summary_to_bigquery", SCRIPT)
loader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loader
spec.loader.exec_module(loader)


class FakeRunner:
    """Test double that records runner interactions.
    """
    def __init__(
        self,
        *,
        schema,
        duplicate_rows=None,
        fail_show=False,
        fail_load=False,
        fail_delete=False,
        show_stdout=None,
    ):
        """Initialize the object with the provided configuration.


        Args:
            schema: schema used by this operation.
            duplicate_rows: duplicate rows used by this operation.
            fail_show: fail show used by this operation.
            fail_load: fail load used by this operation.
            fail_delete: fail delete used by this operation.
            show_stdout: show standard output used by this operation.

        Returns:
            None.
        """
        self.schema = schema
        self.duplicate_rows = duplicate_rows or []
        self.fail_show = fail_show
        self.fail_load = fail_load
        self.fail_delete = fail_delete
        self.show_stdout = show_stdout
        self.commands = []

    def __call__(self, command):
        """Handle the object call using the supplied arguments.


        Args:
            command: command used by this operation.

        Returns:
            Result produced by call.
        """
        self.commands.append(command)
        if "show" in command:
            if self.fail_show:
                return loader.CommandResult(1, "", "access denied")
            if self.show_stdout is not None:
                return loader.CommandResult(0, self.show_stdout, "")
            return loader.CommandResult(
                0, json.dumps({"schema": {"fields": self.schema}}), ""
            )
        if "query" in command:
            return loader.CommandResult(0, json.dumps(self.duplicate_rows), "")
        if "load" in command:
            if self.fail_load:
                return loader.CommandResult(1, "", "tables.create denied")
            return loader.CommandResult(0, "", "")
        if "rm" in command:
            if self.fail_delete:
                return loader.CommandResult(1, "", "delete denied")
            return loader.CommandResult(0, "", "")
        return loader.CommandResult(1, "", "unexpected command")


def valid_summary(run_id="test-run"):
    """Compute valid summary.


    Args:
        run_id: run ID used by this operation.

    Returns:
        Result produced by valid summary.
    """
    return {
        "architecture": "x86_64",
        "avg_cpu_throttling_ratio": 0.01,
        "avg_cpu_usage_cores": 1.9,
        "avg_cpu_utilization_pct": 47.5,
        "avg_memory_working_set_bytes": 1200.0,
        "avg_requests_per_second": 5.0,
        "avg_ready_pods": 12.0,
        "benchmark_compute_cost_usd": 0.001,
        "benchmark_end": "2026-05-07T12:20:00Z",
        "benchmark_start": "2026-05-07T12:00:00Z",
        "cloud_provider": "gcp",
        "cost_per_1m_requests_usd": 3.38983051,
        "cpu_platform": "intel-sapphire-rapids",
        "duration_seconds": 1200,
        "empty_metrics": [],
        "environment": "gcp",
        "frontend_latency_max_ms": 600.0,
        "frontend_latency_p50_ms": 120.0,
        "frontend_latency_p95_ms": 300.0,
        "frontend_latency_p99_ms": 492.0,
        "generated_at": "2026-05-07T12:21:00Z",
        "invalid_metric_samples": {},
        "load_concurrent_users": 10,
        "load_profile_source": "manual",
        "load_users_per_second": 1.0,
        "machine_type": "e2-standard-4",
        "max_cpu_throttling_ratio": 0.02,
        "max_cpu_usage_cores": 2.4,
        "max_cpu_utilization_pct": 60.0,
        "max_memory_used_gb": 0.5,
        "max_memory_working_set_bytes": 500000000.0,
        "max_ready_pods": 12.0,
        "max_restarts_total": 0.0,
        "metrics_coverage_ratio": 1.0,
        "min_ready_pods": 12.0,
        "missing_metrics": [],
        "namespace": "gha-123-1",
        "node_count": 2,
        "node_hourly_price_usd": 0.03,
        "pricing_model": "spot",
        "processor_family": "e2",
        "region": "us-central1",
        "request_count_total": 300,
        "request_failure_count": 5,
        "request_success_count": 295,
        "run_id": run_id,
        "summary_status": "complete",
        "zone": "us-central1-a",
    }


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


class LoadBenchmarkSummaryToBigQueryTest(unittest.TestCase):
    """Unit tests covering load Benchmark Summary To Big Query behavior.
    """
    def load_schema(self):
        """Load schema.


        Returns:
            Result produced by load schema.
        """
        return json.loads(BIGQUERY_SCHEMA.read_text(encoding="utf-8"))

    def test_load_builds_expected_bq_commands(self):
        """Verify load builds expected BigQuery commands.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_store = Path(tmpdir) / "benchmark-summaries.ndjson"
            write_store(summary_store, [valid_summary()])
            runner = FakeRunner(schema=self.load_schema())

            rows = loader.select_rows(loader.read_summary_rows(summary_store), None)
            loader.validate_table_schema(
                project_id="example-project",
                dataset_id="silicon_boutique",
                table_id="benchmark_summaries",
                expected_schema=self.load_schema(),
                runner=runner,
            )
            loader.validate_query_access(
                project_id="example-project",
                dataset_id="silicon_boutique",
                table_id="benchmark_summaries",
                location="US",
                runner=runner,
            )
            duplicate_run_ids = loader.existing_run_ids(
                project_id="example-project",
                dataset_id="silicon_boutique",
                table_id="benchmark_summaries",
                location="US",
                run_ids=[row["run_id"] for row in rows],
                runner=runner,
            )
            loader.load_rows(
                rows=rows,
                project_id="example-project",
                dataset_id="silicon_boutique",
                table_id="benchmark_summaries",
                location="US",
                schema=BIGQUERY_SCHEMA,
                runner=runner,
            )

            self.assertEqual(duplicate_run_ids, set())
            self.assertEqual(runner.commands[0][:4], ["bq", "--format=json", "--project_id", "example-project"])
            self.assertEqual(runner.commands[0][4], "show")
            self.assertIn("example-project:silicon_boutique.benchmark_summaries", runner.commands[0])
            self.assertEqual(runner.commands[1][:4], ["bq", "--format=json", "--project_id", "example-project"])
            self.assertEqual(runner.commands[1][6:8], ["query", "--nouse_legacy_sql"])
            self.assertIn("WHERE FALSE LIMIT 0", runner.commands[1][-1])
            self.assertEqual(runner.commands[2][:4], ["bq", "--format=json", "--project_id", "example-project"])
            self.assertIn("WHERE run_id IN ('test-run')", runner.commands[2][-1])
            self.assertEqual(runner.commands[3][:5], ["bq", "--project_id", "example-project", "--location", "US"])
            self.assertEqual(runner.commands[3][5], "load")
            self.assertIn("--source_format=NEWLINE_DELIMITED_JSON", runner.commands[3])

    def test_duplicate_run_id_is_detected_before_load(self):
        """Verify duplicate run ID is detected before load.


        Returns:
            None.
        """
        runner = FakeRunner(
            schema=self.load_schema(), duplicate_rows=[{"run_id": "test-run"}]
        )

        duplicate_run_ids = loader.existing_run_ids(
            project_id="example-project",
            dataset_id="silicon_boutique",
            table_id="benchmark_summaries",
            location="US",
            run_ids=["test-run"],
            runner=runner,
        )

        self.assertEqual(duplicate_run_ids, {"test-run"})

    def test_main_reports_table_inspection_failure(self):
        """Verify main reports table inspection failure.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_store = Path(tmpdir) / "benchmark-summaries.ndjson"
            report = Path(tmpdir) / "bigquery-load-report.json"
            write_store(summary_store, [valid_summary()])
            runner = FakeRunner(schema=self.load_schema(), fail_show=True)
            argv = [
                "load_benchmark_summary_to_bigquery.py",
                "--summary-store",
                str(summary_store),
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(BIGQUERY_SCHEMA),
                "--load-report-output",
                str(report),
            ]

            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                loader, "run_bq", runner
            ), mock.patch.object(sys, "stderr", io.StringIO()):
                result = loader.main()

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result, 2)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["stage"], "bq_show_schema")
            self.assertIn("failed to inspect BigQuery table", payload["error"])
            self.assertEqual(payload["diagnostics"]["returncode"], 1)
            self.assertIn("access denied", payload["diagnostics"]["stderr_preview"])

    def test_main_reports_non_json_table_inspection_with_preview(self):
        """Verify main reports non JSON table inspection with preview.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_store = Path(tmpdir) / "benchmark-summaries.ndjson"
            report = Path(tmpdir) / "bigquery-load-report.json"
            write_store(summary_store, [valid_summary()])
            runner = FakeRunner(
                schema=self.load_schema(),
                show_stdout="Welcome to bq\ncredential=/tmp/gha-creds-secret.json",
            )
            argv = [
                "load_benchmark_summary_to_bigquery.py",
                "--summary-store",
                str(summary_store),
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(BIGQUERY_SCHEMA),
                "--load-report-output",
                str(report),
            ]

            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                loader, "run_bq", runner
            ), mock.patch.object(sys, "stderr", io.StringIO()):
                result = loader.main()

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result, 2)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["stage"], "bq_show_schema")
            self.assertIn("did not return valid JSON", payload["error"])
            self.assertIn("Welcome to bq", payload["diagnostics"]["stdout_preview"])
            self.assertNotIn("secret", payload["diagnostics"]["stdout_preview"])

    def test_table_inspection_allows_warning_prefix_before_json(self):
        """Verify table inspection allows warning prefix before JSON.


        Returns:
            None.
        """
        runner = FakeRunner(
            schema=self.load_schema(),
            show_stdout=(
                "WARNING: BigQuery CLI emitted a startup warning\n"
                + json.dumps({"schema": {"fields": self.load_schema()}})
            ),
        )

        loader.validate_table_schema(
            project_id="example-project",
            dataset_id="silicon_boutique",
            table_id="benchmark_summaries",
            expected_schema=self.load_schema(),
            runner=runner,
        )

        self.assertEqual(len(runner.commands), 1)

    def test_dry_run_validates_without_load_command(self):
        """Verify dry run validates without load command.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_store = Path(tmpdir) / "benchmark-summaries.ndjson"
            report = Path(tmpdir) / "bigquery-load-report.json"
            write_store(summary_store, [valid_summary()])
            runner = FakeRunner(schema=self.load_schema())
            argv = [
                "load_benchmark_summary_to_bigquery.py",
                "--summary-store",
                str(summary_store),
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(BIGQUERY_SCHEMA),
                "--load-report-output",
                str(report),
                "--dry-run",
            ]

            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                loader, "run_bq", runner
            ):
                result = loader.main()

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["status"], "validated")
            self.assertFalse(any("load" in command for command in runner.commands))

    def test_multi_row_store_requires_run_id_selection(self):
        """Verify multi row store requires run ID selection.


        Returns:
            None.
        """
        rows = [valid_summary("run-a"), valid_summary("run-b")]

        with self.assertRaises(loader.BigQueryLoadError):
            loader.select_rows(rows, None)

        self.assertEqual(loader.select_rows(rows, "run-b")[0]["run_id"], "run-b")

    def test_bigquery_schema_matches_canonical_summary_fields(self):
        """Verify BigQuery schema matches canonical summary fields.


        Returns:
            None.
        """
        canonical = json.loads(CANONICAL_SCHEMA.read_text(encoding="utf-8"))
        canonical_fields = set(canonical["properties"])
        bigquery_fields = {field["name"] for field in self.load_schema()}
        required = set(canonical["required"])
        required_modes = {
            field["name"]
            for field in self.load_schema()
            if field.get("mode") == "REQUIRED"
        }

        self.assertEqual(bigquery_fields, canonical_fields)
        self.assertEqual(required_modes, required)

    def test_main_success_report_proves_fake_load_and_query_path(self):
        """Verify main success report proves fake load and query path.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_store = Path(tmpdir) / "benchmark-summaries.ndjson"
            report = Path(tmpdir) / "bigquery-load-report.json"
            write_store(summary_store, [valid_summary()])
            runner = FakeRunner(schema=self.load_schema())
            argv = [
                "load_benchmark_summary_to_bigquery.py",
                "--summary-store",
                str(summary_store),
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(BIGQUERY_SCHEMA),
                "--load-report-output",
                str(report),
                "--run-id",
                "test-run",
            ]

            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                loader, "run_bq", runner
            ):
                result = loader.main()

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["status"], "loaded")
            self.assertEqual(payload["run_ids"], ["test-run"])
            self.assertTrue(any("load" in command for command in runner.commands))

    def test_preflight_only_validates_destination_without_summary_store(self):
        """Verify preflight only validates destination without summary store.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            report = Path(tmpdir) / "bigquery-load-report.json"
            runner = FakeRunner(schema=self.load_schema())
            argv = [
                "load_benchmark_summary_to_bigquery.py",
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(BIGQUERY_SCHEMA),
                "--load-report-output",
                str(report),
                "--preflight-only",
            ]

            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                loader, "run_bq", runner
            ):
                result = loader.main()

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["status"], "validated")
            self.assertEqual(payload["stage"], "preflight")
            self.assertEqual(len(runner.commands), 2)
            self.assertTrue(all("load" not in command for command in runner.commands))

    def test_preflight_write_probe_loads_and_deletes_scratch_table(self):
        """Verify preflight write probe loads and deletes scratch table.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            report = Path(tmpdir) / "bigquery-load-report.json"
            runner = FakeRunner(schema=self.load_schema())
            argv = [
                "load_benchmark_summary_to_bigquery.py",
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(BIGQUERY_SCHEMA),
                "--load-report-output",
                str(report),
                "--run-id",
                "gha-123-1",
                "--preflight-write-probe",
                "--preflight-only",
            ]

            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                loader, "run_bq", runner
            ):
                result = loader.main()

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["status"], "validated")
            self.assertTrue(payload["preflight_write_probe"])
            self.assertEqual(payload["preflight_scratch_table_id"], "sb_preflight_gha_123_1")
            self.assertEqual(len(runner.commands), 4)
            self.assertEqual(runner.commands[2][5], "load")
            self.assertIn(
                "example-project:silicon_boutique.sb_preflight_gha_123_1",
                runner.commands[2],
            )
            self.assertEqual(runner.commands[3][3:6], ["rm", "-f", "-t"])
            self.assertIn(
                "example-project:silicon_boutique.sb_preflight_gha_123_1",
                runner.commands[3],
            )

    def test_preflight_write_probe_reports_load_permission_failure(self):
        """Verify preflight write probe reports load permission failure.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            report = Path(tmpdir) / "bigquery-load-report.json"
            runner = FakeRunner(schema=self.load_schema(), fail_load=True)
            argv = [
                "load_benchmark_summary_to_bigquery.py",
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(BIGQUERY_SCHEMA),
                "--load-report-output",
                str(report),
                "--run-id",
                "gha-123-1",
                "--preflight-write-probe",
                "--preflight-only",
            ]

            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                loader, "run_bq", runner
            ), mock.patch.object(sys, "stderr", io.StringIO()):
                result = loader.main()

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result, 2)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["stage"], "bq_preflight_write_probe")
            self.assertIn("failed to load BigQuery preflight write probe rows", payload["error"])
            self.assertIn("tables.create denied", payload["diagnostics"]["stderr_preview"])
            self.assertEqual(
                payload["diagnostics"]["scratch_table_id"],
                "sb_preflight_gha_123_1",
            )
            self.assertTrue(any("rm" in command for command in runner.commands))

    def test_preflight_write_probe_reports_cleanup_failure(self):
        """Verify preflight write probe reports cleanup failure.


        Returns:
            None.
        """
        runner = FakeRunner(schema=self.load_schema(), fail_delete=True)

        with self.assertRaises(loader.BigQueryLoadError) as context:
            loader.preflight_write_probe(
                project_id="example-project",
                dataset_id="silicon_boutique",
                location="US",
                schema=BIGQUERY_SCHEMA,
                run_id="gha-123-1",
                runner=runner,
            )

        self.assertEqual(context.exception.stage, "bq_preflight_cleanup")
        self.assertEqual(
            context.exception.diagnostics["scratch_table_id"],
            "sb_preflight_gha_123_1",
        )
        self.assertEqual(runner.commands[-1][3:6], ["rm", "-f", "-t"])


if __name__ == "__main__":
    unittest.main()
