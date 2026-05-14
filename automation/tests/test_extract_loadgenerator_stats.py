"""Tests for test extract loadgenerator stats."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "extract_loadgenerator_stats.py"
FIXTURE = REPO_ROOT / "automation" / "tests" / "fixtures" / "loadgenerator" / "locust-summary.log"


class ExtractLoadgeneratorStatsTest(unittest.TestCase):
    """Unit tests covering extract Loadgenerator Stats behavior.
    """
    def test_parses_aggregate_locust_stats(self):
        """Verify parses aggregate Locust stats.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "loadgenerator-stats.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--logs-input",
                    str(FIXTURE),
                    "--output",
                    str(output),
                    "--run-id",
                    "test-run",
                    "--duration-seconds",
                    "60",
                    "--log-source",
                    "previous",
                    "--strict",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["run_id"], "test-run")
            self.assertEqual(payload["request_count_total"], 300)
            self.assertEqual(payload["request_success_count"], 295)
            self.assertEqual(payload["request_failure_count"], 5)
            self.assertAlmostEqual(payload["avg_requests_per_second"], 5.0)
            self.assertEqual(payload["log_source"], "previous")
            self.assertEqual(payload["aggregated_row_count"], 1)
            self.assertEqual(payload["request_rps_window_ratio"], 1.0)
            self.assertEqual(payload["parse_status"], "parsed")

    def test_uses_final_aggregate_row(self):
        """Verify the parser keeps the final aggregate row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = Path(tmpdir) / "logs.txt"
            output = Path(tmpdir) / "loadgenerator-stats.json"
            logs.write_text(
                "\n".join(
                    [
                        " Aggregated 10 0 | 1 1 1 1 | 1.00 0.00",
                        " Aggregated 120 2(1.67%) | 1 1 1 1 | 2.00 0.03",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--logs-input",
                    str(logs),
                    "--output",
                    str(output),
                    "--run-id",
                    "test-run",
                    "--duration-seconds",
                    "60",
                    "--strict",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["request_count_total"], 120)
            self.assertEqual(payload["aggregated_row_count"], 2)

    def test_strict_mode_fails_when_request_total_is_implausibly_low(self):
        """Verify strict mode rejects partial restarted loadgenerator logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = Path(tmpdir) / "logs.txt"
            output = Path(tmpdir) / "loadgenerator-stats.json"
            logs.write_text(
                " Aggregated 51 0 | 1 1 1 1 | 2.60 0.00\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--logs-input",
                    str(logs),
                    "--output",
                    str(output),
                    "--run-id",
                    "test-run",
                    "--duration-seconds",
                    "1200",
                    "--strict",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 2)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["parse_status"], "failed")
            self.assertIn("too low", payload["error"])

    def test_strict_mode_fails_when_aggregate_row_is_missing(self):
        """Verify strict mode fails when aggregate row is missing.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = Path(tmpdir) / "logs.txt"
            output = Path(tmpdir) / "loadgenerator-stats.json"
            logs.write_text("no locust table here\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--logs-input",
                    str(logs),
                    "--output",
                    str(output),
                    "--run-id",
                    "test-run",
                    "--strict",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 2)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["parse_status"], "failed")


if __name__ == "__main__":
    unittest.main()
