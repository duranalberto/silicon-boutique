import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from automation.scripts import run_local_benchmark


class FakeRunner:
    def __init__(self, *, fail_commands=None):
        self.commands = []
        self.fail_commands = fail_commands or {}

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
                    "automation/scripts/extract_prometheus_metrics.py",
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
                {"github", "benchmark", "gcp", "artifacts", "teardown", "inputs"},
            )
            self.assertEqual(trace["benchmark"]["run_id"], "local-test")
            self.assertEqual(trace["benchmark"]["namespace"], "silicon-boutique-local-test")
            self.assertEqual(trace["artifacts"]["artifact_name"], "benchmark-local-local-test")
            self.assertEqual(trace["teardown"]["destroy_attempted"], "true")
            self.assertEqual(trace["teardown"]["destroy_succeeded"], "true")

            for artifact in (
                "provision-status.env",
                "managed-resource-names.json",
                "terraform-labels.json",
                "teardown-check-commands.json",
                "helm-cleanup.log",
                "teardown-precheck.txt",
                "teardown-destroy.log",
                "teardown-postcheck.txt",
                "teardown-status.env",
                "workflow-trace.env",
            ):
                self.assertTrue((artifacts_dir / artifact).exists(), artifact)

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

    def assertCommandOrder(self, commands, expected_prefixes):
        search_from = 0
        for expected in expected_prefixes:
            for index in range(search_from, len(commands)):
                if commands[index].startswith(expected) or expected in commands[index]:
                    search_from = index + 1
                    break
            else:
                self.fail(f"missing command {expected!r} in {commands!r}")


def make_benchmark(tmpdir, *, failure_stage="none", skip_destroy=False):
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
        architecture="x86_64",
        node_count=1,
        concurrent_users="10",
        users_per_second="1",
        test_duration="20m",
        test_duration_seconds=1200,
        prometheus_port=9090,
        min_duration_seconds=1200,
        min_coverage_ratio=0.95,
        failure_stage=failure_stage,
        skip_destroy=skip_destroy,
    )
    runner = FakeRunner()
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
