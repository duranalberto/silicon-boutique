import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automation.scripts import run_local_benchmark


class FakeRunner:
    def __init__(self, *, fail_commands=None, fail_bigquery_load=False):
        self.commands = []
        self.fail_commands = fail_commands or {}
        self.fail_bigquery_load = fail_bigquery_load

    def run(
        self,
        command,
        *,
        cwd=None,
        check=True,
        capture=False,
        log_path=None,
        input_text=None,
        timeout=None,
    ):
        del input_text
        rendered = [str(part) for part in command]
        self.commands.append(
            {
                "command": rendered,
                "cwd": str(cwd) if cwd else None,
                "timeout": timeout,
            }
        )
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(log_path).open("a", encoding="utf-8") as handle:
                handle.write("$ " + " ".join(rendered) + "\nexit_code=0\n")

        for prefix, returncode in self.fail_commands.items():
            if " ".join(rendered).startswith(prefix):
                if check:
                    raise run_local_benchmark.LocalBenchmarkError(
                        f"command failed with exit {returncode}: {' '.join(rendered)}"
                    )
                return run_local_benchmark.CommandResult(returncode, "", "failed")

        if rendered == ["terraform", "output", "-json"]:
            return run_local_benchmark.CommandResult(0, json.dumps(terraform_outputs()))
        if rendered[:2] == ["curl", "-fsS"]:
            return run_local_benchmark.CommandResult(0, "ready")
        if any(part.endswith("load_benchmark_summary_to_bigquery.py") for part in rendered):
            if self.fail_bigquery_load and "--preflight-only" not in rendered:
                return run_local_benchmark.CommandResult(2, "", "load failed")
            if "--load-report-output" in rendered:
                report = Path(rendered[rendered.index("--load-report-output") + 1])
                report.parent.mkdir(parents=True, exist_ok=True)
                status = "validated" if "--preflight-only" in rendered else "loaded"
                report.write_text(
                    json.dumps(
                        {
                            "status": status,
                            "summary_table": "example-project.silicon_boutique.benchmark_summaries",
                            "run_ids": [] if "--preflight-only" in rendered else ["local-test"],
                        }
                    ),
                    encoding="utf-8",
                )
        return run_local_benchmark.CommandResult(0, "", "")


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        del timeout
        return 0

    def kill(self):
        self.killed = True


class RunLocalBenchmarkTest(unittest.TestCase):
    def test_parse_duration_seconds(self):
        self.assertEqual(run_local_benchmark.parse_duration_seconds("30"), 30)
        self.assertEqual(run_local_benchmark.parse_duration_seconds("30s"), 30)
        self.assertEqual(run_local_benchmark.parse_duration_seconds("20m"), 1200)
        self.assertEqual(run_local_benchmark.parse_duration_seconds("1h"), 3600)

    def test_parse_duration_rejects_invalid_values(self):
        for value in ("0", "0m", "1d", "abc", "1.5m"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    run_local_benchmark.parse_duration_seconds(value)

    def test_default_run_id_is_terraform_compatible(self):
        run_id = run_local_benchmark.default_run_id()

        self.assertRegex(run_id, r"^local-[0-9]{14}$")
        self.assertLessEqual(len(run_id), 46)

    def test_successful_run_executes_expected_local_sequence_and_writes_trace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark, runner = make_benchmark(tmpdir)

            result = benchmark.run()

            self.assertEqual(result, 0)
            commands = command_strings(runner)
            validator_commands = [
                command
                for command in commands
                if "automation/scripts/validate_benchmark_comparability.py" in command
            ]
            generator_commands = [
                command
                for command in commands
                if "automation/scripts/generate_benchmark_summary.py" in command
            ]
            self.assertEqual(len(validator_commands), 1)
            self.assertEqual(len(generator_commands), 1)
            self.assertIn("--run-id local-test", validator_commands[0])
            self.assertIn("--min-coverage-ratio 0.95", generator_commands[0])
            self.assertIn("--min-coverage-ratio 0.95", validator_commands[0])
            self.assertCommandOrder(
                commands,
                [
                    "terraform init -input=false",
                    "terraform validate",
                    "terraform apply -auto-approve",
                    "terraform output -json",
                    "helm dependency update",
                    "helm lint",
                    "helm upgrade --install silicon-boutique-online-boutique",
                    "kubectl wait deployment --all",
                    "helm upgrade --install sb-monitoring",
                    "kubectl rollout restart deployment/loadgenerator",
                    "helm upgrade --install sb-monitoring",
                    "automation/scripts/extract_prometheus_metrics.py",
                    "kubectl logs deployment/loadgenerator",
                    "automation/scripts/extract_loadgenerator_stats.py",
                    "automation/scripts/generate_benchmark_summary.py",
                    "automation/scripts/validate_benchmark_comparability.py",
                    "helm uninstall sb-monitoring",
                    "helm uninstall silicon-boutique-online-boutique",
                    "terraform destroy -auto-approve",
                ],
            )

            artifacts_dir = Path(tmpdir)
            trace = json.loads(
                (artifacts_dir / "workflow-trace.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(trace),
                {"github", "benchmark", "gcp", "bigquery", "artifacts", "teardown", "inputs"},
            )
            self.assertEqual(trace["benchmark"]["run_id"], "local-test")
            self.assertEqual(trace["benchmark"]["namespace"], "silicon-boutique-local-test")
            self.assertEqual(trace["artifacts"]["artifact_name"], "benchmark-local-local-test")
            self.assertEqual(trace["teardown"]["destroy_attempted"], "true")
            self.assertEqual(trace["teardown"]["destroy_succeeded"], "true")
            self.assertEqual(trace["bigquery"]["persist_requested"], "false")

            for artifact in (
                "provision-status.env",
                "managed-resource-names.json",
                "terraform-labels.json",
                "terraform-apply.log",
                "teardown-check-commands.json",
                "helm-cleanup.log",
                "teardown-precheck.txt",
                "teardown-destroy.log",
                "teardown-postcheck.txt",
                "teardown-status.env",
                "workflow-trace.env",
            ):
                self.assertTrue((artifacts_dir / artifact).exists(), artifact)

    def test_load_profile_file_overrides_load_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = Path(tmpdir) / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "selected_profile": {
                            "load_concurrent_users": 64,
                            "load_users_per_second": 8.5,
                            "load_profile_source": "calibration",
                        }
                    }
                ),
                encoding="utf-8",
            )

            args = run_local_benchmark.parse_args(
                [
                    "--run-id",
                    "local-test",
                    "--load-profile-file",
                    str(profile),
                ]
            )
            config = run_local_benchmark.config_from_args(args)

            self.assertEqual(config.concurrent_users, "64")
            self.assertEqual(config.users_per_second, "8.5")
            self.assertEqual(config.load_profile_source, "calibration")

    def test_env_file_parsing_and_bigquery_config_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmpdir) / "credential.env"
            env_file.write_text(
                "\n".join(
                    [
                        "PROJECT_ID=example-project",
                        "BIGQUERY_DATASET=silicon_boutique",
                        "BIGQUERY_TABLE=benchmark_summaries",
                        "BIGQUERY_LOCATION=US",
                        "GOOGLE_APPLICATION_CREDENTIALS=/tmp/local-key.json",
                    ]
                ),
                encoding="utf-8",
            )

            args = run_local_benchmark.parse_args(
                [
                    "--persist-bigquery",
                    "--bigquery-env-file",
                    str(env_file),
                ]
            )
            config = run_local_benchmark.config_from_args(args)

            self.assertEqual(config.bigquery_project_id, "example-project")
            self.assertEqual(config.bigquery_dataset, "silicon_boutique")
            self.assertEqual(config.bigquery_table, "benchmark_summaries")
            self.assertEqual(config.bigquery_location, "US")
            self.assertEqual(os.environ["GOOGLE_APPLICATION_CREDENTIALS"], "/tmp/local-key.json")

    def test_env_file_parse_errors_do_not_echo_secret_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "credential.env"
            env_file.write_text("not a valid secret-value line\n", encoding="utf-8")

            with self.assertRaises(ValueError) as context:
                run_local_benchmark.read_env_file(env_file)

            self.assertIn("line 1", str(context.exception))
            self.assertNotIn("secret-value", str(context.exception))

    def test_bigquery_cli_values_override_env_file(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmpdir) / "credential.env"
            env_file.write_text(
                "\n".join(
                    [
                        "PROJECT_ID=file-project",
                        "BIGQUERY_DATASET=file_dataset",
                        "BIGQUERY_TABLE=file_table",
                        "BIGQUERY_LOCATION=EU",
                    ]
                ),
                encoding="utf-8",
            )

            args = run_local_benchmark.parse_args(
                [
                    "--persist-bigquery",
                    "--bigquery-env-file",
                    str(env_file),
                    "--bigquery-project-id",
                    "cli-project",
                    "--bigquery-dataset",
                    "cli_dataset",
                    "--bigquery-table",
                    "cli_table",
                    "--bigquery-location",
                    "US",
                ]
            )
            config = run_local_benchmark.config_from_args(args)

            self.assertEqual(config.bigquery_project_id, "cli-project")
            self.assertEqual(config.bigquery_dataset, "cli_dataset")
            self.assertEqual(config.bigquery_table, "cli_table")
            self.assertEqual(config.bigquery_location, "US")

    def test_persist_bigquery_requires_resolved_destination(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(os.environ, {}, clear=True):
            missing_env_file = Path(tmpdir) / "missing.env"

            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run_local_benchmark.parse_args(
                    [
                        "--persist-bigquery",
                        "--bigquery-env-file",
                        str(missing_env_file),
                    ]
                )

    def test_controlled_failure_after_provision_still_runs_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark, runner = make_benchmark(tmpdir, failure_stage="after_provision")

            with contextlib.redirect_stderr(io.StringIO()):
                result = benchmark.run()

            self.assertEqual(result, 2)
            commands = command_strings(runner)
            self.assertIn("terraform apply -auto-approve", "\n".join(commands))
            self.assertIn("helm uninstall sb-monitoring", "\n".join(commands))
            self.assertIn("terraform destroy -auto-approve", "\n".join(commands))
            self.assertNotIn("helm upgrade --install silicon-boutique-online-boutique", "\n".join(commands))

    def test_updates_monitoring_dashboard_with_benchmark_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark, runner = make_benchmark(tmpdir)

            result = benchmark.run()

            self.assertEqual(result, 0)
            commands = command_strings(runner)
            window_updates = [
                command
                for command in commands
                if command.startswith("helm upgrade --install sb-monitoring")
                and "--reuse-values" in command
                and "siliconBoutique.benchmarkStart=" in command
                and "siliconBoutique.benchmarkEnd=" in command
            ]
            self.assertEqual(len(window_updates), 1)

    def test_skip_destroy_records_trace_without_destroy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark, runner = make_benchmark(tmpdir, skip_destroy=True)

            result = benchmark.run()

            self.assertEqual(result, 0)
            commands = "\n".join(command_strings(runner))
            self.assertNotIn("terraform destroy -auto-approve", commands)
            trace = json.loads(
                (Path(tmpdir) / "workflow-trace.json").read_text(encoding="utf-8")
            )
            self.assertEqual(trace["teardown"]["destroy_attempted"], "false")
            self.assertEqual(trace["teardown"]["destroy_succeeded"], "skipped")

    def test_unreachable_kubernetes_context_fails_before_terraform_apply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark, runner = make_benchmark(tmpdir)
            runner.fail_commands = {
                "kubectl get nodes --context siliconboutique": 1,
            }

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = benchmark.run()

            self.assertEqual(result, 2)
            self.assertIn("Kubernetes context 'siliconboutique' is not reachable", stderr.getvalue())
            commands = "\n".join(command_strings(runner))
            self.assertIn("kubectl get nodes --context siliconboutique", commands)
            self.assertIn("minikube status --profile siliconboutique", commands)
            self.assertNotIn("terraform apply -auto-approve", commands)

    def test_persist_bigquery_preflights_loads_and_writes_trace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark, runner = make_benchmark(tmpdir, persist_bigquery=True)

            result = benchmark.run()

            self.assertEqual(result, 0)
            commands = command_strings(runner)
            bigquery_commands = [
                command
                for command in commands
                if "load_benchmark_summary_to_bigquery.py" in command
            ]
            self.assertEqual(len(bigquery_commands), 2)
            self.assertIn("--preflight-only", bigquery_commands[0])
            self.assertIn("--summary-store", bigquery_commands[1])
            self.assertCommandOrder(
                commands,
                [
                    "load_benchmark_summary_to_bigquery.py",
                    "terraform init -input=false",
                    "terraform apply -auto-approve",
                    "automation/scripts/validate_benchmark_comparability.py",
                    "load_benchmark_summary_to_bigquery.py",
                    "helm uninstall sb-monitoring",
                ],
            )
            trace = json.loads(
                (Path(tmpdir) / "workflow-trace.json").read_text(encoding="utf-8")
            )
            self.assertEqual(trace["bigquery"]["persist_requested"], "true")
            self.assertEqual(
                trace["bigquery"]["summary_table"],
                "example-project.silicon_boutique.benchmark_summaries",
            )
            self.assertEqual(trace["bigquery"]["load_report_exists"], "true")

    def test_bigquery_load_failure_still_runs_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark, runner = make_benchmark(
                tmpdir,
                persist_bigquery=True,
                runner=FakeRunner(fail_bigquery_load=True),
            )

            with contextlib.redirect_stderr(io.StringIO()):
                result = benchmark.run()

            self.assertEqual(result, 2)
            commands = "\n".join(command_strings(runner))
            self.assertIn("load_benchmark_summary_to_bigquery.py", commands)
            self.assertIn("terraform destroy -auto-approve", commands)

    def assertCommandOrder(self, commands, expected_prefixes):
        search_from = 0
        for expected in expected_prefixes:
            for index in range(search_from, len(commands)):
                if commands[index].startswith(expected) or expected in commands[index]:
                    search_from = index + 1
                    break
            else:
                self.fail(f"missing command {expected!r} in {commands!r}")


def make_benchmark(
    tmpdir,
    *,
    failure_stage="none",
    skip_destroy=False,
    persist_bigquery=False,
    runner=None,
):
    config = run_local_benchmark.BenchmarkConfig(
        run_id="local-test",
        artifacts_dir=Path(tmpdir),
        terraform_dir=Path("infra/terraform/local-kubernetes"),
        workload_chart=Path("k8s/charts/silicon-boutique-online-boutique"),
        monitoring_chart=Path("k8s/charts/silicon-boutique-monitoring"),
        workload_release="silicon-boutique-online-boutique",
        monitoring_release="sb-monitoring",
        machine_type="local",
        processor_family="local",
        cpu_platform=None,
        architecture="x86_64",
        region="local",
        zone="local",
        node_count=1,
        concurrent_users="10",
        users_per_second="1",
        test_duration="20m",
        test_duration_seconds=1200,
        pricing_model="local",
        load_profile_source="manual",
        prometheus_port=9090,
        min_duration_seconds=1200,
        min_coverage_ratio=0.95,
        failure_stage=failure_stage,
        skip_destroy=skip_destroy,
        persist_bigquery=persist_bigquery,
        bigquery_env_file=None,
        bigquery_project_id="example-project" if persist_bigquery else "",
        bigquery_dataset="silicon_boutique" if persist_bigquery else "",
        bigquery_table="benchmark_summaries" if persist_bigquery else "",
        bigquery_location="US" if persist_bigquery else "",
    )
    runner = runner or FakeRunner()
    benchmark = run_local_benchmark.LocalBenchmark(
        config,
        runner=runner,
        sleep=lambda _: None,
        popen=FakeProcess,
    )
    return benchmark, runner


def command_strings(runner):
    return [" ".join(record["command"]) for record in runner.commands]


def terraform_outputs():
    return {
        "run_id": {"value": "local-test"},
        "namespace": {"value": "silicon-boutique-local-test"},
        "name_prefix": {"value": "silicon-boutique-local-test"},
        "kube_context": {"value": "siliconboutique"},
        "environment": {"value": "local"},
        "machine_type": {"value": "local"},
        "processor_family": {"value": "local"},
        "architecture": {"value": "x86_64"},
        "region": {"value": "local"},
        "node_count": {"value": 1},
        "labels": {
            "value": {
                "silicon-boutique/run-id": "local-test",
            }
        },
        "teardown_check_commands": {
            "value": [
                "kubectl get namespace silicon-boutique-local-test --context siliconboutique",
            ]
        },
    }


if __name__ == "__main__":
    unittest.main()
