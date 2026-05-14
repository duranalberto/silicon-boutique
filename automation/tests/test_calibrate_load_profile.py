"""Tests for test calibrate load profile."""

import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "calibrate_load_profile.py"

spec = importlib.util.spec_from_file_location("calibrate_load_profile", SCRIPT)
calibrate_load_profile = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = calibrate_load_profile
spec.loader.exec_module(calibrate_load_profile)


class CalibrateLoadProfileTest(unittest.TestCase):
    """Unit tests covering calibrate Load Profile behavior.
    """
    def run_calibration(self, trials):
        """Run calibration.


        Args:
            trials: trials used by this operation.

        Returns:
            Result produced by run calibration.
        """
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        base = Path(tmpdir.name)
        fixture = base / "trials.json"
        output = base / "calibration.json"
        fixture.write_text(json.dumps(trials), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--fixture-trials",
                str(fixture),
                "--output",
                str(output),
                "--initial-concurrent-users",
                "10",
                "--initial-users-per-second",
                "1",
                "--cooldown-seconds",
                "0",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result, json.loads(output.read_text(encoding="utf-8"))

    def test_increases_load_then_accepts_target_band(self):
        """Verify increases load then accepts target band.


        Returns:
            None.
        """
        result, report = self.run_calibration(
            [
                {"avg_cpu_utilization_pct": 60.0},
                {"avg_cpu_utilization_pct": 84.0},
            ]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["status"], "selected")
        self.assertEqual(report["trials"][0]["decision"], "increase_load")
        self.assertEqual(report["selected_profile"]["load_concurrent_users"], 15)
        self.assertAlmostEqual(report["selected_profile"]["load_users_per_second"], 1.5)

    def test_decreases_load_when_above_target_band(self):
        """Verify decreases load when above target band.


        Returns:
            None.
        """
        result, report = self.run_calibration(
            [
                {"avg_cpu_utilization_pct": 96.0},
                {"avg_cpu_utilization_pct": 86.0},
            ]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["trials"][0]["decision"], "decrease_load")
        self.assertEqual(report["selected_profile"]["load_concurrent_users"], 8)

    def test_rejects_trial_with_excessive_failures(self):
        """Verify rejects trial with excessive failures.


        Returns:
            None.
        """
        result, report = self.run_calibration(
            [
                {"avg_cpu_utilization_pct": 85.0, "request_failure_ratio": 0.2},
                {"avg_cpu_utilization_pct": 84.0, "request_failure_ratio": 0.0},
            ]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["trials"][0]["decision"], "reject_failures")
        self.assertEqual(report["selected_profile"]["load_profile_source"], "calibration")
        self.assertIn("source_run_id", report["selected_profile"])

    def test_local_execution_mode_is_accepted_by_parser(self):
        """Verify local execution mode is accepted by parser.


        Returns:
            None.
        """
        args = calibrate_load_profile.parse_args(
            [
                "--execute-local",
                "--output",
                "calibration.json",
                "--max-trials",
                "1",
            ]
        )

        self.assertTrue(args.execute_local)

    def test_gcp_workflow_command_uses_trial_load_settings(self):
        """Verify GCP workflow command uses trial load settings.


        Returns:
            None.
        """
        args = calibrate_load_profile.parse_args(
            [
                "--execute-gcp",
                "--output",
                "calibration.json",
                "--project-id",
                "example-project",
                "--machine-type",
                "e2-standard-4",
                "--processor-family",
                "e2",
            ]
        )

        command = calibrate_load_profile.gcp_workflow_command(
            args=args,
            run_id="calibration-1",
            concurrent_users=42,
            users_per_second=4.5,
        )

        self.assertEqual(command[:3], ["gh", "workflow", "run"])
        self.assertIn("concurrent_users=42", command)
        self.assertIn("users_per_second=4.5", command)
        self.assertIn("load_profile_source=calibration", command)
        self.assertIn("machine_type=e2-standard-4", command)


if __name__ == "__main__":
    unittest.main()
