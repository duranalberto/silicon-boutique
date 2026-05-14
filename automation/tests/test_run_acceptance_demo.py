"""Tests for test run acceptance demo."""

import importlib.util
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "run_acceptance_demo.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "benchmark.yml"

sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("run_acceptance_demo", SCRIPT)
run_acceptance_demo = importlib.util.module_from_spec(spec)
sys.modules["run_acceptance_demo"] = run_acceptance_demo
spec.loader.exec_module(run_acceptance_demo)


class FakeRunner:
    """Test double that records runner interactions.
    """
    def __init__(
        self,
        *,
        omit_summary=False,
        mismatched_summary=False,
        grafana_api_payload=None,
        grafana_api_returncode=0,
        omit_grafana_secret=False,
        grafana_secret_payload=None,
    ):
        """Initialize the object with the provided configuration.


        Args:
            omit_summary: omit summary used by this operation.
            mismatched_summary: mismatched summary used by this operation.
            grafana_api_payload: Grafana API payload used by this operation.
            grafana_api_returncode: Grafana API returncode used by this operation.
            omit_grafana_secret: omit Grafana secret used by this operation.
            grafana_secret_payload: Grafana secret payload used by this operation.

        Returns:
            None.
        """
        self.commands = []
        self.omit_summary = omit_summary
        self.mismatched_summary = mismatched_summary
        self.grafana_api_payload = grafana_api_payload or {
            "dashboard": {
                "uid": "silicon-boutique-online-boutique",
                "title": "SiliconBoutique Online Boutique Benchmark",
            }
        }
        self.grafana_api_returncode = grafana_api_returncode
        self.omit_grafana_secret = omit_grafana_secret
        self.grafana_secret_payload = grafana_secret_payload

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
        """Run the configured operation.


        Args:
            command: command used by this operation.
            cwd: cwd used by this operation.
            check: check used by this operation.
            capture: capture used by this operation.
            log_path: log path used by this operation.
            input_text: input text used by this operation.
            timeout: timeout used by this operation.

        Returns:
            Result produced by run.
        """
        del cwd, check, capture, input_text, timeout
        rendered = [str(part) for part in command]
        self.commands.append(rendered)
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(log_path).open("a", encoding="utf-8") as handle:
                handle.write("$ " + " ".join(rendered) + "\nexit_code=0\n")

        if rendered == ["terraform", "output", "-json"]:
            return run_acceptance_demo.run_local_benchmark.CommandResult(
                0, json.dumps(terraform_outputs()), ""
            )
        if rendered[:3] == ["kubectl", "get", "configmap"]:
            return run_acceptance_demo.run_local_benchmark.CommandResult(
                0, json.dumps(dashboard_configmap()), ""
            )
        if rendered[:3] == ["kubectl", "get", "secret"]:
            payload = self.grafana_secret_payload
            if payload is None:
                payload = {} if self.omit_grafana_secret else grafana_secret()
            return run_acceptance_demo.run_local_benchmark.CommandResult(
                0, json.dumps(payload), ""
            )
        if rendered[:2] == ["curl", "-fsS"] and any("/api/dashboards/uid/" in part for part in rendered):
            if self.grafana_api_returncode != 0:
                return run_acceptance_demo.run_local_benchmark.CommandResult(
                    self.grafana_api_returncode, "", "Grafana unavailable"
                )
            return run_acceptance_demo.run_local_benchmark.CommandResult(
                0, json.dumps(self.grafana_api_payload), ""
            )
        if rendered[:2] == ["curl", "-fsS"]:
            return run_acceptance_demo.run_local_benchmark.CommandResult(0, "ready", "")
        if any(part.endswith("extract_prometheus_metrics.py") for part in rendered):
            write_json(Path(rendered[rendered.index("--output") + 1]), metrics_payload())
        if any(part.endswith("extract_loadgenerator_stats.py") for part in rendered):
            write_json(
                Path(rendered[rendered.index("--output") + 1]),
                {
                    "run_id": "local-test",
                    "request_count_total": 300,
                    "request_success_count": 295,
                    "request_failure_count": 5,
                    "avg_requests_per_second": 5,
                    "parse_status": "parsed",
                },
            )
        if any(part.endswith("generate_benchmark_summary.py") for part in rendered) and not self.omit_summary:
            run_id = "other-run" if self.mismatched_summary else "local-test"
            summary_path = Path(rendered[rendered.index("--summary-output") + 1])
            store_path = Path(rendered[rendered.index("--summary-store") + 1])
            summary = summary_payload(run_id)
            write_json(summary_path, summary)
            store_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        if any(part.endswith("validate_benchmark_comparability.py") for part in rendered):
            write_json(
                Path(rendered[rendered.index("--report-output") + 1]),
                {
                    "summary_validation_status": "pass",
                    "comparability_validation_status": "skipped",
                    "comparable_run_ids": ["local-test"],
                },
            )
        if any(part.endswith("load_benchmark_summary_to_bigquery.py") for part in rendered):
            write_json(
                Path(rendered[rendered.index("--load-report-output") + 1]),
                {
                    "status": "loaded",
                    "summary_table": "project.dataset.table",
                    "row_count": 1,
                    "run_ids": ["local-test"],
                    "dry_run": False,
                },
            )
        if rendered[:3] == ["kubectl", "logs", "deployment/loadgenerator"]:
            return run_acceptance_demo.run_local_benchmark.CommandResult(
                0, "Aggregated 300 295 5", ""
            )
        return run_acceptance_demo.run_local_benchmark.CommandResult(0, "", "")


class FakeProcess:
    """Test double that records process interactions.
    """
    def __init__(self, *args, **kwargs):
        """Initialize the object with the provided configuration.


        Args:
            args: arguments used by this operation.
            kwargs: kwargs used by this operation.

        Returns:
            None.
        """
        self.args = args
        self.kwargs = kwargs
        self.terminated = False
        self.killed = False

    def terminate(self):
        """Compute terminate.


        Returns:
            None.
        """
        self.terminated = True

    def wait(self, timeout=None):
        """Compute wait.


        Args:
            timeout: timeout used by this operation.

        Returns:
            Result produced by wait.
        """
        del timeout
        return 0

    def kill(self):
        """Compute kill.


        Returns:
            None.
        """
        self.killed = True


class AcceptanceDemoTest(unittest.TestCase):
    """Unit tests covering acceptance Demo behavior.
    """
    def test_successful_local_demo_writes_acceptance_report_and_cleans_up(self):
        """Verify successful local demo writes acceptance report and cleans up.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, runner = run_demo(tmpdir)

            self.assertEqual(result, 0)
            commands = command_strings(runner)
            self.assertTrue(any(command.startswith("terraform apply -auto-approve") for command in commands))
            self.assertTrue(any(command.startswith("terraform destroy -auto-approve") for command in commands))
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["run_id"], "local-test")
            self.assertEqual(report["checks"]["dashboard"]["dashboard_uid"], "silicon-boutique-online-boutique")
            self.assertEqual(report["checks"]["dashboard"]["grafana_load_status"]["status"], "passed")
            self.assertEqual(report["checks"]["bigquery"]["status"], "skipped_optional")

    def test_grafana_api_success_is_recorded(self):
        """Verify Grafana API success is recorded.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = run_demo(
                tmpdir,
                runner=FakeRunner(
                    grafana_api_payload={
                        "dashboard": {
                            "uid": "silicon-boutique-online-boutique",
                            "title": "SiliconBoutique Online Boutique Benchmark",
                        }
                    }
                ),
            )

            self.assertEqual(result, 0)
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(report["checks"]["dashboard"]["grafana_load_status"]["status"], "passed")

    def test_grafana_api_unavailable_fails_acceptance(self):
        """Verify Grafana API unavailable fails acceptance.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = run_demo(
                tmpdir,
                runner=FakeRunner(grafana_api_returncode=7),
            )

            self.assertEqual(result, 2)
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(
                report["checks"]["dashboard"]["grafana_load_status"]["status"],
                "failed",
            )
            self.assertEqual(report["status"], "failed")

    def test_missing_grafana_secret_fails_acceptance(self):
        """Verify missing Grafana secret fails acceptance.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = run_demo(tmpdir, runner=FakeRunner(omit_grafana_secret=True))

            self.assertEqual(result, 2)
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(report["status"], "failed")
            self.assertIn("admin-password", report["checks"]["orchestration"]["error"])

    def test_invalid_grafana_secret_fails_acceptance(self):
        """Verify invalid Grafana secret fails acceptance.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = run_demo(
                tmpdir,
                runner=FakeRunner(
                    grafana_secret_payload={"data": {"admin-password": "not-base64!"}}
                ),
            )

            self.assertEqual(result, 2)
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(report["status"], "failed")
            self.assertIn("base64", report["checks"]["orchestration"]["error"])

    def test_local_demo_loads_bigquery_when_settings_are_provided(self):
        """Verify local demo loads BigQuery when settings are provided.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = run_demo(
                tmpdir,
                "--bigquery-project-id",
                "valid-project1",
                "--bigquery-dataset",
                "silicon_boutique",
                "--bigquery-table",
                "benchmark_summaries",
                "--bigquery-location",
                "US",
            )

            self.assertEqual(result, 0)
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(report["checks"]["bigquery"]["status"], "passed")
            self.assertEqual(report["checks"]["bigquery"]["summary_table"], "project.dataset.table")

    def test_dashboard_hold_records_local_url_and_still_cleans_up(self):
        """Verify dashboard hold records local URL and still cleans up.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, runner = run_demo(tmpdir, "--dashboard-hold-seconds", "1")

            self.assertEqual(result, 0)
            commands = command_strings(runner)
            self.assertTrue(any(command.startswith("terraform destroy -auto-approve") for command in commands))
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(
                report["checks"]["dashboard"]["live_inspection"]["url"],
                "http://127.0.0.1:3000",
            )

    def test_missing_summary_fails_acceptance_report(self):
        """Verify missing summary fails acceptance report.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = run_demo(tmpdir, runner=FakeRunner(omit_summary=True))

            self.assertEqual(result, 2)
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["checks"]["summary"]["status"], "failed")

    def test_mismatched_summary_run_id_fails_acceptance_report(self):
        """Verify mismatched summary run ID fails acceptance report.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = run_demo(tmpdir, runner=FakeRunner(mismatched_summary=True))

            self.assertEqual(result, 2)
            report = read_json(Path(tmpdir) / "acceptance-demo-report.json")
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["checks"]["summary"]["run_id"], "other-run")

    def test_workflow_has_acceptance_demo_dispatch_path(self):
        """Verify workflow has acceptance demo dispatch path.


        Returns:
            None.
        """
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("acceptance_demo:", workflow)
        self.assertIn("acceptance-demo-report.json", workflow)
        self.assertIn("run_acceptance_demo.py", workflow)

    def test_workflow_preflights_bigquery_before_provisioning(self):
        """Verify workflow preflights BigQuery before provisioning.


        Returns:
            None.
        """
        workflow = WORKFLOW.read_text(encoding="utf-8")

        preflight_index = workflow.index("name: Preflight BigQuery destination")
        provision_index = workflow.index("name: Provision GKE benchmark environment")
        self.assertLess(preflight_index, provision_index)
        self.assertIn("--preflight-only", workflow)
        self.assertIn("--load-profile-source \"$LOAD_PROFILE_SOURCE\" \\\n            --min-coverage-ratio 0.95", workflow)
        self.assertIn('--min-duration-seconds "$TEST_DURATION_SECONDS"', workflow)
        self.assertIn('--duration-seconds "$TEST_DURATION_SECONDS"', workflow)
        self.assertIn('--log-source "$log_source"', workflow)
        self.assertIn("--previous", workflow)
        self.assertNotIn("--min-duration-seconds 1200", workflow)


def run_demo(tmpdir, *extra_args, runner=None):
    """Run demo.


    Args:
        tmpdir: tmpdir used by this operation.
        extra_args: extra arguments used by this operation.
        runner: runner used by this operation.

    Returns:
        Result produced by run demo.
    """
    args = run_acceptance_demo.parse_args(
        [
            "--mode",
            "local",
            "--run-id",
            "local-test",
            "--artifacts-dir",
            tmpdir,
            "--test-duration",
            "1s",
            "--min-duration-seconds",
            "1",
            *extra_args,
        ]
    )
    demo = run_acceptance_demo.AcceptanceDemo(
        run_acceptance_demo.config_from_args(args),
        runner=runner or FakeRunner(),
        sleep=lambda _: None,
        popen=FakeProcess,
    )
    result = demo.run()
    return result, demo.runner


def command_strings(runner):
    """Compute command strings.


    Args:
        runner: runner used by this operation.

    Returns:
        Result produced by command strings.
    """
    return [" ".join(command) for command in runner.commands]


def terraform_outputs():
    """Compute terraform outputs.


    Returns:
        Result produced by terraform outputs.
    """
    return {
        "run_id": {"value": "local-test"},
        "namespace": {"value": "silicon-boutique-local-test"},
        "environment": {"value": "local"},
        "machine_type": {"value": "local"},
        "processor_family": {"value": "local"},
        "architecture": {"value": "x86_64"},
        "region": {"value": "local"},
        "node_count": {"value": 1},
        "kube_context": {"value": "siliconboutique"},
        "labels": {"value": {"run_id": "local-test"}},
        "teardown_check_commands": {"value": []},
        "name_prefix": {"value": "silicon-boutique-local-test"},
    }


def dashboard_configmap():
    """Compute dashboard configmap.


    Returns:
        Result produced by dashboard configmap.
    """
    dashboard = {
        "uid": "silicon-boutique-online-boutique",
        "title": "SiliconBoutique Online Boutique Benchmark",
        "panels": [
            {
                "targets": [
                    {
                        "expr": " ".join(run_acceptance_demo.EXPECTED_PANEL_EXPRESSIONS)
                        + " local-test"
                    }
                ]
            }
        ],
    }
    return {
        "items": [
            {
                "metadata": {"name": "sb-monitoring-dashboard"},
                "data": {"online-boutique-benchmark.json": json.dumps(dashboard)},
            }
        ]
    }


def grafana_secret():
    """Compute Grafana secret.


    Returns:
        Result produced by Grafana secret.
    """
    encoded = base64.b64encode(b"prom-operator").decode("ascii")
    return {"data": {"admin-password": encoded}}


def metrics_payload():
    """Compute metrics payload.


    Returns:
        Result produced by metrics payload.
    """
    return {
        "run_id": "local-test",
        "namespace": "silicon-boutique-local-test",
        "window": {
            "start": "2026-05-07T12:00:00Z",
            "end": "2026-05-07T12:01:00Z",
            "step_seconds": 15,
        },
        "quality": {
            "coverage_ratio": 1.0,
            "missing_series": [],
            "empty_series": [],
            "invalid_samples": {},
            "expected_samples_per_metric": 5,
        },
        "metrics": {
            name: {"sample_count": 5, "unit": "test", "avg": 1}
            for name in run_acceptance_demo.REQUIRED_METRICS
        },
    }


def summary_payload(run_id):
    """Compute summary payload.


    Args:
        run_id: run ID used by this operation.

    Returns:
        Result produced by summary payload.
    """
    return {
        "run_id": run_id,
        "summary_status": "complete",
        "avg_cpu_utilization_pct": 50,
        "request_success_count": 295,
    }


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


if __name__ == "__main__":
    unittest.main()
