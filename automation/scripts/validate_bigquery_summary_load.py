#!/usr/bin/env python3
"""Guarded BigQuery load/query validation for benchmark summary rows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import load_benchmark_summary_to_bigquery as loader


class BigQueryValidationError(RuntimeError):
    """Raised when the guarded BigQuery validation cannot prove the row."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load one BenchmarkSummary row, query it by run_id, and optionally delete the test row."
    )
    parser.add_argument("--summary-store", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument(
        "--cleanup-row",
        action="store_true",
        help="Delete only the validated run_id row after the query proof succeeds.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = base_report(args)
    try:
        load_report = args.report_output.parent / "bigquery-validation-load-report.json"
        load_one_row(args=args, load_report=load_report)
        query_result = query_loaded_row(args=args, runner=run_bq)
        report.update(
            {
                "status": "validated",
                "load_report_path": str(load_report),
                "query_row_count": query_result["row_count"],
                "queried_run_ids": query_result["run_ids"],
            }
        )
        if args.cleanup_row:
            cleanup_loaded_row(args=args, runner=run_bq)
            report["cleanup_status"] = "deleted_test_row"
        write_json(args.report_output, report)
    except (BigQueryValidationError, loader.BigQueryLoadError) as exc:
        report.update({"status": "failed", "error": str(exc)})
        write_json(args.report_output, report)
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def base_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "status": "pending",
        "summary_table": loader.table_sql_name(args.project_id, args.dataset_id, args.table_id),
        "run_id": args.run_id,
        "summary_store": str(args.summary_store),
        "cleanup_status": "not_requested",
        "error": None,
    }


def load_one_row(*, args: argparse.Namespace, load_report: Path) -> None:
    rows = loader.select_rows(loader.read_summary_rows(args.summary_store), args.run_id)
    schema = loader.load_bigquery_schema(args.schema)
    loader.validate_destination(args.project_id, args.dataset_id, args.table_id, args.location)
    loader.validate_table_schema(
        project_id=args.project_id,
        dataset_id=args.dataset_id,
        table_id=args.table_id,
        expected_schema=schema,
        runner=loader.run_bq,
    )
    duplicate_run_ids = loader.existing_run_ids(
        project_id=args.project_id,
        dataset_id=args.dataset_id,
        table_id=args.table_id,
        location=args.location,
        run_ids=[args.run_id],
        runner=loader.run_bq,
    )
    if duplicate_run_ids:
        raise BigQueryValidationError(
            "BigQuery validation row already exists: " + ", ".join(sorted(duplicate_run_ids))
        )
    loader.load_rows(
        rows=rows,
        project_id=args.project_id,
        dataset_id=args.dataset_id,
        table_id=args.table_id,
        location=args.location,
        schema=args.schema,
        runner=loader.run_bq,
    )
    write_json(
        load_report,
        {
            "status": "loaded",
            "summary_table": loader.table_sql_name(args.project_id, args.dataset_id, args.table_id),
            "row_count": len(rows),
            "run_ids": [args.run_id],
        },
    )


def query_loaded_row(*, args: argparse.Namespace, runner: Runner) -> dict[str, Any]:
    query = (
        "SELECT run_id FROM "
        f"`{loader.table_sql_name(args.project_id, args.dataset_id, args.table_id)}` "
        f"WHERE run_id = {loader.sql_string(args.run_id)}"
    )
    result = runner(
        [
            "bq",
            "query",
            "--nouse_legacy_sql",
            "--format=json",
            "--project_id",
            args.project_id,
            "--location",
            args.location,
            query,
        ]
    )
    if result.returncode != 0:
        raise BigQueryValidationError("failed to query loaded BigQuery row: " + result.stderr.strip())
    rows = json.loads(result.stdout or "[]")
    run_ids = [row.get("run_id") for row in rows if isinstance(row, dict)]
    if run_ids != [args.run_id]:
        raise BigQueryValidationError("BigQuery query did not return exactly the validation run_id")
    return {"row_count": len(run_ids), "run_ids": run_ids}


def cleanup_loaded_row(*, args: argparse.Namespace, runner: Runner) -> None:
    query = (
        "DELETE FROM "
        f"`{loader.table_sql_name(args.project_id, args.dataset_id, args.table_id)}` "
        f"WHERE run_id = {loader.sql_string(args.run_id)}"
    )
    result = runner(
        [
            "bq",
            "query",
            "--nouse_legacy_sql",
            "--project_id",
            args.project_id,
            "--location",
            args.location,
            query,
        ]
    )
    if result.returncode != 0:
        raise BigQueryValidationError("failed to delete validation BigQuery row: " + result.stderr.strip())


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
        raise BigQueryValidationError("bq command was not found in PATH") from exc
    return CommandResult(result.returncode, result.stdout, result.stderr)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
