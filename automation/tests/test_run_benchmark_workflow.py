"""Tests for test run benchmark workflow."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOMATION_LIB = REPO_ROOT / "automation" / "lib"
sys.path.insert(0, str(AUTOMATION_LIB))

from silicon_boutique_automation.command import CommandResult
from silicon_boutique_automation import unified_workflow


class FakeRunner:
    """Test double that records runner interactions.
    """
    def __init__(self, *, fail_gh_version=False, ambiguous_runs=False, failing_run=False):
        """Initialize the object with the provided configuration.


        Args:
            fail_gh_version: fail GitHub version used by this operation.
            ambiguous_runs: ambiguous runs used by this operation.
            failing_run: failing run used by this operation.

        Returns:
            None.
        """
        self.commands = []
        self.fail_gh_version = fail_gh_version
        self.ambiguous_runs = ambiguous_runs
        self.failing_run = failing_run

    def run(self, command, *, cwd=None, env=None):
        """Run the configured operation.


        Args:
            command: command used by this operation.
            cwd: cwd used by this operation.
            env: environment used by this operation.

        Returns:
            Result produced by run.
        """
        rendered = [str(part) for part in command]
        self.commands.append(rendered)
        joined = " ".join(rendered)
        if rendered[:2] == ["gh", "--version"]:
            if self.fail_gh_version:
                return CommandResult(127, "", "gh: command not found token=secret-value")
            return CommandResult(0, "gh version 2.0.0", "")
        if rendered[:3] == ["gh", "auth", "status"]:
            return CommandResult(0, "Logged in", "")
        if rendered[:3] == ["gh", "workflow", "view"]:
            return CommandResult(0, "workflow", "")
        if rendered[:3] == ["gh", "workflow", "run"]:
            return CommandResult(0, "", "")
        if rendered[:3] == ["gh", "run", "list"]:
            rows = [
                {
                    "databaseId": 12345,
                    "url": "https://github.example/runs/12345",
                    "status": "queued",
                    "conclusion": "",
                    "createdAt": "2026-05-14T21:00:00Z",
                    "headBranch": "main",
                }
            ]
            if self.ambiguous_runs:
                rows.append({**rows[0], "databaseId": 12346})
            return CommandResult(0, json.dumps(rows), "")
        if rendered[:3] == ["gh", "run", "view"]:
            conclusion = "failure" if self.failing_run else "success"
            return CommandResult(
                0,
                json.dumps(
                    {
                        "databaseId": int(rendered[3]),
                        "url": f"https://github.example/runs/{rendered[3]}",
                        "status": "completed",
                        "conclusion": conclusion,
                    }
                ),
                "",
            )
        if rendered[:3] == ["gh", "run", "download"]:
            output_dir = Path(rendered[rendered.index("--dir") + 1])
            write_cloud_artifacts(output_dir)
            return CommandResult(0, "downloaded", "")
        if "automation/scripts/run_local_benchmark_workflow.py" in joined:
            run_id = rendered[rendered.index("--run-id") + 1]
            root = Path(rendered[rendered.index("--artifacts-root") + 1])
            write_local_artifacts(root / run_id, run_id, with_workflow_report=True)
            return CommandResult(0, "local ok", "")
        if "automation/scripts/run_local_benchmark.py" in joined:
            run_id = rendered[rendered.index("--run-id") + 1]
            artifacts = Path(rendered[rendered.index("--artifacts-dir") + 1])
            write_local_artifacts(artifacts, run_id, with_workflow_report=False)
            return CommandResult(0, "local ok", "")
        if "automation/scripts/run_acceptance_matrix.py" in joined:
            output_dir = Path(rendered[rendered.index("--artifacts-dir") + 1])
            write_json(output_dir / "acceptance-matrix-report.json", {"status": "passed"})
            return CommandResult(0, "matrix ok", "")
        if "automation/scripts/launch_metrics_dashboard.py" in joined:
            output_dir = Path(rendered[rendered.index("--output-dir") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            write_json(output_dir / "dashboard-data.json", {"source": "test"})
            return CommandResult(0, "Dashboard files written", "")
        return CommandResult(0, "ok", "")


class UnifiedBenchmarkWorkflowTest(unittest.TestCase):
    """Unit tests covering unified Benchmark Workflow behavior.
    """
    def test_local_target_default_run_id_uses_local_smoke_prefix(self):
        """Verify local target default run ID uses local smoke prefix.


        Returns:
            None.
        """
        args = unified_workflow.parse_args(["--target", "local"])
        config = unified_workflow.config_from_args(args, environ={})

        self.assertRegex(config.run_id, r"^local-smoke-[0-9]{8}-[0-9]{6}$")
        self.assertLessEqual(len(config.run_id), 46)

    def test_cloud_target_default_run_id_keeps_unified_prefix(self):
        """Verify cloud target default run ID keeps unified prefix.


        Returns:
            None.
        """
        args = unified_workflow.parse_args(["--target", "gcp"])
        config = unified_workflow.config_from_args(args, environ={})

        self.assertRegex(config.run_id, r"^unified-[0-9]{8}-[0-9]{6}$")
        self.assertLessEqual(len(config.run_id), 46)

    def test_local_target_uses_existing_local_workflow_and_generate_only_dashboard(self):
        """Verify local target uses existing local workflow and generate only dashboard.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = write_env_file(Path(tmpdir))
            workflow, runner = make_workflow(
                tmpdir,
                "--target",
                "local",
                "--run-id",
                "unified-local",
                "--bigquery-env-file",
                str(env_file),
            )

            self.assertEqual(workflow.run(), 0)

            commands = command_strings(runner)
            local_command = next(command for command in commands if "run_local_benchmark_workflow.py" in command)
            self.assertIn("--credential-env-file", local_command)
            self.assertIn("--extra-run-local-arg=--machine-type", local_command)
            dashboard_command = next(command for command in commands if "launch_metrics_dashboard.py" in command)
            self.assertIn("--no-serve --no-browser", dashboard_command)
            self.assertIn("--summary-store", dashboard_command)
            report = read_json(workflow.report_path)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["provider_results"]["local"]["run_id"], "unified-local")

    def test_gcp_target_dispatches_workflow_without_cloud_terraform(self):
        """Verify GCP target dispatches workflow without cloud Terraform.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = write_env_file(Path(tmpdir))
            workflow, runner = make_workflow(
                tmpdir,
                "--target",
                "gcp",
                "--run-id",
                "unified-gcp",
                "--bigquery-env-file",
                str(env_file),
            )

            self.assertEqual(workflow.run(), 0)

            commands = command_strings(runner)
            dispatch = next(command for command in commands if command.startswith("gh workflow run"))
            self.assertIn("benchmark.yml", dispatch)
            self.assertIn("-f acceptance_demo=true", dispatch)
            self.assertIn("-f failure_stage=none", dispatch)
            self.assertNotIn("terraform apply", "\n".join(commands))
            self.assertIn("gh run download 12345", "\n".join(commands))
            report = read_json(workflow.report_path)
            self.assertEqual(report["provider_results"]["gcp"]["run_id"], "gha-12345-1")

    def test_aws_target_passes_secondary_zone(self):
        """Verify AWS target passes secondary zone.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = write_env_file(Path(tmpdir))
            workflow, runner = make_workflow(
                tmpdir,
                "--target",
                "aws",
                "--run-id",
                "unified-aws",
                "--secondary-zone",
                "us-east-1c",
                "--bigquery-env-file",
                str(env_file),
                "--no-wait",
                "--dashboard",
                "skip",
            )

            self.assertEqual(workflow.run(), 0)

            dispatch = next(command for command in command_strings(runner) if command.startswith("gh workflow run"))
            self.assertIn("benchmark-aws.yml", dispatch)
            self.assertIn("-f secondary_zone=us-east-1c", dispatch)
            self.assertIn("-f bigquery_project_id=example-project", dispatch)
            report = read_json(workflow.report_path)
            self.assertEqual(report["status"], "dispatched")

    def test_all_target_runs_matrix_over_downloaded_artifacts(self):
        """Verify all target runs matrix over downloaded artifacts.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = write_env_file(Path(tmpdir))
            workflow, runner = make_workflow(
                tmpdir,
                "--target",
                "all",
                "--run-id",
                "unified-all",
                "--bigquery-env-file",
                str(env_file),
                "--dashboard",
                "skip",
            )

            self.assertEqual(workflow.run(), 0)

            commands = command_strings(runner)
            self.assertEqual(sum("gh workflow run" in command for command in commands), 2)
            matrix = [command for command in commands if "run_acceptance_matrix.py" in command][-1]
            self.assertIn("--local-artifacts", matrix)
            self.assertIn("--gcp-artifacts", matrix)
            self.assertIn("--aws-artifacts", matrix)
            report = read_json(workflow.report_path)
            self.assertEqual(report["acceptance_matrix"]["status"], "passed")

    def test_cloud_target_requires_bigquery_settings_before_gh_preflight(self):
        """Verify cloud target requires BigQuery settings before GitHub preflight.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow, runner = make_workflow(
                tmpdir,
                "--target",
                "gcp",
                "--run-id",
                "missing-bq",
                "--bigquery-env-file",
                str(Path(tmpdir) / "missing.env"),
            )

            with contextlib.redirect_stderr(io.StringIO()):
                result = workflow.run()

            self.assertEqual(result, 2)
            self.assertEqual(runner.commands, [])
            report = read_json(workflow.report_path)
            self.assertEqual(report["error"]["failed_step"], "bigquery-config")

    def test_missing_gh_writes_redacted_failure_report(self):
        """Verify missing GitHub writes redacted failure report.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = write_env_file(Path(tmpdir))
            workflow, _ = make_workflow(
                tmpdir,
                "--target",
                "gcp",
                "--run-id",
                "missing-gh",
                "--bigquery-env-file",
                str(env_file),
                runner=FakeRunner(fail_gh_version=True),
            )

            with contextlib.redirect_stderr(io.StringIO()):
                result = workflow.run()

            self.assertEqual(result, 2)
            report = read_json(workflow.report_path)
            self.assertEqual(report["error"]["failed_step"], "gh-version")
            self.assertNotIn("secret-value", json.dumps(report))

    def test_ambiguous_cloud_run_lookup_fails(self):
        """Verify ambiguous cloud run lookup fails.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = write_env_file(Path(tmpdir))
            workflow, _ = make_workflow(
                tmpdir,
                "--target",
                "gcp",
                "--run-id",
                "ambiguous-gh",
                "--bigquery-env-file",
                str(env_file),
                runner=FakeRunner(ambiguous_runs=True),
            )

            with contextlib.redirect_stderr(io.StringIO()):
                result = workflow.run()

            self.assertEqual(result, 2)
            report = read_json(workflow.report_path)
            self.assertEqual(report["error"]["failed_step"], "gh-run-list")

    def test_invalid_local_pricing_model_is_rejected(self):
        """Verify invalid local pricing model is rejected.


        Returns:
            None.
        """
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                unified_workflow.parse_args(
                    ["--target", "local", "--pricing-model", "spot"]
                )


def make_workflow(tmpdir, *extra_args, runner=None):
    """Compute make workflow.


    Args:
        tmpdir: tmpdir used by this operation.
        extra_args: extra arguments used by this operation.
        runner: runner used by this operation.

    Returns:
        Result produced by make workflow.
    """
    args = unified_workflow.parse_args(
        [
            "--artifacts-root",
            str(Path(tmpdir) / "artifacts"),
            "--poll-interval-seconds",
            "1",
            "--workflow-timeout-seconds",
            "5",
            *extra_args,
        ]
    )
    config = unified_workflow.config_from_args(args, environ={})
    runner = runner or FakeRunner()
    return unified_workflow.UnifiedBenchmarkWorkflow(config, runner=runner, environ={}), runner


def write_env_file(base):
    """Write environment file.


    Args:
        base: base used by this operation.

    Returns:
        Result produced by write environment file.
    """
    path = base / "credential.env"
    path.write_text(
        "\n".join(
            [
                "PROJECT_ID=example-project",
                "BIGQUERY_DATASET=silicon_boutique",
                "BIGQUERY_TABLE=benchmark_summaries",
                "BIGQUERY_LOCATION=US",
            ]
        ),
        encoding="utf-8",
    )
    return path


def write_local_artifacts(path, run_id, *, with_workflow_report):
    """Write local artifacts.


    Args:
        path: path used by this operation.
        run_id: run ID used by this operation.
        with_workflow_report: with workflow report used by this operation.

    Returns:
        None.
    """
    path.mkdir(parents=True, exist_ok=True)
    write_json(path / "benchmark-summary.json", {"run_id": run_id, "summary_status": "complete"})
    (path / "benchmark-summaries.ndjson").write_text(
        json.dumps({"run_id": run_id, "summary_status": "complete"}) + "\n",
        encoding="utf-8",
    )
    (path / "teardown-status.env").write_text(
        "destroy_attempted=true\ndestroy_succeeded=true\n",
        encoding="utf-8",
    )
    if with_workflow_report:
        write_json(
            path / "local-workflow-report.json",
            {
                "status": "validated",
                "run_id": run_id,
                "bigquery": {"validated_row": {"run_id": run_id, "summary_status": "complete"}},
            },
        )


def write_cloud_artifacts(path):
    """Write cloud artifacts.


    Args:
        path: path used by this operation.

    Returns:
        None.
    """
    path.mkdir(parents=True, exist_ok=True)
    write_json(path / "workflow-trace.json", {"benchmark": {"run_id": "gha-12345-1"}})
    write_json(path / "benchmark-summary.json", {"run_id": "gha-12345-1", "summary_status": "complete"})
    write_json(path / "bigquery-load-report.json", {"status": "loaded", "run_ids": ["gha-12345-1"]})
    write_json(path / "acceptance-demo-report.json", {"status": "passed"})
    write_json(path / "comparability-report.json", {"summary_validation_status": "pass"})
    (path / "teardown-status.env").write_text(
        "destroy_attempted=true\ndestroy_succeeded=true\n",
        encoding="utf-8",
    )


def write_json(path, payload):
    """Write jSON.


    Args:
        path: path used by this operation.
        payload: payload used by this operation.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path):
    """Read jSON.


    Args:
        path: path used by this operation.

    Returns:
        Result produced by read JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def command_strings(runner):
    """Compute command strings.


    Args:
        runner: runner used by this operation.

    Returns:
        Result produced by command strings.
    """
    return [" ".join(command) for command in runner.commands]


if __name__ == "__main__":
    unittest.main()
