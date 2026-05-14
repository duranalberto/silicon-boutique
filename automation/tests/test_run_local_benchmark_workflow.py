"""Tests for test run local benchmark workflow."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automation.scripts import run_local_benchmark_workflow


class FakeRunner:
    """Test double that records runner interactions.
    """
    def __init__(
        self,
        *,
        kubectl_failures=0,
        bigquery_rows=None,
        fail_steps=None,
    ):
        """Initialize the object with the provided configuration.


        Args:
            kubectl_failures: kubectl failures used by this operation.
            bigquery_rows: BigQuery rows used by this operation.
            fail_steps: fail steps used by this operation.

        Returns:
            None.
        """
        self.commands = []
        self.kubectl_failures = kubectl_failures
        self.bigquery_rows = bigquery_rows
        self.fail_steps = fail_steps or {}

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
        self.commands.append(
            {
                "command": rendered,
                "cwd": str(cwd) if cwd else None,
                "env": dict(env or {}),
            }
        )
        joined = " ".join(rendered)
        for prefix, result in self.fail_steps.items():
            if joined.startswith(prefix):
                return run_local_benchmark_workflow.CommandResult(
                    result[0],
                    result[1] if len(result) > 1 else "",
                    result[2] if len(result) > 2 else "",
                )
        if rendered[:3] == ["kubectl", "get", "nodes"]:
            if self.kubectl_failures > 0:
                self.kubectl_failures -= 1
                return run_local_benchmark_workflow.CommandResult(
                    1,
                    "",
                    "connect: no route to host",
                )
            return run_local_benchmark_workflow.CommandResult(0, "node ready", "")
        if rendered[0] == "bq":
            rows = self.bigquery_rows
            if rows is None:
                rows = [
                    {
                        "run_id": "local-smoke-20260511-201554",
                        "machine_type": "local",
                        "benchmark_start": "2026-05-11 20:24:27",
                        "benchmark_end": "2026-05-11 20:26:27",
                        "summary_status": "complete",
                    }
                ]
            return run_local_benchmark_workflow.CommandResult(0, json.dumps(rows), "")
        return run_local_benchmark_workflow.CommandResult(0, "ok", "")


class LocalBenchmarkWorkflowTest(unittest.TestCase):
    """Unit tests covering local Benchmark Workflow behavior.
    """
    def test_default_run_id_is_dns_safe(self):
        """Verify default run ID is dns safe.


        Returns:
            None.
        """
        run_id = run_local_benchmark_workflow.default_run_id()

        self.assertRegex(run_id, r"^local-smoke-[0-9]{8}-[0-9]{6}$")
        self.assertLessEqual(len(run_id), 46)

    def test_config_loads_bigquery_env_without_leaking_secret_values(self):
        """Verify config loads BigQuery environment without leaking secret values.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "credential.env"
            env_file.write_text(
                "\n".join(
                    [
                        "PROJECT_ID=example-project",
                        "BIGQUERY_DATASET=silicon_boutique",
                        "BIGQUERY_TABLE=benchmark_summaries",
                        "BIGQUERY_LOCATION=US",
                        "GOOGLE_APPLICATION_CREDENTIALS=/tmp/secret-key.json",
                    ]
                ),
                encoding="utf-8",
            )
            args = run_local_benchmark_workflow.parse_args(
                [
                    "--run-id",
                    "local-smoke-20260511-201554",
                    "--credential-env-file",
                    str(env_file),
                    "--artifacts-root",
                    str(Path(tmpdir) / "artifacts"),
                ]
            )
            config = run_local_benchmark_workflow.config_from_args(args, environ={})
            workflow = run_local_benchmark_workflow.LocalBenchmarkWorkflow(
                config,
                runner=FakeRunner(),
                environ={
                    "PROJECT_ID": "example-project",
                    "BIGQUERY_DATASET": "silicon_boutique",
                    "BIGQUERY_TABLE": "benchmark_summaries",
                    "BIGQUERY_LOCATION": "US",
                    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/secret-key.json",
                },
            )

            workflow.config.artifacts_dir.mkdir(parents=True)
            workflow.log_env_presence()

            log = workflow.workflow_log.read_text(encoding="utf-8")
            self.assertIn('"GOOGLE_APPLICATION_CREDENTIALS"', log)
            self.assertIn('"redacted": true', log)
            self.assertNotIn("/tmp/secret-key.json", log)

    def test_unreachable_kubernetes_runs_repair_then_benchmark(self):
        """Verify unreachable kubernetes runs repair then benchmark.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow, runner = make_workflow(tmpdir, runner=FakeRunner(kubectl_failures=1))

            result = workflow.run()

            self.assertEqual(result, 0)
            commands = command_strings(runner)
            self.assertCommandOrder(
                commands,
                [
                    ".devcontainer/verify-toolchain.sh",
                    "kubectl get nodes --context siliconboutique",
                    ".devcontainer/post-create.sh",
                    "kubectl get nodes --context siliconboutique",
                    "automation/scripts/load_benchmark_summary_to_bigquery.py",
                    "automation/scripts/run_local_benchmark.py",
                    "bq --format=json",
                ],
            )

    def test_skip_minikube_repair_fails_fast(self):
        """Verify skip minikube repair fails fast.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow, runner = make_workflow(
                tmpdir,
                extra_args=["--skip-minikube-repair"],
                runner=FakeRunner(kubectl_failures=1),
            )

            with contextlib.redirect_stderr(io.StringIO()):
                result = workflow.run()

            self.assertEqual(result, 2)
            commands = "\n".join(command_strings(runner))
            self.assertNotIn(".devcontainer/post-create.sh", commands)
            issue = json.loads(workflow.issue_path.read_text(encoding="utf-8"))
            self.assertEqual(issue["failed_step"], "kubectl-context-check")
            self.assertIn("post-create", issue["suggestion"])

    def test_local_benchmark_command_uses_bigquery_and_run_scoped_artifacts(self):
        """Verify local benchmark command uses BigQuery and run scoped artifacts.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow, runner = make_workflow(tmpdir)

            self.assertEqual(workflow.run(), 0)

            command = next(
                command
                for command in command_strings(runner)
                if "automation/scripts/run_local_benchmark.py" in command
            )
            self.assertIn("--run-id local-smoke-20260511-201554", command)
            self.assertIn("--artifacts-dir", command)
            self.assertIn("artifacts/local-smoke-20260511-201554", command)
            self.assertIn("--persist-bigquery", command)
            self.assertIn("--bigquery-env-file", command)
            self.assertIn("--test-duration 2m", command)
            self.assertIn("--min-duration-seconds 60", command)

    def test_bigquery_validation_success_writes_report(self):
        """Verify BigQuery validation success writes report.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow, _ = make_workflow(tmpdir)

            self.assertEqual(workflow.run(), 0)

            report = json.loads(workflow.report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "validated")
            self.assertEqual(
                report["bigquery"]["validated_row"]["run_id"],
                "local-smoke-20260511-201554",
            )

    def test_bigquery_validation_rejects_zero_rows(self):
        """Verify BigQuery validation rejects zero rows.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow, _ = make_workflow(tmpdir, runner=FakeRunner(bigquery_rows=[]))

            with contextlib.redirect_stderr(io.StringIO()):
                result = workflow.run()

            self.assertEqual(result, 2)
            issue = json.loads(workflow.issue_path.read_text(encoding="utf-8"))
            self.assertEqual(issue["failed_step"], "bigquery-row-validation")
            self.assertIn("exactly one row", issue["message"])

    def test_bigquery_validation_rejects_duplicate_rows(self):
        """Verify BigQuery validation rejects duplicate rows.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "local-smoke-20260511-201554", "summary_status": "complete"},
                {"run_id": "local-smoke-20260511-201554", "summary_status": "complete"},
            ]
            workflow, _ = make_workflow(tmpdir, runner=FakeRunner(bigquery_rows=rows))

            with contextlib.redirect_stderr(io.StringIO()):
                result = workflow.run()

            self.assertEqual(result, 2)
            issue = json.loads(workflow.issue_path.read_text(encoding="utf-8"))
            self.assertIn("found 2", issue["message"])

    def test_bigquery_validation_query_failure_writes_issue(self):
        """Verify BigQuery validation query failure writes issue.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow, _ = make_workflow(
                tmpdir,
                runner=FakeRunner(
                    fail_steps={
                        "bq --format=json": (1, "", "permission denied token=secret-value")
                    }
                ),
            )

            with contextlib.redirect_stderr(io.StringIO()):
                result = workflow.run()

            self.assertEqual(result, 2)
            issue_text = workflow.issue_path.read_text(encoding="utf-8")
            self.assertIn("permission denied", issue_text)
            self.assertNotIn("secret-value", issue_text)

    def assertCommandOrder(self, commands, expected_prefixes):
        """Assert that command Order matches expectations.


        Args:
            commands: commands used by this operation.
            expected_prefixes: expected prefixes used by this operation.

        Returns:
            None.
        """
        search_from = 0
        for expected in expected_prefixes:
            for index in range(search_from, len(commands)):
                if commands[index].startswith(expected) or expected in commands[index]:
                    search_from = index + 1
                    break
            else:
                self.fail(f"missing command {expected!r} in {commands!r}")


def make_workflow(tmpdir, *, extra_args=None, runner=None):
    """Compute make workflow.


    Args:
        tmpdir: tmpdir used by this operation.
        extra_args: extra arguments used by this operation.
        runner: runner used by this operation.

    Returns:
        Result produced by make workflow.
    """
    env_file = Path(tmpdir) / "credential.env"
    env_file.write_text(
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
    args = run_local_benchmark_workflow.parse_args(
        [
            "--run-id",
            "local-smoke-20260511-201554",
            "--credential-env-file",
            str(env_file),
            "--artifacts-root",
            str(Path(tmpdir) / "artifacts"),
            *(extra_args or []),
        ]
    )
    env = {}
    config = run_local_benchmark_workflow.config_from_args(args, environ=env)
    runner = runner or FakeRunner()
    workflow = run_local_benchmark_workflow.LocalBenchmarkWorkflow(
        config,
        runner=runner,
        environ=env,
    )
    return workflow, runner


def command_strings(runner):
    """Compute command strings.


    Args:
        runner: runner used by this operation.

    Returns:
        Result produced by command strings.
    """
    return [" ".join(record["command"]) for record in runner.commands]


if __name__ == "__main__":
    unittest.main()
