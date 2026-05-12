import json
import os
import unittest


from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = REPO_ROOT / "mcp-server" / "src"
sys.path.insert(0, str(MCP_SRC))

from silicon_boutique_mcp.bigquery_history import (  # noqa: E402
    BigQueryHistoryConfig,
    BigQueryHistoryError,
    BigQueryHistoryStore,
    CommandResult,
    build_history_query,
    sql_string,
    summary_references_from_json,
)


class BigQueryHistoryTest(unittest.TestCase):
    def config(self):
        return BigQueryHistoryConfig(
            project_id="example-project",
            dataset_id="silicon_boutique",
            table_id="benchmark_summaries",
            location="US",
        )

    def row(self, **overrides):
        values = {
            "run_id": "run-a",
            "machine_type": "c3-standard-4",
            "processor_family": "c3",
            "architecture": "x86_64",
            "cloud_provider": "gcp",
            "region": "us-central1",
            "zone": "us-central1-a",
            "node_count": 1,
            "pricing_model": "spot",
            "summary_status": "complete",
            "cpu_platform": "intel-sapphire-rapids",
            "benchmark_start": "2026-05-07T12:00:00Z",
            "benchmark_end": "2026-05-07T12:20:00Z",
            "avg_cpu_usage_cores": 2.1,
            "frontend_latency_p99_ms": 145.0,
            "cost_per_1m_requests_usd": 0.42,
            "missing_metrics": [],
            "empty_metrics": [],
        }
        values.update(overrides)
        return values

    def test_config_from_env_uses_defaults(self):
        config = BigQueryHistoryConfig.from_env(
            {
                "GOOGLE_CLOUD_PROJECT": "example-project",
                "SILICON_BOUTIQUE_BQ_COMMAND": "/tmp/fake-bq",
            }
        )

        self.assertEqual(config.project_id, "example-project")
        self.assertEqual(config.dataset_id, "silicon_boutique")
        self.assertEqual(config.table_id, "benchmark_summaries")
        self.assertEqual(config.location, "US")
        self.assertEqual(config.bq_command, "/tmp/fake-bq")

    def test_config_from_env_requires_project(self):
        with self.assertRaises(BigQueryHistoryError):
            BigQueryHistoryConfig.from_env({})

    def test_invalid_destination_config_is_rejected(self):
        invalid_configs = [
            BigQueryHistoryConfig(project_id="Example_Project"),
            BigQueryHistoryConfig(project_id="example-project", dataset_id="bad-name"),
            BigQueryHistoryConfig(project_id="example-project", table_id="bad.name"),
            BigQueryHistoryConfig(project_id="example-project", location="US/EAST"),
        ]
        for config in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaises(BigQueryHistoryError):
                    BigQueryHistoryStore(config, FakeRunner([]))

    def test_sql_string_escapes_quotes_and_backslashes(self):
        self.assertEqual(sql_string("c3'\\x"), "'c3\\'\\\\x'")

    def test_build_history_query_selects_expected_fields_and_filters(self):
        query = build_history_query(
            config=self.config(),
            filters={
                "machine_type": "c3-standard-4",
                "processor_family": "c3",
                "architecture": "x86_64",
            },
            limit=5,
        )

        self.assertIn(
            "FROM `example-project.silicon_boutique.benchmark_summaries`",
            query,
        )
        self.assertIn("machine_type = 'c3-standard-4'", query)
        self.assertIn("processor_family = 'c3'", query)
        self.assertIn("architecture = 'x86_64'", query)
        self.assertIn("ORDER BY benchmark_start DESC", query)
        self.assertTrue(query.endswith("LIMIT 5"))
        self.assertIn("run_id, machine_type, processor_family", query)
        self.assertNotIn("SELECT *", query)

    def test_query_historical_metrics_runs_bq_and_maps_rows(self):
        runner = FakeRunner([self.row(), self.row(run_id="run-b", cost_per_1m_requests_usd=None)])
        store = BigQueryHistoryStore(self.config(), runner)

        results = store.query_historical_metrics(
            machine_type="c3-standard-4",
            processor_family="c3",
            architecture="x86_64",
            limit=2,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].run_id, "run-a")
        self.assertEqual(results[0].node_count, 1)
        self.assertEqual(results[0].frontend_latency_p99_ms, 145.0)
        self.assertEqual(results[0].missing_metrics, ())
        self.assertIsNone(results[1].cost_per_1m_requests_usd)
        command = runner.commands[0]
        self.assertEqual(command[:4], ["bq", "--format=json", "--project_id", "example-project"])
        self.assertEqual(command[4:8], ["--location", "US", "query", "--nouse_legacy_sql"])

    def test_query_historical_metrics_returns_empty_results(self):
        store = BigQueryHistoryStore(self.config(), FakeRunner([]))

        self.assertEqual(store.query_historical_metrics(), [])

    def test_summary_mapping_skips_non_object_rows(self):
        results = summary_references_from_json(
            json.dumps([self.row(run_id="run-a"), "skip-me", self.row(run_id="run-b")])
        )

        self.assertEqual([result.run_id for result in results], ["run-a", "run-b"])

    def test_command_failure_and_invalid_json_are_reported_without_secrets(self):
        store = BigQueryHistoryStore(
            self.config(),
            FakeRunner([], returncode=1, stderr="permission denied"),
        )
        with self.assertRaises(BigQueryHistoryError) as command_context:
            store.query_historical_metrics()
        self.assertIn("permission denied", str(command_context.exception))

        with self.assertRaises(BigQueryHistoryError) as json_context:
            summary_references_from_json("not-json")
        self.assertIn("not return valid JSON", str(json_context.exception))
        self.assertNotIn("GOOGLE", str(json_context.exception))

    @unittest.skipUnless(
        os.environ.get("SILICON_BOUTIQUE_ENABLE_BIGQUERY_INTEGRATION") == "1",
        "guarded BigQuery integration test is disabled by default",
    )
    def test_guarded_integration_queries_bigquery_history(self):
        store = BigQueryHistoryStore.from_env()

        rows = store.query_historical_metrics(limit=1)

        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(rows[0].run_id)


class FakeRunner:
    def __init__(self, rows, *, returncode=0, stderr=""):
        self.rows = rows
        self.returncode = returncode
        self.stderr = stderr
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        return CommandResult(
            returncode=self.returncode,
            stdout=json.dumps(self.rows),
            stderr=self.stderr,
        )


if __name__ == "__main__":
    unittest.main()
