"""Tests for test shared utilities."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared import automation
from silicon_boutique_shared import bigquery as BigQuery


class SharedAutomationUtilitiesTest(unittest.TestCase):
    """Unit tests covering shared Automation Utilities behavior.
    """
    def test_json_and_ndjson_helpers_create_parent_directories(self):
        """Verify jSON and NDJSON helpers create parent directories.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            json_path = base / "nested" / "payload.json"
            ndjson_path = base / "nested" / "rows.ndjson"

            automation.write_json(json_path, {"b": 2, "a": 1})
            automation.write_ndjson(ndjson_path, [{"run_id": "one"}, {"run_id": "two"}])

            self.assertEqual(automation.read_json(json_path), {"a": 1, "b": 2})
            self.assertEqual(
                automation.read_ndjson(ndjson_path),
                [{"run_id": "one"}, {"run_id": "two"}],
            )

    def test_duration_and_shell_helpers_preserve_existing_forms(self):
        """Verify duration and shell helpers preserve existing forms.


        Returns:
            None.
        """
        self.assertEqual(automation.parse_duration_seconds("20m"), 1200)
        self.assertEqual(automation.parse_duration_seconds("2h"), 7200)
        self.assertEqual(automation.parse_duration_seconds("15s"), 15)
        self.assertEqual(automation.parse_duration_seconds("1500ms", allow_milliseconds=True), 1)
        self.assertEqual(
            automation.shell_join(["terraform", "plan", "-var=run_id=local one"]),
            "terraform plan '-var=run_id=local one'",
        )
        with self.assertRaises(ValueError):
            automation.parse_duration_seconds("0s")

    def test_first_env_returns_first_non_empty_value(self):
        """Verify first environment returns first non empty value.


        Returns:
            None.
        """
        self.assertEqual(
            automation.first_env({"PRIMARY": " ", "FALLBACK": " value "}, "PRIMARY", "FALLBACK"),
            "value",
        )
        self.assertEqual(automation.first_env({}, "MISSING"), "")


class SharedBigQueryUtilitiesTest(unittest.TestCase):
    """Unit tests covering shared Big Query Utilities behavior.
    """
    def test_destination_validation_and_sql_escaping(self):
        """Verify destination validation and SQL escaping.


        Returns:
            None.
        """
        BigQuery.validate_destination("valid-proj1", "dataset_1", "table_1", "US")
        self.assertEqual(BigQuery.table_ref("valid-proj1", "ds", "tbl"), "valid-proj1:ds.tbl")
        self.assertEqual(BigQuery.table_sql_name("valid-proj1", "ds", "tbl"), "valid-proj1.ds.tbl")
        self.assertEqual(BigQuery.sql_string("a'b\\c"), "'a\\'b\\\\c'")
        self.assertEqual(
            BigQuery.show_table_command("valid-proj1", "ds", "tbl"),
            ["bq", "--format=json", "--project_id", "valid-proj1", "show", "valid-proj1:ds.tbl"],
        )
        self.assertEqual(
            BigQuery.query_command("valid-proj1", "US", "SELECT 1"),
            [
                "bq",
                "--format=json",
                "--project_id",
                "valid-proj1",
                "--location",
                "US",
                "query",
                "--nouse_legacy_sql",
                "SELECT 1",
            ],
        )
        self.assertEqual(
            BigQuery.load_command("valid-proj1", "ds", "tbl", "US", "/tmp/rows.ndjson", "schema.json"),
            [
                "bq",
                "--project_id",
                "valid-proj1",
                "--location",
                "US",
                "load",
                "--source_format=NEWLINE_DELIMITED_JSON",
                "valid-proj1:ds.tbl",
                "/tmp/rows.ndjson",
                "schema.json",
            ],
        )
        self.assertEqual(
            BigQuery.delete_table_command("valid-proj1", "ds", "tbl"),
            [
                "bq",
                "--project_id",
                "valid-proj1",
                "rm",
                "-f",
                "-t",
                "valid-proj1:ds.tbl",
            ],
        )

        with self.assertRaises(BigQuery.BigQueryHelperError):
            BigQuery.validate_destination("INVALID", "dataset_1", "table_1", "US")

    def test_parse_bq_json_array_rejects_malformed_payloads(self):
        """Verify parse BigQuery JSON array rejects malformed payloads.


        Returns:
            None.
        """
        self.assertEqual(
            BigQuery.parse_bq_json_array(json.dumps([{"run_id": "one"}, "ignored"])),
            [{"run_id": "one"}],
        )
        with self.assertRaises(BigQuery.BigQueryHelperError):
            BigQuery.parse_bq_json_array("{}", label="history query")
        with self.assertRaises(BigQuery.BigQueryHelperError):
            BigQuery.parse_bq_json_array("{", label="history query")


if __name__ == "__main__":
    unittest.main()
