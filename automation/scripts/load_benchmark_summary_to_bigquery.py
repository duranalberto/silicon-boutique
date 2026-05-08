#!/usr/bin/env python3
"""Load canonical SiliconBoutique benchmark summaries into BigQuery."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
LOCATION_RE = re.compile(r"^[A-Za-z0-9-]+$")


class BigQueryLoadError(RuntimeError):
    """Raised when a benchmark summary cannot be loaded safely."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load BenchmarkSummary NDJSON rows into BigQuery."
    )
    parser.add_argument("--summary-store", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--load-report-output", type=Path, required=True)
    parser.add_argument(
        "--duplicate-policy",
        choices=("fail",),
        default="fail",
        help="Duplicate run_id handling. P7.2 supports immutable rows only.",
    )
    parser.add_argument(
        "--run-id",
        help="Load only one run_id from a multi-row store. Without this, the store must contain exactly one row.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the input, destination table, schema, and duplicate status without loading rows.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report: dict[str, Any] = base_report(args)
    try:
        rows = read_summary_rows(args.summary_store)
        selected_rows = select_rows(rows, args.run_id)
        schema = load_bigquery_schema(args.schema)
        validate_destination(args.project_id, args.dataset_id, args.table_id, args.location)
        validate_table_schema(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            expected_schema=schema,
            runner=run_bq,
        )
        duplicate_run_ids = existing_run_ids(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            location=args.location,
            run_ids=[row["run_id"] for row in selected_rows],
            runner=run_bq,
        )
        if duplicate_run_ids:
            raise BigQueryLoadError(
                "BigQuery table already contains run_id values: "
                + ", ".join(sorted(duplicate_run_ids))
            )
        if not args.dry_run:
            load_rows(
                rows=selected_rows,
                project_id=args.project_id,
                dataset_id=args.dataset_id,
                table_id=args.table_id,
                location=args.location,
                schema=args.schema,
                runner=run_bq,
            )
        report.update(
            {
                "status": "validated" if args.dry_run else "loaded",
                "row_count": len(selected_rows),
                "run_ids": [row["run_id"] for row in selected_rows],
            }
        )
        write_json(args.load_report_output, report)
    except BigQueryLoadError as exc:
        report.update({"status": "failed", "error": str(exc)})
        write_json(args.load_report_output, report)
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def base_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "status": "pending",
        "project_id": args.project_id,
        "dataset_id": args.dataset_id,
        "table_id": args.table_id,
        "location": args.location,
        "summary_table": table_sql_name(args.project_id, args.dataset_id, args.table_id),
        "summary_store": str(args.summary_store),
        "schema": str(args.schema),
        "duplicate_policy": args.duplicate_policy,
        "dry_run": args.dry_run,
        "row_count": 0,
        "run_ids": [],
        "error": None,
    }


def read_summary_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise BigQueryLoadError(f"summary store does not exist: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BigQueryLoadError(
                f"summary store contains invalid JSON on line {line_number}: {path}"
            ) from exc
        if not isinstance(row, dict):
            raise BigQueryLoadError(
                f"summary store line {line_number} is not a JSON object: {path}"
            )
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise BigQueryLoadError(
                f"summary store line {line_number} is missing a non-empty run_id"
            )
        rows.append(row)
    if not rows:
        raise BigQueryLoadError(f"summary store contains no rows: {path}")
    return rows


def select_rows(rows: list[dict[str, Any]], run_id: str | None) -> list[dict[str, Any]]:
    if run_id:
        selected = [row for row in rows if row.get("run_id") == run_id]
        if len(selected) != 1:
            raise BigQueryLoadError(
                f"expected exactly one summary row for run_id {run_id!r}, found {len(selected)}"
            )
        return selected
    if len(rows) != 1:
        raise BigQueryLoadError(
            "summary store must contain exactly one row unless --run-id selects one row"
        )
    return rows


def load_bigquery_schema(path: Path) -> list[dict[str, Any]]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BigQueryLoadError(f"BigQuery schema does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BigQueryLoadError(f"BigQuery schema is not valid JSON: {path}") from exc
    if not isinstance(schema, list) or not schema:
        raise BigQueryLoadError(f"BigQuery schema must be a non-empty field array: {path}")
    for field in schema:
        if not isinstance(field, dict) or not field.get("name") or not field.get("type"):
            raise BigQueryLoadError(f"BigQuery schema contains an invalid field: {path}")
    return schema


def validate_destination(
    project_id: str, dataset_id: str, table_id: str, location: str
) -> None:
    if not PROJECT_RE.match(project_id):
        raise BigQueryLoadError(f"invalid GCP project_id: {project_id}")
    for label, value in (("dataset_id", dataset_id), ("table_id", table_id)):
        if not IDENTIFIER_RE.match(value):
            raise BigQueryLoadError(f"invalid BigQuery {label}: {value}")
    if not LOCATION_RE.match(location):
        raise BigQueryLoadError(f"invalid BigQuery location: {location}")


def validate_table_schema(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    expected_schema: list[dict[str, Any]],
    runner: Runner,
) -> None:
    result = runner(
        [
            "bq",
            "show",
            "--format=json",
            "--project_id",
            project_id,
            table_ref(project_id, dataset_id, table_id),
        ]
    )
    if result.returncode != 0:
        raise BigQueryLoadError(
            "failed to inspect BigQuery table "
            f"{table_sql_name(project_id, dataset_id, table_id)}: {result.stderr.strip()}"
        )
    try:
        table = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BigQueryLoadError("bq show did not return valid JSON") from exc
    actual_fields = table.get("schema", {}).get("fields")
    if not isinstance(actual_fields, list):
        raise BigQueryLoadError("bq show response did not include schema.fields")
    expected = schema_signature(expected_schema)
    actual = schema_signature(actual_fields)
    if actual != expected:
        raise BigQueryLoadError("BigQuery table schema does not match benchmark summary schema")


def existing_run_ids(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    location: str,
    run_ids: list[str],
    runner: Runner,
) -> set[str]:
    run_id_literals = ", ".join(sql_string(run_id) for run_id in run_ids)
    query = (
        "SELECT run_id FROM "
        f"`{table_sql_name(project_id, dataset_id, table_id)}` "
        f"WHERE run_id IN ({run_id_literals})"
    )
    result = runner(
        [
            "bq",
            "query",
            "--nouse_legacy_sql",
            "--format=json",
            "--project_id",
            project_id,
            "--location",
            location,
            query,
        ]
    )
    if result.returncode != 0:
        raise BigQueryLoadError(
            "failed to query existing BigQuery run IDs: " + result.stderr.strip()
        )
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise BigQueryLoadError("bq query did not return valid JSON") from exc
    if not isinstance(rows, list):
        raise BigQueryLoadError("bq query did not return a row array")
    return {
        row["run_id"]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("run_id"), str)
    }


def load_rows(
    *,
    rows: list[dict[str, Any]],
    project_id: str,
    dataset_id: str,
    table_id: str,
    location: str,
    schema: Path,
    runner: Runner,
) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".ndjson") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        result = runner(
            [
                "bq",
                "load",
                "--source_format=NEWLINE_DELIMITED_JSON",
                "--project_id",
                project_id,
                "--location",
                location,
                table_ref(project_id, dataset_id, table_id),
                handle.name,
                str(schema),
            ]
        )
    if result.returncode != 0:
        raise BigQueryLoadError("failed to load BigQuery summary rows: " + result.stderr.strip())


def schema_signature(fields: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [
        (
            str(field.get("name", "")),
            str(field.get("type", "")).upper(),
            str(field.get("mode", "NULLABLE")).upper(),
        )
        for field in fields
    ]


def table_ref(project_id: str, dataset_id: str, table_id: str) -> str:
    return f"{project_id}:{dataset_id}.{table_id}"


def table_sql_name(project_id: str, dataset_id: str, table_id: str) -> str:
    return f"{project_id}.{dataset_id}.{table_id}"


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def run_bq(command: list[str]) -> CommandResult:
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise BigQueryLoadError("bq command was not found in PATH") from exc
    return CommandResult(result.returncode, result.stdout, result.stderr)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
