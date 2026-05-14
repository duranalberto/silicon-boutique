"""Tests for test run acceptance matrix."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "run_acceptance_matrix.py"
SCHEMA = REPO_ROOT / "automation" / "templates" / "benchmark-summary.schema.json"

sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("run_acceptance_matrix", SCRIPT)
run_acceptance_matrix = importlib.util.module_from_spec(spec)
sys.modules["run_acceptance_matrix"] = run_acceptance_matrix
spec.loader.exec_module(run_acceptance_matrix)


class FakeCompleted:
    """Test double that records completed interactions.
    """
    returncode = 0


class AcceptanceMatrixTest(unittest.TestCase):
    """Unit tests covering acceptance Matrix behavior.
    """
    def test_local_mode_runs_local_acceptance_and_skips_clouds(self):
        """Verify local mode runs local acceptance and skips clouds.


        Returns:
            Result produced by test local mode runs local acceptance and skips clouds.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            def runner(command, **kwargs):
                """Compute runner.


                Args:
                    command: command used by this operation.
                    kwargs: kwargs used by this operation.

                Returns:
                    Result produced by runner.
                """
                del command, kwargs
                write_artifacts(base / "local", "local-test", "local")
                return FakeCompleted()

            result = run_matrix(base, "--mode", "local", runner=runner)

            self.assertEqual(result, 0)
            report = read_json(base / "acceptance-matrix-report.json")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["checks"]["local_smoke"]["status"], "passed")
            self.assertEqual(
                report["checks"]["gcp_live_benchmark"]["status"],
                "skipped_requires_credentials",
            )
            self.assertEqual(
                report["checks"]["aws_live_benchmark"]["status"],
                "skipped_requires_credentials",
            )

    def test_stale_summary_run_id_fails_artifact_verification(self):
        """Verify stale summary run ID fails artifact verification.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            gcp = base / "gcp"
            write_artifacts(gcp, "trace-run", "gcp", summary_run_id="summary-run")

            result = run_matrix(base, "--mode", "verify", "--gcp-artifacts", str(gcp))

            self.assertEqual(result, 2)
            report = read_json(base / "acceptance-matrix-report.json")
            self.assertEqual(report["status"], "failed")
            self.assertIn(
                "benchmark summary run_id does not match workflow trace",
                report["checks"]["gcp_live_benchmark"]["errors"],
            )

    def test_missing_teardown_status_fails_artifact_verification(self):
        """Verify missing teardown status fails artifact verification.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            aws = base / "aws"
            write_artifacts(aws, "aws-run", "aws")
            (aws / "teardown-status.env").unlink()

            result = run_matrix(base, "--mode", "verify", "--aws-artifacts", str(aws))

            self.assertEqual(result, 2)
            report = read_json(base / "acceptance-matrix-report.json")
            self.assertEqual(report["status"], "failed")
            self.assertIn("teardown-status.env", report["checks"]["aws_live_benchmark"]["errors"][0])

    def test_mixed_gcp_aws_artifacts_generate_comparison(self):
        """Verify mixed GCP AWS artifacts generate comparison.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            gcp = base / "gcp"
            aws = base / "aws"
            write_artifacts(gcp, "gcp-run", "gcp")
            write_artifacts(aws, "aws-run", "aws")

            result = run_matrix(
                base,
                "--mode",
                "verify",
                "--gcp-artifacts",
                str(gcp),
                "--aws-artifacts",
                str(aws),
            )

            self.assertEqual(result, 0)
            report = read_json(base / "acceptance-matrix-report.json")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["checks"]["comparison_report"]["status"], "passed")
            comparison = read_json(base / "acceptance-matrix-comparison.json")
            self.assertEqual(comparison["comparable_run_count"], 2)
            markdown = (base / "acceptance-matrix-comparison.md").read_text(encoding="utf-8")
            self.assertIn("| Provider | Region | Machine |", markdown)
            self.assertIn("| aws | us-east-1 | m7i.xlarge |", markdown)


def run_matrix(base, *extra_args, runner=None):
    """Run matrix.


    Args:
        base: base used by this operation.
        extra_args: extra arguments used by this operation.
        runner: runner used by this operation.

    Returns:
        Result produced by run matrix.
    """
    args = run_acceptance_matrix.parse_args(
        [
            "--artifacts-dir",
            str(base),
            "--schema",
            str(SCHEMA),
            *extra_args,
        ]
    )
    matrix = run_acceptance_matrix.AcceptanceMatrix(
        run_acceptance_matrix.config_from_args(args),
        runner=runner or (lambda *_, **__: FakeCompleted()),
    )
    return matrix.run()


def write_artifacts(path, run_id, provider, *, summary_run_id=None):
    """Write artifacts.


    Args:
        path: path used by this operation.
        run_id: run ID used by this operation.
        provider: provider used by this operation.
        summary_run_id: summary run ID used by this operation.

    Returns:
        None.
    """
    path.mkdir(parents=True, exist_ok=True)
    summary_id = summary_run_id or run_id
    write_json(
        path / "workflow-trace.json",
        {
            "benchmark": {
                "run_id": run_id,
                "namespace": run_id,
                "cloud_provider": provider,
            },
            "teardown": {"destroy_succeeded": "true"},
        },
    )
    write_json(path / "benchmark-summary.json", summary_payload(summary_id, provider))
    write_json(
        path / "acceptance-demo-report.json",
        {
            "status": "passed",
            "run_id": run_id,
            "checks": {
                "dashboard": {
                    "grafana_load_status": {"status": "passed"},
                    "dashboard_uid": "silicon-boutique-online-boutique",
                    "dashboard_title": "SiliconBoutique Online Boutique Benchmark",
                }
            },
        },
    )
    write_json(
        path / "comparability-report.json",
        {
            "summary_validation_status": "pass",
            "comparable_run_ids": [run_id],
        },
    )
    write_json(
        path / "bigquery-load-report.json",
        {
            "status": "loaded",
            "summary_table": "project.silicon_boutique.benchmark_summaries",
            "run_ids": [run_id],
        },
    )
    (path / "teardown-status.env").write_text(
        "destroy_attempted=true\ndestroy_succeeded=true\n",
        encoding="utf-8",
    )


def summary_payload(run_id, provider):
    """Compute summary payload.


    Args:
        run_id: run ID used by this operation.
        provider: provider used by this operation.

    Returns:
        Result produced by summary payload.
    """
    cloud = {
        "local": ("local", "local", "local", "local", "local"),
        "gcp": ("gcp", "us-central1", "us-central1-a", "c3-standard-4", "c3"),
        "aws": ("aws", "us-east-1", "us-east-1a", "m7i.xlarge", "m7i"),
    }[provider]
    pricing = "local" if provider == "local" else "spot"
    return {
        "architecture": "x86_64",
        "avg_cpu_throttling_ratio": 0.01,
        "avg_cpu_usage_cores": 2.0,
        "avg_cpu_utilization_pct": 80.0,
        "avg_memory_working_set_bytes": 1_000_000_000,
        "avg_requests_per_second": 100.0,
        "avg_ready_pods": 12.0,
        "benchmark_compute_cost_usd": 0.001,
        "benchmark_end": "2026-05-07T12:20:00Z",
        "benchmark_start": "2026-05-07T12:00:00Z",
        "cloud_provider": cloud[0],
        "cost_per_1m_requests_usd": 0.4,
        "cpu_platform": None if provider == "local" else "test-platform",
        "duration_seconds": 1200,
        "empty_metrics": [],
        "environment": cloud[0],
        "frontend_latency_max_ms": 130.0,
        "frontend_latency_p50_ms": 60.0,
        "frontend_latency_p95_ms": 100.0,
        "frontend_latency_p99_ms": 120.0,
        "generated_at": "2026-05-07T12:21:00Z",
        "invalid_metric_samples": {},
        "load_concurrent_users": 10,
        "load_profile_source": "manual",
        "load_users_per_second": 1.0,
        "machine_type": cloud[3],
        "max_cpu_throttling_ratio": 0.02,
        "max_cpu_usage_cores": 2.5,
        "max_cpu_utilization_pct": 90.0,
        "max_memory_used_gb": 1.0,
        "max_memory_working_set_bytes": 1_000_000_000,
        "max_ready_pods": 12.0,
        "max_restarts_total": 0.0,
        "metrics_coverage_ratio": 0.99,
        "min_ready_pods": 12.0,
        "missing_metrics": [],
        "namespace": run_id,
        "node_count": 1,
        "node_hourly_price_usd": 0.03,
        "pricing_model": pricing,
        "processor_family": cloud[4],
        "region": cloud[1],
        "request_count_total": 120000,
        "request_failure_count": 1,
        "request_success_count": 119999,
        "run_id": run_id,
        "summary_status": "complete",
        "zone": cloud[2],
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
