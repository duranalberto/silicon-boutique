import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared import automation
from silicon_boutique_shared import bigquery


class SharedAutomationUtilitiesTest(unittest.TestCase):
    def test_json_and_ndjson_helpers_create_parent_directories(self):
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
        self.assertEqual(automation.parse_duration_seconds("20m"), 1200)
        self.assertEqual(automation.parse_duration_seconds("2h"), 7200)
        self.assertEqual(automation.parse_duration_seconds("15s"), 15)
        self.assertEqual(
            automation.shell_join(["terraform", "plan", "-var=run_id=local one"]),
            "terraform plan '-var=run_id=local one'",
        )
        with self.assertRaises(ValueError):
            automation.parse_duration_seconds("0s")


class SharedBigQueryUtilitiesTest(unittest.TestCase):
    def test_destination_validation_and_sql_escaping(self):
        bigquery.validate_destination("valid-proj1", "dataset_1", "table_1", "US")
        self.assertEqual(bigquery.table_ref("valid-proj1", "ds", "tbl"), "valid-proj1:ds.tbl")
        self.assertEqual(bigquery.table_sql_name("valid-proj1", "ds", "tbl"), "valid-proj1.ds.tbl")
        self.assertEqual(bigquery.sql_string("a'b\\c"), "'a\\'b\\\\c'")

        with self.assertRaises(bigquery.BigQueryHelperError):
            bigquery.validate_destination("INVALID", "dataset_1", "table_1", "US")

    def test_parse_bq_json_array_rejects_malformed_payloads(self):
        self.assertEqual(
            bigquery.parse_bq_json_array(json.dumps([{"run_id": "one"}, "ignored"])),
            [{"run_id": "one"}],
        )
        with self.assertRaises(bigquery.BigQueryHelperError):
            bigquery.parse_bq_json_array("{}", label="history query")
        with self.assertRaises(bigquery.BigQueryHelperError):
            bigquery.parse_bq_json_array("{", label="history query")


if __name__ == "__main__":
    unittest.main()
