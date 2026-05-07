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
        metrics_input.write_text(json.dumps(metrics_payload), encoding="utf-8")

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
            self.assertAlmostEqual(summary["avg_cpu_usage_cores"], 1.9)
            self.assertAlmostEqual(summary["max_memory_used_gb"], 0.000002)
            self.assertAlmostEqual(summary["frontend_latency_p99_ms"], 492.0)
            self.assertIsNone(summary["avg_cpu_utilization_pct"])
            self.assertIsNone(summary["cost_per_1m_requests_usd"])

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


if __name__ == "__main__":
    unittest.main()
