import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_SCRIPT = (
    REPO_ROOT / "automation" / "scripts" / "validate_benchmark_comparability.py"
)
SCHEMA = REPO_ROOT / "automation" / "templates" / "benchmark-summary.schema.json"


class ValidateBenchmarkComparabilityTest(unittest.TestCase):
    def valid_summary(self, run_id="run-a", machine_type="minikube-a"):
        return {
            "architecture": "x86_64",
            "avg_cpu_throttling_ratio": 0.018,
            "avg_cpu_usage_cores": 1.9,
            "avg_cpu_utilization_pct": 47.5,
            "avg_memory_working_set_bytes": 1400.0,
            "avg_requests_per_second": 5.0,
            "avg_ready_pods": 11.0,
            "benchmark_compute_cost_usd": None,
            "benchmark_end": "2026-05-07T12:20:00Z",
            "benchmark_start": "2026-05-07T12:00:00Z",
            "cloud_provider": "local",
            "cost_per_1m_requests_usd": None,
            "cpu_platform": None,
            "duration_seconds": 1200,
            "empty_metrics": [],
            "environment": "local",
            "frontend_latency_max_ms": 500.0,
            "frontend_latency_p50_ms": 200.0,
            "frontend_latency_p95_ms": 460.0,
            "frontend_latency_p99_ms": 492.0,
            "generated_at": "2026-05-07T12:21:00Z",
            "invalid_metric_samples": {},
            "load_concurrent_users": 10,
            "load_profile_source": "manual",
            "load_users_per_second": 1.0,
            "machine_type": machine_type,
            "max_cpu_throttling_ratio": 0.03,
            "max_cpu_usage_cores": 2.5,
            "max_cpu_utilization_pct": 60.0,
            "max_memory_used_gb": 0.000002,
            "max_memory_working_set_bytes": 2000.0,
            "max_ready_pods": 11.0,
            "max_restarts_total": 1.0,
            "metrics_coverage_ratio": 0.99,
            "min_ready_pods": 11.0,
            "missing_metrics": [],
            "namespace": f"sb-{run_id}",
            "node_count": 1,
            "node_hourly_price_usd": None,
            "pricing_model": "local",
            "processor_family": "local-dev",
            "region": "local",
            "request_count_total": 300,
            "request_failure_count": 5,
            "request_success_count": 295,
            "run_id": run_id,
            "zone": "local",
            "summary_status": "complete",
        }

    def run_validator(self, rows, *extra_args):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        base = Path(tmpdir.name)
        store = base / "benchmark-summaries.ndjson"
        report = base / "comparability-report.json"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR_SCRIPT),
                "--summary-store",
                str(store),
                "--schema",
                str(SCHEMA),
                "--report-output",
                str(report),
                "--min-duration-seconds",
                "1200",
                "--min-coverage-ratio",
                "0.95",
                *extra_args,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        payload = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
        return result, payload

    def test_two_valid_fixture_summaries_pass_comparability(self):
        result, report = self.run_validator(
            [
                self.valid_summary("run-a", "minikube-a"),
                self.valid_summary("run-b", "minikube-b"),
            ],
            "--strict",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["comparability_status"], "pass")
        self.assertEqual(report["comparable_run_ids"], ["run-a", "run-b"])
        self.assertEqual(report["rejected_runs"], [])

    def test_single_valid_summary_passes_summary_mode(self):
        result, report = self.run_validator(
            [self.valid_summary()],
            "--mode",
            "summary",
            "--strict",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["validation_mode"], "summary")
        self.assertEqual(report["summary_validation_status"], "pass")
        self.assertEqual(report["comparability_validation_status"], "fail")
        self.assertEqual(report["comparability_status"], "fail")
        self.assertEqual(report["comparable_run_ids"], ["run-a"])
        self.assertEqual(report["rejected_runs"], [])

    def test_run_id_selection_passes_summary_mode_with_invalid_historical_rows(self):
        short_row = self.valid_summary("short-run")
        short_row["duration_seconds"] = 60
        partial_row = self.valid_summary("partial-run")
        partial_row["summary_status"] = "partial"

        result, report = self.run_validator(
            [short_row, self.valid_summary("target-run"), partial_row],
            "--run-id",
            "target-run",
            "--mode",
            "summary",
            "--strict",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["selected_run_id"], "target-run")
        self.assertEqual(report["source_total_rows"], 3)
        self.assertEqual(report["total_rows"], 1)
        self.assertEqual(report["summary_validation_status"], "pass")
        self.assertEqual(report["comparable_run_ids"], ["target-run"])
        self.assertEqual(report["rejected_runs"], [])

    def test_run_id_selection_fails_when_missing(self):
        result, report = self.run_validator(
            [self.valid_summary("run-a")],
            "--run-id",
            "missing-run",
            "--mode",
            "summary",
            "--strict",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIsNone(report)
        self.assertIn(
            "expected exactly one summary row for run_id 'missing-run', found 0",
            result.stderr,
        )

    def test_run_id_selection_fails_when_duplicate(self):
        result, report = self.run_validator(
            [self.valid_summary("run-a"), self.valid_summary("run-a")],
            "--run-id",
            "run-a",
            "--mode",
            "summary",
            "--strict",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIsNone(report)
        self.assertIn(
            "expected exactly one summary row for run_id 'run-a', found 2",
            result.stderr,
        )

    def test_single_valid_summary_fails_comparability_mode(self):
        result, report = self.run_validator(
            [self.valid_summary()],
            "--mode",
            "comparability",
            "--strict",
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["summary_validation_status"], "pass")
        self.assertEqual(report["comparability_validation_status"], "fail")

    def test_single_invalid_summary_fails_summary_mode(self):
        row = self.valid_summary()
        row["summary_status"] = "partial"

        result, report = self.run_validator([row], "--mode", "summary", "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["summary_validation_status"], "fail")
        self.assertIn("summary_status_not_complete", report["rejected_runs"][0]["reasons"])

    def test_short_duration_fails_quality_bar(self):
        row = self.valid_summary()
        row["duration_seconds"] = 1199

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["comparability_status"], "fail")
        self.assertIn("duration_seconds_below_min:1199<1200", report["rejected_runs"][0]["reasons"])

    def test_low_coverage_fails_quality_bar(self):
        row = self.valid_summary()
        row["metrics_coverage_ratio"] = 0.94

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "metrics_coverage_ratio_below_min:0.94<0.95",
            report["rejected_runs"][0]["reasons"],
        )

    def test_partial_summary_status_fails(self):
        row = self.valid_summary()
        row["summary_status"] = "partial"

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertIn("summary_status_not_complete", report["rejected_runs"][0]["reasons"])

    def test_missing_baseline_labels_fail(self):
        row = self.valid_summary()
        row["machine_type"] = ""

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "missing_baseline_labels:machine_type",
            report["rejected_runs"][0]["reasons"],
        )

    def test_missing_normalized_metadata_fails(self):
        row = self.valid_summary()
        row["region"] = ""
        row["zone"] = ""
        row["pricing_model"] = ""

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "missing_baseline_labels:region,zone,pricing_model",
            report["rejected_runs"][0]["reasons"],
        )

    def test_invalid_node_count_fails(self):
        row = self.valid_summary()
        row["node_count"] = 0

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid_node_count", report["rejected_runs"][0]["reasons"])

    def test_invalid_pricing_model_fails(self):
        row = self.valid_summary()
        row["pricing_model"] = "preemptible"

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid_pricing_model", report["rejected_runs"][0]["reasons"])

    def test_nullable_cpu_platform_is_accepted(self):
        row_a = self.valid_summary("run-a")
        row_b = self.valid_summary("run-b")
        row_a["cpu_platform"] = None
        row_b["cpu_platform"] = None

        result, report = self.run_validator([row_a, row_b], "--strict")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["comparability_status"], "pass")

    def test_schema_extra_field_fails_as_drift(self):
        row = self.valid_summary()
        row["unexpected"] = "drift"

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertIn("schema_extra_fields:unexpected", report["rejected_runs"][0]["reasons"])

    def test_schema_missing_field_fails_as_drift(self):
        row = self.valid_summary()
        del row["frontend_latency_p99_ms"]

        result, report = self.run_validator([row, self.valid_summary("run-b")], "--strict")

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "schema_missing_fields:frontend_latency_p99_ms",
            report["rejected_runs"][0]["reasons"],
        )

    def test_nullable_future_fields_are_accepted(self):
        row_a = self.valid_summary("run-a")
        row_b = self.valid_summary("run-b")
        row_a["benchmark_compute_cost_usd"] = None
        row_a["cost_per_1m_requests_usd"] = None
        row_a["node_hourly_price_usd"] = None
        row_b["benchmark_compute_cost_usd"] = None
        row_b["cost_per_1m_requests_usd"] = None
        row_b["node_hourly_price_usd"] = None

        result, report = self.run_validator([row_a, row_b], "--strict")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["comparability_status"], "pass")

    def test_non_strict_mode_reports_fail_but_exits_zero(self):
        row = self.valid_summary()
        row["duration_seconds"] = 60

        result, report = self.run_validator([row])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["comparability_status"], "fail")

    def test_unscoped_comparability_still_fails_on_invalid_historical_rows(self):
        short_row = self.valid_summary("short-run")
        short_row["duration_seconds"] = 60

        result, report = self.run_validator(
            [short_row, self.valid_summary("run-b")],
            "--mode",
            "comparability",
            "--strict",
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["selected_run_id"], None)
        self.assertEqual(report["source_total_rows"], 2)
        self.assertEqual(report["comparability_status"], "fail")
        self.assertIn(
            "duration_seconds_below_min:60<1200",
            report["rejected_runs"][0]["reasons"],
        )


if __name__ == "__main__":
    unittest.main()
