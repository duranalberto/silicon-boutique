"""Tests for test validate local comparison."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "automation" / "scripts"
SCHEMA = REPO_ROOT / "automation" / "templates" / "benchmark-summary.schema.json"

sys.path.insert(0, str(SCRIPTS_DIR))
import validate_local_comparison


class FakeRunner:
    """Test double that records runner interactions.
    """
    def __init__(self):
        """Initialize the object with the provided configuration.


        Returns:
            None.
        """
        self.commands = []

    def __call__(self, command, cwd):
        """Handle the object call using the supplied arguments.


        Args:
            command: command used by this operation.
            cwd: cwd used by this operation.

        Returns:
            Result produced by call.
        """
        rendered = [str(part) for part in command]
        self.commands.append({"command": rendered, "cwd": str(cwd)})
        return validate_local_comparison.CommandResult(0, "", "")


class ValidateLocalComparisonTest(unittest.TestCase):
    """Unit tests covering validate Local Comparison behavior.
    """
    def test_uses_existing_store_when_two_comparable_rows_exist(self):
        """Verify uses existing store when two comparable rows exist.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            summary_store = base / "benchmark-summaries.ndjson"
            write_ndjson(summary_store, validate_local_comparison.comparable_fixture_rows()[:2])
            runner = FakeRunner()

            result = run_validation(base, summary_store, runner)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["summary_source"], "existing")
            self.assertEqual(result["comparability_status"], "pass")
            self.assertEqual(result["comparison_status"], "warn")
            self.assertEqual(result["comparable_run_ids"], ["local-comparison-fast-001", "local-comparison-fast-002"])
            valid_rows = read_ndjson(base / "comparison" / "benchmark-summaries-valid.ndjson")
            mixed_rows = read_ndjson(base / "comparison" / "benchmark-summaries-mixed.ndjson")
            self.assertEqual(len(valid_rows), 2)
            self.assertEqual(len(mixed_rows), 3)
            self.assertNoCloudCommands(runner.commands)

    def test_falls_back_to_deterministic_fixtures_for_legacy_store(self):
        """Verify falls back to deterministic fixtures for legacy store.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            summary_store = base / "benchmark-summaries.ndjson"
            write_ndjson(summary_store, [{"run_id": "legacy-local-smoke"}])
            runner = FakeRunner()

            result = run_validation(base, summary_store, runner)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["summary_source"], "fixture")
            self.assertIn("found 0 comparable comparison-ready rows", result["summary_source_reason"])
            self.assertEqual(result["comparability_status"], "pass")
            comparison = read_json(base / "comparison" / "comparison-report.json")
            self.assertEqual(comparison["status"], "warn")
            self.assertEqual(comparison["comparison_group_count"], 2)
            self.assertEqual(comparison["rejected_runs"][0]["run_id"], "local-comparison-partial-001")
            self.assertIn(
                "summary_status_not_complete",
                comparison["rejected_runs"][0]["reasons"],
            )
            self.assertTrue((base / "local-existing-comparability-check.json").exists())
            self.assertNoCloudCommands(runner.commands)

    def test_outputs_passing_comparability_and_deterministic_rankings(self):
        """Verify outputs passing comparability and deterministic rankings.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            summary_store = base / "missing.ndjson"
            runner = FakeRunner()

            result = run_validation(base, summary_store, runner)

            self.assertEqual(result["status"], "pass")
            comparability = read_json(base / "comparison" / "comparability-report.json")
            comparison = read_json(base / "comparison" / "comparison-report.json")
            markdown = (base / "comparison" / "comparison-report.md").read_text(encoding="utf-8")
            self.assertEqual(comparability["comparability_status"], "pass")
            self.assertEqual(comparison["status"], "warn")
            self.assertEqual(
                comparison["rankings"]["avg_requests_per_second"][0]["machine_type"],
                "local-fast",
            )
            self.assertEqual(
                comparison["rankings"]["requests_per_cpu_core"][0]["machine_type"],
                "local-efficient",
            )
            self.assertIn("| Machine | Processor |", markdown)
            self.assertIn("local-comparison-partial-001", markdown)

    def assertNoCloudCommands(self, commands):
        """Assert that no Cloud Commands matches expectations.


        Args:
            commands: commands used by this operation.

        Returns:
            None.
        """
        rendered = [" ".join(item["command"]) for item in commands]
        for item in commands:
            self.assertNotIn(item["command"][0], {"aws", "bq", "gcloud"})
        self.assertFalse(any("terraform apply" in command for command in rendered))
        self.assertFalse(any("terraform destroy" in command for command in rendered))


def run_validation(base, summary_store, runner):
    """Run validation.


    Args:
        base: base used by this operation.
        summary_store: summary store used by this operation.
        runner: runner used by this operation.

    Returns:
        Result produced by run validation.
    """
    config = validate_local_comparison.ValidationConfig(
        summary_store=summary_store,
        artifacts_dir=base / "comparison",
        schema=SCHEMA,
        repo_root=REPO_ROOT,
    )
    return validate_local_comparison.run_validation(config, runner=runner)


def write_ndjson(path, rows):
    """Write nDJSON.


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


def read_ndjson(path):
    """Read nDJSON.


    Args:
        path: path used by this operation.

    Returns:
        Result produced by read NDJSON.
    """
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def read_json(path):
    """Read jSON.


    Args:
        path: path used by this operation.

    Returns:
        Result produced by read JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
