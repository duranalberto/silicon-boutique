import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "extract_prometheus_metrics.py"
FIXTURES = REPO_ROOT / "automation" / "tests" / "fixtures" / "prometheus"


class ExtractPrometheusMetricsTest(unittest.TestCase):
    def run_extractor(self, *extra_args):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--fixture-dir",
                str(FIXTURES),
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
                *extra_args,
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return json.loads(result.stdout)

    def test_extracts_deterministic_structured_metrics(self):
        payload = self.run_extractor()

        self.assertEqual(payload["run_id"], "test-run")
        self.assertEqual(payload["namespace"], "sb-test")
        self.assertEqual(payload["window"]["step_seconds"], 15)
        self.assertEqual(payload["quality"]["coverage_ratio"], 1.0)
        self.assertEqual(payload["quality"]["missing_series"], [])
        self.assertEqual(payload["quality"]["empty_series"], [])

        cpu = payload["metrics"]["cpu_usage_cores"]
        self.assertEqual(cpu["sample_count"], 5)
        self.assertEqual(cpu["unit"], "cores")
        self.assertAlmostEqual(cpu["avg"], 1.9)
        self.assertAlmostEqual(cpu["max"], 2.5)

        utilization = payload["metrics"]["cpu_utilization_pct"]
        self.assertEqual(utilization["sample_count"], 5)
        self.assertEqual(utilization["unit"], "percent")
        self.assertAlmostEqual(utilization["avg"], 47.5)
        self.assertAlmostEqual(utilization["max"], 62.5)

        latency = payload["metrics"]["frontend_probe_latency_seconds"]
        self.assertEqual(latency["sample_count"], 5)
        self.assertAlmostEqual(latency["p50"], 0.2)
        self.assertAlmostEqual(latency["p95"], 0.46)
        self.assertAlmostEqual(latency["p99"], 0.492)

    def test_strict_mode_fails_when_required_metric_is_empty(self):
        empty_fixture_dir = FIXTURES / "empty"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--fixture-dir",
                str(empty_fixture_dir),
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
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("required metrics are missing, empty, or invalid", result.stderr)

    def test_strict_mode_writes_output_before_failing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "metrics.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--fixture-dir",
                    str(FIXTURES / "empty"),
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
                    "--output",
                    str(output_path),
                    "--strict",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 2)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(
                payload["quality"]["missing_series"]
                or payload["quality"]["empty_series"]
            )


if __name__ == "__main__":
    unittest.main()
