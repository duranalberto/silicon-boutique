"""Tests for test workflow trace helpers."""

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "automation" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import render_acceptance_summary
import write_workflow_trace


class WorkflowTraceHelpersTest(unittest.TestCase):
    """Unit tests covering workflow Trace Helpers behavior.
    """
    def test_build_trace_preserves_artifact_keys_and_env_values(self):
        """Verify build trace preserves artifact keys and environment values.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = Path(tmpdir)
            (artifacts / "benchmark-summary.json").write_text("{}", encoding="utf-8")
            env = {
                "RUN_ID": "gha-123-1",
                "ENVIRONMENT": "gcp",
                "PROJECT_ID": "valid-proj1",
                "REGION": "us-central1",
                "ZONE": "us-central1-a",
                "MACHINE_TYPE": "e2-standard-4",
                "PROCESSOR_FAMILY": "e2",
                "ARCHITECTURE": "x86_64",
                "NODE_COUNT": "1",
                "PRICING_MODEL": "spot",
                "BENCHMARK_START": "2026-05-10T00:00:00Z",
                "BENCHMARK_END": "2026-05-10T00:20:00Z",
                "SUMMARY_ARTIFACT_NAME": "benchmark-gha-123-1",
                "BIGQUERY_DATASET": "silicon_boutique",
                "BIGQUERY_TABLE": "benchmark_summaries",
                "BIGQUERY_LOCATION": "US",
            }

            trace = write_workflow_trace.build_trace(
                artifacts,
                artifacts / "workflow-trace.json",
                env,
            )

            self.assertEqual(trace["benchmark"]["run_id"], "gha-123-1")
            self.assertEqual(trace["benchmark"]["cloud_provider"], "gcp")
            self.assertEqual(trace["gcp"]["project_id"], "valid-proj1")
            self.assertEqual(trace["bigquery"]["summary_table"], "valid-proj1.silicon_boutique.benchmark_summaries")
            self.assertEqual(trace["artifacts"]["summary_exists"], "true")
            self.assertIn("loadgenerator_stats_path", trace["artifacts"])
            self.assertEqual(trace["teardown"]["destroy_succeeded"], "pending")

    def test_render_acceptance_summary_matches_workflow_table(self):
        """Verify render acceptance summary matches workflow table.


        Returns:
            None.
        """
        markdown = render_acceptance_summary.render_summary(
            {
                "status": "passed",
                "run_id": "gha-123-1",
                "artifacts_dir": "artifacts",
                "checks": {
                    "bigquery": {"summary_table": "project.dataset.table"},
                    "dashboard": {
                        "dashboard_uid": "silicon-boutique-online-boutique",
                        "dashboard_title": "SiliconBoutique Online Boutique Benchmark",
                    },
                },
            }
        )

        self.assertIn("### Acceptance Demo", markdown)
        self.assertIn("| status | `passed` |", markdown)
        self.assertIn("| bigquery_summary_table | `project.dataset.table` |", markdown)


if __name__ == "__main__":
    unittest.main()
