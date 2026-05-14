#!/usr/bin/env python3
"""Command-line workflow for load benchmark summary to BigQuery in the benchmark automation pipeline.


The module exposes a CLI entrypoint plus focused helper functions so tests can exercise the workflow without running external infrastructure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared import bigquery as bq_helpers
from silicon_boutique_shared.automation import write_json


class BigQueryLoadError(RuntimeError):
    """Raised when a benchmark summary cannot be loaded safely."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "validation",
        diagnostics: dict[str, Any] | None = None,
    ):
        """Initialize the object with the provided configuration.


        Args:
            message: message (str) used by this operation.
            stage: stage (str) used by this operation.
            diagnostics: diagnostics (dict[str, Any] | None) used by this operation.

        Returns:
            None.
        """
        super().__init__(message)
        self.stage = stage
        self.diagnostics = diagnostics or {}


CommandResult = bq_helpers.CommandResult
Runner = bq_helpers.Runner
PREVIEW_LIMIT = 600


def parse_args() -> argparse.Namespace:
    """Parse arguments.


    Returns:
        argparse.Namespace value produced by parse arguments.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    parser = argparse.ArgumentParser(
        description="Load BenchmarkSummary NDJSON rows into bigquery."
    )
    parser.add_argument("--summary-store", type=Path)
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
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate the destination table, schema, and query access without reading or loading summaries.",
    )
    parser.add_argument(
        "--preflight-write-probe",
        action="store_true",
        help="During --preflight-only, load and delete a run-scoped scratch table to verify BigQuery write permissions.",
    )
    args = parser.parse_args()
    if args.preflight_write_probe and not args.preflight_only:
        parser.error("--preflight-write-probe requires --preflight-only")
    if not args.preflight_only and args.summary_store is None:
        parser.error("--summary-store is required unless --preflight-only is set")
    return args


def main() -> int:
    """Run the command-line entrypoint.


    Returns:
        Process exit code for the command.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    args = parse_args()
    report: dict[str, Any] = base_report(args)
    try:
        schema = load_bigquery_schema(args.schema)
        validate_destination(args.project_id, args.dataset_id, args.table_id, args.location)
        validate_table_schema(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            expected_schema=schema,
            runner=run_bq,
        )
        validate_query_access(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            location=args.location,
            runner=run_bq,
        )
        if args.preflight_only:
            scratch_table_id = None
            if args.preflight_write_probe:
                scratch_table_id = preflight_write_probe(
                    project_id=args.project_id,
                    dataset_id=args.dataset_id,
                    location=args.location,
                    schema=args.schema,
                    run_id=args.run_id,
                    runner=run_bq,
                )
            report.update(
                {
                    "status": "validated",
                    "stage": "preflight",
                    "preflight_write_probe": args.preflight_write_probe,
                    "preflight_scratch_table_id": scratch_table_id,
                }
            )
            write_json(args.load_report_output, report)
            return 0
        rows = read_summary_rows(args.summary_store)
        selected_rows = select_rows(rows, args.run_id)
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
                "stage": "complete",
                "row_count": len(selected_rows),
                "run_ids": [row["run_id"] for row in selected_rows],
            }
        )
        write_json(args.load_report_output, report)
    except BigQueryLoadError as exc:
        report.update(
            {
                "status": "failed",
                "stage": exc.stage,
                "error": str(exc),
                "diagnostics": exc.diagnostics,
            }
        )
        write_json(args.load_report_output, report)
        print(format_load_error(exc), file=sys.stderr)
        return 2
    return 0


def base_report(args: argparse.Namespace) -> dict[str, Any]:
    """Compute base report.


    Args:
        args: arguments (argparse.Namespace) used by this operation.

    Returns:
        dict[str, Any] value produced by base report.
    """
    return {
        "status": "pending",
        "project_id": args.project_id,
        "dataset_id": args.dataset_id,
        "table_id": args.table_id,
        "location": args.location,
        "summary_table": bq_helpers.table_sql_name(
            args.project_id, args.dataset_id, args.table_id
        ),
        "summary_store": str(args.summary_store),
        "schema": str(args.schema),
        "duplicate_policy": args.duplicate_policy,
        "dry_run": args.dry_run,
        "preflight_only": args.preflight_only,
        "preflight_write_probe": args.preflight_write_probe,
        "preflight_scratch_table_id": None,
        "stage": "pending",
        "row_count": 0,
        "run_ids": [],
        "error": None,
        "diagnostics": {},
    }


def read_summary_rows(path: Path) -> list[dict[str, Any]]:
    """Read summary rows.


    Args:
        path: path (Path) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by read summary rows.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
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
    """Select rows.


    Args:
        rows: rows (list[dict[str, Any]]) used by this operation.
        run_id: run ID (str | None) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by select rows.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
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
    """Load BigQuery schema.


    Args:
        path: path (Path) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by load BigQuery schema.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
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
    """Validate destination.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        location: location (str) used by this operation.

    Returns:
        None.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        bq_helpers.validate_destination(project_id, dataset_id, table_id, location)
    except bq_helpers.BigQueryHelperError as exc:
        raise BigQueryLoadError(str(exc)) from exc


def validate_table_schema(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    expected_schema: list[dict[str, Any]],
    runner: Runner,
) -> None:
    """Validate table schema.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        expected_schema: expected schema (list[dict[str, Any]]) used by this operation.
        runner: runner (Runner) used by this operation.

    Returns:
        None.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    result = runner(
        bq_helpers.show_table_command(project_id, dataset_id, table_id)
    )
    if result.returncode != 0:
        raise BigQueryLoadError(
            "failed to inspect BigQuery table "
            f"{bq_helpers.table_sql_name(project_id, dataset_id, table_id)}",
            stage="bq_show_schema",
            diagnostics=command_diagnostics(result),
        )
    table = parse_bq_json_object(result, stage="bq_show_schema", label="bq show")
    actual_fields = table.get("schema", {}).get("fields")
    if not isinstance(actual_fields, list):
        raise BigQueryLoadError(
            "bq show response did not include schema.fields",
            stage="bq_show_schema",
            diagnostics=command_diagnostics(result),
        )
    expected = schema_signature(expected_schema)
    actual = schema_signature(actual_fields)
    if actual != expected:
        raise BigQueryLoadError(
            "BigQuery table schema does not match benchmark summary schema",
            stage="bq_show_schema",
        )


def validate_query_access(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    location: str,
    runner: Runner,
) -> None:
    """Validate query access.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        location: location (str) used by this operation.
        runner: runner (Runner) used by this operation.

    Returns:
        None.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    query = (
        "SELECT run_id FROM "
        f"`{bq_helpers.table_sql_name(project_id, dataset_id, table_id)}` "
        "WHERE FALSE LIMIT 0"
    )
    result = runner(bq_helpers.query_command(project_id, location, query))
    if result.returncode != 0:
        raise BigQueryLoadError(
            "failed to run BigQuery preflight query",
            stage="bq_preflight_query",
            diagnostics=command_diagnostics(result),
        )
    parse_bq_json_array(result, stage="bq_preflight_query", label="bq preflight query")


def existing_run_ids(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    location: str,
    run_ids: list[str],
    runner: Runner,
) -> set[str]:
    """Compute existing run IDs.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        location: location (str) used by this operation.
        run_ids: run IDs (list[str]) used by this operation.
        runner: runner (Runner) used by this operation.

    Returns:
        set[str] value produced by existing run IDs.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    run_id_literals = ", ".join(bq_helpers.sql_string(run_id) for run_id in run_ids)
    query = (
        "SELECT run_id FROM "
        f"`{bq_helpers.table_sql_name(project_id, dataset_id, table_id)}` "
        f"WHERE run_id IN ({run_id_literals})"
    )
    result = runner(
        bq_helpers.query_command(project_id, location, query)
    )
    if result.returncode != 0:
        raise BigQueryLoadError(
            "failed to query existing BigQuery run IDs",
            stage="bq_duplicate_query",
            diagnostics=command_diagnostics(result),
        )
    rows = parse_bq_json_array(result, stage="bq_duplicate_query", label="bq duplicate query")
    return {
        row["run_id"]
        for row in rows
        if isinstance(row.get("run_id"), str)
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
    """Load rows.


    Args:
        rows: rows (list[dict[str, Any]]) used by this operation.
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        location: location (str) used by this operation.
        schema: schema (Path) used by this operation.
        runner: runner (Runner) used by this operation.

    Returns:
        None.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".ndjson") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        result = runner(
            bq_helpers.load_command(
                project_id,
                dataset_id,
                table_id,
                location,
                handle.name,
                str(schema),
            )
        )
    if result.returncode != 0:
        raise BigQueryLoadError(
            "failed to load BigQuery summary rows",
            stage="bq_load",
            diagnostics=command_diagnostics(result),
        )


def preflight_write_probe(
    *,
    project_id: str,
    dataset_id: str,
    location: str,
    schema: Path,
    run_id: str | None,
    runner: Runner,
) -> str:
    """Compute preflight write probe.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        location: location (str) used by this operation.
        schema: schema (Path) used by this operation.
        run_id: run ID (str | None) used by this operation.
        runner: runner (Runner) used by this operation.

    Returns:
        str value produced by preflight write probe.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    scratch_table_id = preflight_scratch_table_id(run_id)
    probe_row = preflight_probe_row(run_id)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".ndjson") as handle:
        handle.write(json.dumps(probe_row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        load_result = runner(
            bq_helpers.load_command(
                project_id,
                dataset_id,
                scratch_table_id,
                location,
                handle.name,
                str(schema),
            )
        )
    cleanup_result = runner(
        bq_helpers.delete_table_command(project_id, dataset_id, scratch_table_id)
    )
    if load_result.returncode != 0:
        raise BigQueryLoadError(
            "failed to load BigQuery preflight write probe rows",
            stage="bq_preflight_write_probe",
            diagnostics={
                **command_diagnostics(load_result),
                "scratch_table_id": scratch_table_id,
                "cleanup": command_diagnostics(cleanup_result),
            },
        )
    if cleanup_result.returncode != 0:
        raise BigQueryLoadError(
            "failed to delete BigQuery preflight scratch table",
            stage="bq_preflight_cleanup",
            diagnostics={
                **command_diagnostics(cleanup_result),
                "scratch_table_id": scratch_table_id,
            },
        )
    return scratch_table_id


def preflight_scratch_table_id(run_id: str | None) -> str:
    """Compute preflight scratch table ID.


    Args:
        run_id: run ID (str | None) used by this operation.

    Returns:
        str value produced by preflight scratch table ID.
    """
    suffix = re.sub(r"[^A-Za-z0-9_]+", "_", (run_id or "manual").strip()).strip("_")
    if not suffix:
        suffix = "manual"
    return ("sb_preflight_" + suffix.lower())[:1024]


def preflight_probe_row(run_id: str | None) -> dict[str, Any]:
    """Compute preflight probe row.


    Args:
        run_id: run ID (str | None) used by this operation.

    Returns:
        dict[str, Any] value produced by preflight probe row.
    """
    probe_run_id = run_id or "manual"
    timestamp = "2026-01-01T00:00:00Z"
    return {
        "run_id": f"{probe_run_id}-preflight",
        "namespace": probe_run_id,
        "environment": "preflight",
        "cloud_provider": "gcp",
        "region": "preflight",
        "zone": "preflight",
        "machine_type": "preflight",
        "processor_family": "preflight",
        "architecture": "x86_64",
        "node_count": 1,
        "pricing_model": "preflight",
        "benchmark_start": timestamp,
        "benchmark_end": timestamp,
        "duration_seconds": 1,
        "generated_at": timestamp,
        "missing_metrics": [],
        "empty_metrics": [],
        "summary_status": "preflight",
    }


def parse_bq_json_object(
    result: CommandResult,
    *,
    stage: str,
    label: str,
) -> dict[str, Any]:
    """Parse bigQuery JSON object.


    Args:
        result: result (CommandResult) used by this operation.
        stage: stage (str) used by this operation.
        label: label (str) used by this operation.

    Returns:
        dict[str, Any] value produced by parse BigQuery JSON object.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        payload = json.loads(bq_json_stdout(result.stdout, fallback="{}"))
    except json.JSONDecodeError as exc:
        raise BigQueryLoadError(
            f"{label} did not return valid JSON",
            stage=stage,
            diagnostics=command_diagnostics(result),
        ) from exc
    if not isinstance(payload, dict):
        raise BigQueryLoadError(
            f"{label} did not return a JSON object",
            stage=stage,
            diagnostics=command_diagnostics(result),
        )
    return payload


def parse_bq_json_array(
    result: CommandResult,
    *,
    stage: str,
    label: str,
) -> list[dict[str, Any]]:
    """Parse bigQuery JSON array.


    Args:
        result: result (CommandResult) used by this operation.
        stage: stage (str) used by this operation.
        label: label (str) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by parse BigQuery JSON array.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        return bq_helpers.parse_bq_json_array(
            bq_json_stdout(result.stdout, fallback="[]"),
            label=label,
        )
    except bq_helpers.BigQueryHelperError as exc:
        raise BigQueryLoadError(
            str(exc),
            stage=stage,
            diagnostics=command_diagnostics(result),
        ) from exc


def command_diagnostics(result: CommandResult) -> dict[str, Any]:
    """Compute command diagnostics.


    Args:
        result: result (CommandResult) used by this operation.

    Returns:
        dict[str, Any] value produced by command diagnostics.
    """
    return {
        "returncode": result.returncode,
        "stdout_preview": preview_text(result.stdout),
        "stderr_preview": preview_text(result.stderr),
    }


def format_load_error(exc: BigQueryLoadError) -> str:
    """Format load error.


    Args:
        exc: exc (BigQueryLoadError) used by this operation.

    Returns:
        str value produced by format load error.
    """
    lines = [str(exc)]
    if exc.stage:
        lines.append(f"stage: {exc.stage}")
    stdout_preview = exc.diagnostics.get("stdout_preview")
    stderr_preview = exc.diagnostics.get("stderr_preview")
    if stdout_preview:
        lines.append(f"stdout: {stdout_preview}")
    if stderr_preview:
        lines.append(f"stderr: {stderr_preview}")
    return "\n".join(lines)


def bq_json_stdout(value: str, *, fallback: str) -> str:
    """Compute bigQuery JSON standard output.


    Args:
        value: value (str) used by this operation.
        fallback: fallback (str) used by this operation.

    Returns:
        str value produced by bigQuery JSON standard output.
    """
    text = (value or "").strip()
    if not text:
        return fallback
    if text[0] in "[{":
        return text
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            prefix = "\n".join(lines[:index]).strip()
            if prefix and not all(is_ignorable_bq_stdout_line(item) for item in lines[:index]):
                break
            return "\n".join(lines[index:]).strip()
    return text


def is_ignorable_bq_stdout_line(value: str) -> bool:
    """Compute is ignorable BigQuery standard output line.


    Args:
        value: value (str) used by this operation.

    Returns:
        bool value produced by is ignorable BigQuery standard output line.
    """
    stripped = value.strip()
    return not stripped or stripped.startswith(("WARNING:", "WARN:", "INFO:"))


def preview_text(value: str) -> str:
    """Compute preview text.


    Args:
        value: value (str) used by this operation.

    Returns:
        str value produced by preview text.
    """
    text = redact_diagnostic_text(value or "").strip()
    if len(text) <= PREVIEW_LIMIT:
        return text
    return text[:PREVIEW_LIMIT] + "...<truncated>"


def redact_diagnostic_text(value: str) -> str:
    """Compute redact diagnostic text.


    Args:
        value: value (str) used by this operation.

    Returns:
        str value produced by redact diagnostic text.
    """
    patterns = [
        (r"(?i)(authorization:\s*)(bearer|basic)\s+\S+", r"\1<redacted>"),
        (r"(?i)((?:token|secret|password|credential)[A-Za-z0-9_ -]*[=:]\s*)\S+", r"\1<redacted>"),
        (r"gha-creds-[A-Za-z0-9._-]+\.json", "gha-creds-<redacted>.json"),
    ]
    redacted = value
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def schema_signature(fields: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Compute schema signature.


    Args:
        fields: fields (list[dict[str, Any]]) used by this operation.

    Returns:
        list[tuple[str, str, str]] value produced by schema signature.
    """
    return [
        (
            str(field.get("name", "")),
            str(field.get("type", "")).upper(),
            str(field.get("mode", "NULLABLE")).upper(),
        )
        for field in fields
    ]


def run_bq(command: list[str]) -> CommandResult:
    """Run bigQuery.


    Args:
        command: command (list[str]) used by this operation.

    Returns:
        CommandResult value produced by run bigquery.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        return bq_helpers.run_bq(command)
    except bq_helpers.BigQueryHelperError as exc:
        raise BigQueryLoadError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
