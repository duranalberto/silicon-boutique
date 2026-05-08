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
    def test_parses_aggregate_locust_stats(self):
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
            self.assertEqual(payload["parse_status"], "parsed")

    def test_strict_mode_fails_when_aggregate_row_is_missing(self):
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
