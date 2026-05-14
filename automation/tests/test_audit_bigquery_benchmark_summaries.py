"""Tests for audit BigQuery benchmark summaries."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "automation" / "scripts" / "audit_bigquery_benchmark_summaries.py"
BIGQUERY_SCHEMA = (
    REPO_ROOT / "automation" / "templates" / "benchmark-summary.bigquery-schema.json"
)

sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("audit_bigquery_benchmark_summaries", SCRIPT)
auditor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = auditor
spec.loader.exec_module(auditor)


class FakeRunner:
    """Test double for BigQuery CLI calls."""

    def __init__(self, rows, *, schema=None):
        self.rows = rows
        self.schema = schema or json.loads(BIGQUERY_SCHEMA.read_text(encoding="utf-8"))
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        if "show" in command:
            return auditor.CommandResult(
                0,
                json.dumps({"schema": {"fields": self.schema}}),
                "",
            )
        if "query" in command:
            return auditor.CommandResult(0, json.dumps(self.rows), "")
        return auditor.CommandResult(1, "", "unexpected command")


class AuditBigQueryBenchmarkSummariesTest(unittest.TestCase):
    """Unit tests for read-only benchmark summary auditing."""

    def test_valid_fixture_passes(self):
        """Verify a valid row passes the audit."""
        report = auditor.build_audit_report(
            rows=[valid_summary("valid")],
            source={"type": "fixture"},
            schema_path=BIGQUERY_SCHEMA,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["suspect_run_ids"], [])
        self.assertEqual(report["rows"][0]["findings"], [])

    def test_current_suspect_pattern_is_flagged(self):
        """Verify the current BigQuery issue pattern is marked suspect."""
        report = auditor.build_audit_report(
            rows=[
                valid_summary("local-smoke", cloud_provider="local", duration_seconds=120, request_total=90, avg_rps=1.7),
                valid_summary("gcp-run", cloud_provider="gcp", request_total=51, avg_rps=2.6, cpu_platform=None),
            ],
            source={"type": "fixture"},
            schema_path=BIGQUERY_SCHEMA,
        )

        self.assertEqual(report["status"], "warn")
        self.assertEqual(report["suspect_run_ids"], ["local-smoke", "gcp-run"])
        local_findings = report["rows"][0]["findings"]
        gcp_findings = report["rows"][1]["findings"]
        self.assertIn("request_total_far_below_avg_rps_window", local_findings)
        self.assertIn("duration_below_comparability_min:120<1200", local_findings)
        self.assertIn("cloud_cpu_platform_missing", gcp_findings)

    def test_duplicate_run_id_fails(self):
        """Verify duplicate run IDs fail the audit."""
        report = auditor.build_audit_report(
            rows=[valid_summary("dup"), valid_summary("dup")],
            source={"type": "fixture"},
            schema_path=BIGQUERY_SCHEMA,
        )

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["duplicate_run_ids"], ["dup"])
        self.assertIn("duplicate_run_id", report["rows"][0]["findings"])

    def test_cli_validates_schema_and_queries_rows(self):
        """Verify CLI uses schema validation and query access."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "audit.json"
            runner = FakeRunner([valid_summary("valid")])
            argv = [
                "audit_bigquery_benchmark_summaries.py",
                "--project-id",
                "example-project",
                "--dataset-id",
                "silicon_boutique",
                "--table-id",
                "benchmark_summaries",
                "--location",
                "US",
                "--schema",
                str(BIGQUERY_SCHEMA),
                "--report-output",
                str(output),
                "--limit",
                "5",
            ]

            with mock.patch.object(sys, "argv", argv), mock.patch.object(auditor, "run_bq", runner):
                exit_code = auditor.main()

            payload = json.loads(output.read_text(encoding="utf-8"))
            query = runner.commands[1][-1]
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "pass")
            self.assertIn("ORDER BY benchmark_start DESC LIMIT 5", query)


def valid_summary(
    run_id,
    *,
    cloud_provider="gcp",
    duration_seconds=1200,
    request_total=120000,
    avg_rps=100.0,
    cpu_platform="intel-sapphire-rapids",
):
    """Return a valid summary row."""
    return {
        "architecture": "x86_64",
        "avg_requests_per_second": avg_rps,
        "benchmark_compute_cost_usd": 0.04 if cloud_provider != "local" else None,
        "benchmark_end": "2026-05-07T12:20:00Z",
        "benchmark_start": "2026-05-07T12:00:00Z",
        "cloud_provider": cloud_provider,
        "cost_per_1m_requests_usd": 0.3 if cloud_provider != "local" else None,
        "cpu_platform": cpu_platform,
        "duration_seconds": duration_seconds,
        "empty_metrics": [],
        "environment": cloud_provider,
        "generated_at": "2026-05-07T12:21:00Z",
        "invalid_metric_samples": {},
        "machine_type": "e2-standard-4" if cloud_provider != "local" else "local",
        "metrics_coverage_ratio": 1.0,
        "missing_metrics": [],
        "namespace": run_id,
        "node_count": 1,
        "node_hourly_price_usd": 0.12 if cloud_provider != "local" else None,
        "pricing_model": "spot" if cloud_provider != "local" else "local",
        "processor_family": "e2" if cloud_provider != "local" else "local",
        "region": "us-central1" if cloud_provider != "local" else "local",
        "request_count_total": request_total,
        "request_failure_count": 0,
        "request_success_count": request_total,
        "run_id": run_id,
        "summary_status": "complete",
        "zone": "us-central1-a" if cloud_provider != "local" else "local",
    }


if __name__ == "__main__":
    unittest.main()
