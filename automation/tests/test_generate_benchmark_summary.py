import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTRACT_SCRIPT = REPO_ROOT / "automation" / "scripts" / "extract_prometheus_metrics.py"
SUMMARY_SCRIPT = REPO_ROOT / "automation" / "scripts" / "generate_benchmark_summary.py"
PROMETHEUS_FIXTURES = REPO_ROOT / "automation" / "tests" / "fixtures" / "prometheus"
LOADGENERATOR_FIXTURE = (
    REPO_ROOT / "automation" / "tests" / "fixtures" / "loadgenerator" / "stats.json"
)


class GenerateBenchmarkSummaryTest(unittest.TestCase):
    def make_metrics_payload(self):
        result = subprocess.run(
            [
                sys.executable,
                str(EXTRACT_SCRIPT),
                "--fixture-dir",
                str(PROMETHEUS_FIXTURES),
                "--run-id",
                "test-run",
                "--namespace",
                "sb-test",
                "--start",
                "2026-05-07T12:00:00Z",
                "--end",
                "2026-05-07T12:01:00Z",
                "--step",
                "15s",
                "--strict",
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return json.loads(result.stdout)

    def run_summary(self, tmpdir, metrics_payload, *extra_args):
        metrics_input = Path(tmpdir) / "prometheus-metrics.json"
        summary_output = Path(tmpdir) / "benchmark-summary.json"
        summary_store = Path(tmpdir) / "benchmark-summaries.ndjson"
        loadgenerator_stats = Path(tmpdir) / "loadgenerator-stats.json"
        metrics_input.write_text(json.dumps(metrics_payload), encoding="utf-8")
        loadgenerator_stats.write_text(
            json.dumps(
                {
                    "run_id": metrics_payload["run_id"],
                    "request_count_total": 300,
                    "request_success_count": 295,
                    "request_failure_count": 5,
                    "avg_requests_per_second": 5.0,
                    "parse_status": "parsed",
                }
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SUMMARY_SCRIPT),
                "--metrics-input",
                str(metrics_input),
                "--summary-output",
                str(summary_output),
                "--summary-store",
                str(summary_store),
                "--environment",
                "local",
                "--machine-type",
                "minikube",
                "--processor-family",
                "local-dev",
                "--architecture",
                "x86_64",
                "--cloud-provider",
                "local",
                "--loadgenerator-stats",
                str(loadgenerator_stats),
                "--node-count",
                "1",
                "--concurrent-users",
                "10",
                "--users-per-second",
                "1",
                "--load-profile-source",
                "manual",
                "--generated-at",
                "2026-05-07T12:02:00Z",
                *extra_args,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result, summary_output, summary_store

    def test_generates_deterministic_summary_and_store_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, summary_output, summary_store = self.run_summary(
                tmpdir,
                self.make_metrics_payload(),
                "--strict",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(summary_output.read_text(encoding="utf-8"))
            rows = [
                json.loads(line)
                for line in summary_store.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(rows, [summary])
            self.assertEqual(summary["run_id"], "test-run")
            self.assertEqual(summary["summary_status"], "complete")
            self.assertEqual(summary["duration_seconds"], 60)
            self.assertEqual(summary["generated_at"], "2026-05-07T12:02:00Z")
            self.assertEqual(summary["region"], "local")
            self.assertEqual(summary["zone"], "local")
            self.assertEqual(summary["node_count"], 1)
            self.assertEqual(summary["pricing_model"], "local")
            self.assertIsNone(summary["cpu_platform"])
            self.assertAlmostEqual(summary["avg_cpu_usage_cores"], 1.9)
            self.assertAlmostEqual(summary["avg_cpu_utilization_pct"], 47.5)
            self.assertAlmostEqual(summary["max_cpu_utilization_pct"], 62.5)
            self.assertAlmostEqual(summary["max_memory_used_gb"], 0.000002)
            self.assertAlmostEqual(summary["frontend_latency_p99_ms"], 492.0)
            self.assertEqual(summary["request_count_total"], 300)
            self.assertEqual(summary["request_success_count"], 295)
            self.assertEqual(summary["request_failure_count"], 5)
            self.assertAlmostEqual(summary["avg_requests_per_second"], 5.0)
            self.assertEqual(summary["load_concurrent_users"], 10)
            self.assertAlmostEqual(summary["load_users_per_second"], 1.0)
            self.assertEqual(summary["load_profile_source"], "manual")
            self.assertIsNone(summary["node_hourly_price_usd"])
            self.assertIsNone(summary["benchmark_compute_cost_usd"])
            self.assertIsNone(summary["cost_per_1m_requests_usd"])

    def test_priced_run_calculates_cost_per_million_requests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pricing = Path(tmpdir) / "pricing.json"
            pricing.write_text(
                json.dumps(
                    {
                        "prices": [
                            {
                                "cloud_provider": "gcp",
                                "region": "us-central1",
                                "machine_type": "e2-standard-4",
                                "pricing_model": "spot",
                                "hourly_usd": 0.03,
                                "currency": "USD",
                                "source_note": "test",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result, summary_output, _ = self.run_summary(
                tmpdir,
                self.make_metrics_payload(),
                "--environment",
                "gcp",
                "--machine-type",
                "e2-standard-4",
                "--cloud-provider",
                "gcp",
                "--region",
                "us-central1",
                "--zone",
                "us-central1-a",
                "--node-count",
                "2",
                "--pricing-model",
                "spot",
                "--cpu-platform",
                "intel-sapphire-rapids",
                "--pricing-table",
                str(pricing),
                "--strict",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(summary_output.read_text(encoding="utf-8"))
            self.assertEqual(summary["region"], "us-central1")
            self.assertEqual(summary["zone"], "us-central1-a")
            self.assertEqual(summary["node_count"], 2)
            self.assertEqual(summary["pricing_model"], "spot")
            self.assertEqual(summary["cpu_platform"], "intel-sapphire-rapids")
            self.assertAlmostEqual(summary["node_hourly_price_usd"], 0.03)
            self.assertAlmostEqual(summary["benchmark_compute_cost_usd"], 0.001)
            self.assertAlmostEqual(summary["cost_per_1m_requests_usd"], 3.38983051)

    def test_duplicate_run_id_fails_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            first, _, _ = self.run_summary(tmpdir, metrics_payload, "--strict")
            second, _, _ = self.run_summary(tmpdir, metrics_payload, "--strict")

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 2)
            self.assertIn("already contains run_id", second.stderr)

    def test_replace_updates_existing_store_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            first, _, summary_store = self.run_summary(tmpdir, metrics_payload, "--strict")
            updated_payload = self.make_metrics_payload()
            updated_payload["metrics"]["cpu_usage_cores"]["avg"] = 3.25
            second, summary_output, _ = self.run_summary(
                tmpdir,
                updated_payload,
                "--strict",
                "--replace",
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            rows = [
                json.loads(line)
                for line in summary_store.read_text(encoding="utf-8").splitlines()
            ]
            summary = json.loads(summary_output.read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0], summary)
            self.assertAlmostEqual(summary["avg_cpu_usage_cores"], 3.25)

    def test_strict_mode_fails_on_partial_metric_quality(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            metrics_payload["quality"]["missing_series"] = ["cpu_usage_cores"]

            result, _, _ = self.run_summary(tmpdir, metrics_payload, "--strict")

            self.assertEqual(result.returncode, 2)
            self.assertIn("required metric quality checks failed", result.stderr)

    def test_non_strict_mode_emits_partial_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            metrics_payload["quality"]["empty_series"] = ["frontend_probe_latency_seconds"]

            result, summary_output, _ = self.run_summary(tmpdir, metrics_payload)

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(summary_output.read_text(encoding="utf-8"))
            self.assertEqual(summary["summary_status"], "partial")

    def test_non_strict_mode_marks_missing_derived_fields_partial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            metrics_payload["metrics"]["frontend_probe_latency_seconds"]["p99"] = None

            result, summary_output, _ = self.run_summary(tmpdir, metrics_payload)

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(summary_output.read_text(encoding="utf-8"))
            self.assertEqual(summary["summary_status"], "partial")
            self.assertIsNone(summary["frontend_latency_p99_ms"])

    def test_coverage_above_minimum_is_complete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            metrics_payload["quality"]["coverage_ratio"] = 0.99

            result, summary_output, _ = self.run_summary(
                tmpdir,
                metrics_payload,
                "--min-coverage-ratio",
                "0.95",
                "--strict",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(summary_output.read_text(encoding="utf-8"))
            self.assertEqual(summary["summary_status"], "complete")

    def test_coverage_below_minimum_is_partial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            metrics_payload["quality"]["coverage_ratio"] = 0.94

            result, summary_output, _ = self.run_summary(
                tmpdir,
                metrics_payload,
                "--min-coverage-ratio",
                "0.95",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(summary_output.read_text(encoding="utf-8"))
            self.assertEqual(summary["summary_status"], "partial")

    def test_invalid_min_coverage_ratio_fails_argument_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _, _ = self.run_summary(
                tmpdir,
                self.make_metrics_payload(),
                "--min-coverage-ratio",
                "1.1",
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("--min-coverage-ratio must be between 0 and 1", result.stderr)

    def test_strict_mode_fails_when_cpu_utilization_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            metrics_payload["metrics"]["cpu_utilization_pct"]["avg"] = None

            result, _, _ = self.run_summary(tmpdir, metrics_payload, "--strict")

            self.assertEqual(result.returncode, 2)
            self.assertIn("avg_cpu_utilization_pct", result.stderr)

    def test_strict_mode_fails_when_cpu_utilization_is_impossible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_payload = self.make_metrics_payload()
            metrics_payload["metrics"]["cpu_utilization_pct"]["max"] = 150.0

            result, _, _ = self.run_summary(tmpdir, metrics_payload, "--strict")

            self.assertEqual(result.returncode, 2)
            self.assertIn("CPU utilization fields are outside the expected range", result.stderr)

    def test_strict_priced_run_fails_when_pricing_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pricing = Path(tmpdir) / "pricing.json"
            pricing.write_text(json.dumps({"prices": []}), encoding="utf-8")

            result, _, _ = self.run_summary(
                tmpdir,
                self.make_metrics_payload(),
                "--environment",
                "gcp",
                "--cloud-provider",
                "gcp",
                "--region",
                "us-central1",
                "--zone",
                "us-central1-a",
                "--pricing-table",
                str(pricing),
                "--strict",
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("required pricing fields are missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
