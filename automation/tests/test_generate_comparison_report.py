import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "generate_comparison_report.py"
SCHEMA = REPO_ROOT / "automation" / "templates" / "benchmark-summary.schema.json"

sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("generate_comparison_report", SCRIPT)
reporter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reporter
spec.loader.exec_module(reporter)


class FakeRunner:
    def __init__(self, rows):
        self.rows = rows
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        return reporter.CommandResult(0, json.dumps(self.rows), "")


class GenerateComparisonReportTest(unittest.TestCase):
    def valid_summary(
        self,
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
        request_total=1000,
        benchmark_start="2026-05-07T12:00:00Z",
        cloud_provider="gcp",
        region="us-central1",
        zone="us-central1-a",
    ):
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
            "pricing_model": "spot",
            "processor_family": processor_family,
            "region": region,
            "request_count_total": request_total,
            "request_failure_count": failures,
            "request_success_count": request_total - failures,
            "run_id": run_id,
            "summary_status": "complete",
            "zone": zone,
        }

    def write_store(self, path, rows):
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def run_report(self, rows, *extra_args):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        base = Path(tmpdir.name)
        store = base / "summaries.ndjson"
        output = base / "comparison.json"
        markdown = base / "comparison.md"
        self.write_store(store, rows)
        argv = [
            "generate_comparison_report.py",
            "--summary-store",
            str(store),
            "--schema",
            str(SCHEMA),
            "--report-output",
            str(output),
            "--markdown-output",
            str(markdown),
            *extra_args,
        ]
        with mock.patch.object(sys, "argv", argv):
            exit_code = reporter.main()
        payload = json.loads(output.read_text(encoding="utf-8"))
        return exit_code, payload, markdown.read_text(encoding="utf-8")

    def test_ranks_and_aggregates_comparable_machine_groups(self):
        rows = [
            self.valid_summary("c3-a", avg_rps=100, cpu_cores=2, p99=120, memory_gb=1.0, cost=0.4, failures=1),
            self.valid_summary("c3-b", avg_rps=120, cpu_cores=2, p99=100, memory_gb=1.2, cost=0.5, failures=2),
            self.valid_summary(
                "t2a-a",
                machine_type="t2a-standard-4",
                processor_family="t2a",
                architecture="arm64",
                avg_rps=80,
                cpu_cores=1,
                p99=150,
                memory_gb=0.8,
                cost=0.3,
                failures=0,
            ),
        ]

        exit_code, payload, markdown = self.run_report(rows)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["comparison_group_count"], 2)
        c3_group = next(
            group
            for group in payload["comparison_groups"]
            if group["metadata"]["machine_type"] == "c3-standard-4"
        )
        self.assertEqual(c3_group["run_count"], 2)
        self.assertEqual(c3_group["run_ids"], ["c3-a", "c3-b"])
        self.assertAlmostEqual(c3_group["metrics"]["avg_requests_per_second"], 110.0)
        self.assertEqual(
            payload["rankings"]["frontend_latency_p99_ms"][0]["machine_type"],
            "c3-standard-4",
        )
        self.assertEqual(
            payload["rankings"]["requests_per_cpu_core"][0]["machine_type"],
            "t2a-standard-4",
        )
        self.assertIn("| Provider | Region | Machine | Processor |", markdown)
        self.assertIn("| 1 | gcp | us-central1 | c3-standard-4 | c3 |", markdown)

    def test_mixed_cloud_rows_render_provider_and_region(self):
        rows = [
            self.valid_summary("gcp-a"),
            self.valid_summary(
                "aws-a",
                machine_type="m7i.xlarge",
                processor_family="m7i",
                cloud_provider="aws",
                region="us-east-1",
                zone="us-east-1a",
                avg_rps=90,
                p99=130,
            ),
        ]

        exit_code, payload, markdown = self.run_report(rows)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["comparison_group_count"], 2)
        providers = {
            group["metadata"]["machine_type"]: group["metadata"]["cloud_provider"]
            for group in payload["comparison_groups"]
        }
        self.assertEqual(providers["c3-standard-4"], "gcp")
        self.assertEqual(providers["m7i.xlarge"], "aws")
        self.assertIn("| aws | us-east-1 | m7i.xlarge | m7i |", markdown)

    def test_rejects_non_comparable_runs(self):
        partial = self.valid_summary("partial")
        partial["summary_status"] = "partial"

        exit_code, payload, _ = self.run_report(
            [self.valid_summary("valid-a"), self.valid_summary("valid-b"), partial]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "warn")
        self.assertEqual(payload["rejected_runs"][0]["run_id"], "partial")
        self.assertIn("summary_status_not_complete", payload["rejected_runs"][0]["reasons"])

    def test_missing_cost_fields_warns_and_excludes_cost_ranking(self):
        row_a = self.valid_summary("run-a")
        row_b = self.valid_summary("run-b", machine_type="t2a-standard-4", processor_family="t2a")
        row_a["cost_per_1m_requests_usd"] = None
        row_a["node_hourly_price_usd"] = None
        row_a["benchmark_compute_cost_usd"] = None

        exit_code, payload, _ = self.run_report([row_a, row_b])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "warn")
        self.assertEqual(payload["warnings"][0]["reason"], "missing_cost_fields")
        self.assertEqual(len(payload["rankings"]["cost_per_1m_requests_usd"]), 1)
        self.assertEqual(
            payload["rankings"]["cost_per_1m_requests_usd"][0]["machine_type"],
            "t2a-standard-4",
        )

    def test_bigquery_source_builds_filtered_query_and_parses_rows(self):
        runner = FakeRunner(
            [
                self.valid_summary("run-a"),
                self.valid_summary("run-b", machine_type="t2a-standard-4", processor_family="t2a"),
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "comparison.json"
            markdown = Path(tmpdir) / "comparison.md"
            argv = [
                "generate_comparison_report.py",
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(SCHEMA),
                "--report-output",
                str(output),
                "--markdown-output",
                str(markdown),
                "--machine-type",
                "c3-standard-4",
                "--pricing-model",
                "spot",
                "--limit",
                "5",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                reporter, "run_bq", runner
            ):
                exit_code = reporter.main()

            payload = json.loads(output.read_text(encoding="utf-8"))
            query = runner.commands[0][-1]
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["source"]["type"], "bigquery")
            self.assertIn("FROM `example-project.silicon_boutique.benchmark_summaries`", query)
            self.assertIn("machine_type = 'c3-standard-4'", query)
            self.assertIn("pricing_model = 'spot'", query)
            self.assertIn("LIMIT 5", query)


if __name__ == "__main__":
    unittest.main()
