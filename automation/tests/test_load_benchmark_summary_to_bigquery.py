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
    def __init__(self, *, schema, duplicate_rows=None, fail_show=False):
        self.schema = schema
        self.duplicate_rows = duplicate_rows or []
        self.fail_show = fail_show
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        if command[:2] == ["bq", "show"]:
            if self.fail_show:
                return loader.CommandResult(1, "", "access denied")
            return loader.CommandResult(
                0, json.dumps({"schema": {"fields": self.schema}}), ""
            )
        if command[:2] == ["bq", "query"]:
            return loader.CommandResult(0, json.dumps(self.duplicate_rows), "")
        if command[:2] == ["bq", "load"]:
            return loader.CommandResult(0, "", "")
        return loader.CommandResult(1, "", "unexpected command")


def valid_summary(run_id="test-run"):
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
        "node_hourly_price_usd": 0.03,
        "processor_family": "e2",
        "request_count_total": 300,
        "request_failure_count": 5,
        "request_success_count": 295,
        "run_id": run_id,
        "summary_status": "complete",
    }


def write_store(path, rows):
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


class LoadBenchmarkSummaryToBigQueryTest(unittest.TestCase):
    def load_schema(self):
        return json.loads(BIGQUERY_SCHEMA.read_text(encoding="utf-8"))

    def test_load_builds_expected_bq_commands(self):
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
            self.assertEqual(runner.commands[0][:4], ["bq", "show", "--format=json", "--project_id"])
            self.assertIn("example-project:silicon_boutique.benchmark_summaries", runner.commands[0])
            self.assertEqual(runner.commands[1][:3], ["bq", "query", "--nouse_legacy_sql"])
            self.assertIn("WHERE run_id IN ('test-run')", runner.commands[1][-1])
            self.assertEqual(runner.commands[2][:2], ["bq", "load"])
            self.assertIn("--source_format=NEWLINE_DELIMITED_JSON", runner.commands[2])

    def test_duplicate_run_id_is_detected_before_load(self):
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
            self.assertIn("failed to inspect BigQuery table", payload["error"])

    def test_dry_run_validates_without_load_command(self):
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
            self.assertFalse(any(command[:2] == ["bq", "load"] for command in runner.commands))

    def test_multi_row_store_requires_run_id_selection(self):
        rows = [valid_summary("run-a"), valid_summary("run-b")]

        with self.assertRaises(loader.BigQueryLoadError):
            loader.select_rows(rows, None)

        self.assertEqual(loader.select_rows(rows, "run-b")[0]["run_id"], "run-b")

    def test_bigquery_schema_matches_canonical_summary_fields(self):
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
            self.assertTrue(any(command[:2] == ["bq", "load"] for command in runner.commands))


if __name__ == "__main__":
    unittest.main()
