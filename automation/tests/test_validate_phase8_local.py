import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "validate_phase8_local.py"
SCHEMA = REPO_ROOT / "automation" / "templates" / "benchmark-summary.schema.json"

sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("validate_phase8_local", SCRIPT)
validate_phase8_local = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validate_phase8_local
spec.loader.exec_module(validate_phase8_local)


class FakeRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command, cwd):
        rendered = [str(part) for part in command]
        self.commands.append({"command": rendered, "cwd": str(cwd)})
        return validate_phase8_local.CommandResult(0, "", "")


class ValidatePhase8LocalTest(unittest.TestCase):
    def test_uses_existing_store_when_two_comparable_rows_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            summary_store = base / "benchmark-summaries.ndjson"
            write_ndjson(summary_store, validate_phase8_local.comparable_fixture_rows()[:2])
            runner = FakeRunner()

            result = run_validation(base, summary_store, runner)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["summary_source"], "existing")
            self.assertEqual(result["comparability_status"], "pass")
            self.assertEqual(result["comparison_status"], "warn")
            self.assertEqual(result["comparable_run_ids"], ["phase8-local-fast-001", "phase8-local-fast-002"])
            valid_rows = read_ndjson(base / "phase8" / "benchmark-summaries-valid.ndjson")
            mixed_rows = read_ndjson(base / "phase8" / "benchmark-summaries-mixed.ndjson")
            self.assertEqual(len(valid_rows), 2)
            self.assertEqual(len(mixed_rows), 3)
            self.assertNoCloudCommands(runner.commands)

    def test_falls_back_to_deterministic_fixtures_for_legacy_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            summary_store = base / "benchmark-summaries.ndjson"
            write_ndjson(summary_store, [{"run_id": "legacy-local-smoke"}])
            runner = FakeRunner()

            result = run_validation(base, summary_store, runner)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["summary_source"], "fixture")
            self.assertIn("found 0 comparable P8.1 rows", result["summary_source_reason"])
            self.assertEqual(result["comparability_status"], "pass")
            comparison = read_json(base / "phase8" / "comparison-report.json")
            self.assertEqual(comparison["status"], "warn")
            self.assertEqual(comparison["comparison_group_count"], 2)
            self.assertEqual(comparison["rejected_runs"][0]["run_id"], "phase8-local-partial-001")
            self.assertIn(
                "summary_status_not_complete",
                comparison["rejected_runs"][0]["reasons"],
            )
            self.assertTrue((base / "phase8-existing-comparability-check.json").exists())
            self.assertNoCloudCommands(runner.commands)

    def test_outputs_passing_comparability_and_deterministic_rankings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            summary_store = base / "missing.ndjson"
            runner = FakeRunner()

            result = run_validation(base, summary_store, runner)

            self.assertEqual(result["status"], "pass")
            comparability = read_json(base / "phase8" / "comparability-report.json")
            comparison = read_json(base / "phase8" / "comparison-report.json")
            markdown = (base / "phase8" / "comparison-report.md").read_text(encoding="utf-8")
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
            self.assertIn("phase8-local-partial-001", markdown)

    def assertNoCloudCommands(self, commands):
        rendered = [" ".join(item["command"]) for item in commands]
        for item in commands:
            self.assertNotIn(item["command"][0], {"aws", "bq", "gcloud"})
        self.assertFalse(any("terraform apply" in command for command in rendered))
        self.assertFalse(any("terraform destroy" in command for command in rendered))


def run_validation(base, summary_store, runner):
    config = validate_phase8_local.ValidationConfig(
        summary_store=summary_store,
        artifacts_dir=base / "phase8",
        schema=SCHEMA,
        repo_root=REPO_ROOT,
    )
    return validate_phase8_local.run_validation(config, runner=runner)


def write_ndjson(path, rows):
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_ndjson(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
