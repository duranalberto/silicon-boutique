"""Shared BigQuery CLI safety helpers."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
LOCATION_RE = re.compile(r"^[A-Za-z0-9-]+$")


class BigQueryHelperError(ValueError):
    """Raised when shared BigQuery helpers reject input or command output."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Container for command Result state and behavior.


    Attributes:
        returncode: returncode (int) stored on the object.
        stdout: standard output (str) stored on the object.
        stderr: standard error (str) stored on the object.
    """
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]


def validate_destination(project_id: str, dataset_id: str, table_id: str, location: str) -> None:
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
    if not PROJECT_RE.match(project_id):
        raise BigQueryHelperError(f"invalid GCP project_id: {project_id}")
    for label, value in (("dataset_id", dataset_id), ("table_id", table_id)):
        if not IDENTIFIER_RE.match(value):
            raise BigQueryHelperError(f"invalid BigQuery {label}: {value}")
    if not LOCATION_RE.match(location):
        raise BigQueryHelperError(f"invalid BigQuery location: {location}")


def table_ref(project_id: str, dataset_id: str, table_id: str) -> str:
    """Compute table ref.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.

    Returns:
        str value produced by table ref.
    """
    return f"{project_id}:{dataset_id}.{table_id}"


def table_sql_name(project_id: str, dataset_id: str, table_id: str) -> str:
    """Compute table SQL name.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.

    Returns:
        str value produced by table SQL name.
    """
    return f"{project_id}.{dataset_id}.{table_id}"


def sql_string(value: str) -> str:
    """Compute sQL string.


    Args:
        value: value (str) used by this operation.

    Returns:
        str value produced by sQL string.
    """
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def show_table_command(
    project_id: str,
    dataset_id: str,
    table_id: str,
    *,
    bq_command: str = "bq",
) -> list[str]:
    """Compute show table command.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        bq_command: bigQuery command (str) used by this operation.

    Returns:
        list[str] value produced by show table command.
    """
    return [
        bq_command,
        "--format=json",
        "--project_id",
        project_id,
        "show",
        table_ref(project_id, dataset_id, table_id),
    ]


def query_command(
    project_id: str,
    location: str,
    query: str,
    *,
    bq_command: str = "bq",
    format_json: bool = True,
) -> list[str]:
    """Query command.


    Args:
        project_id: project ID (str) used by this operation.
        location: location (str) used by this operation.
        query: query (str) used by this operation.
        bq_command: bigQuery command (str) used by this operation.
        format_json: format JSON (bool) used by this operation.

    Returns:
        list[str] value produced by query command.
    """
    command = [bq_command]
    if format_json:
        command.append("--format=json")
    command.extend(
        [
            "--project_id",
            project_id,
            "--location",
            location,
            "query",
            "--nouse_legacy_sql",
            query,
        ]
    )
    return command


def load_command(
    project_id: str,
    dataset_id: str,
    table_id: str,
    location: str,
    source_path: str,
    schema_path: str,
    *,
    bq_command: str = "bq",
) -> list[str]:
    """Load command.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        location: location (str) used by this operation.
        source_path: source path (str) used by this operation.
        schema_path: schema path (str) used by this operation.
        bq_command: bigQuery command (str) used by this operation.

    Returns:
        list[str] value produced by load command.
    """
    return [
        bq_command,
        "--project_id",
        project_id,
        "--location",
        location,
        "load",
        "--source_format=NEWLINE_DELIMITED_JSON",
        table_ref(project_id, dataset_id, table_id),
        source_path,
        schema_path,
    ]


def delete_table_command(
    project_id: str,
    dataset_id: str,
    table_id: str,
    *,
    bq_command: str = "bq",
) -> list[str]:
    """Delete table command.


    Args:
        project_id: project ID (str) used by this operation.
        dataset_id: dataset ID (str) used by this operation.
        table_id: table ID (str) used by this operation.
        bq_command: bigQuery command (str) used by this operation.

    Returns:
        list[str] value produced by delete table command.
    """
    return [
        bq_command,
        "--project_id",
        project_id,
        "rm",
        "-f",
        "-t",
        table_ref(project_id, dataset_id, table_id),
    ]


def parse_bq_json_array(payload: str, *, label: str = "bq query") -> list[dict[str, Any]]:
    """Parse bigQuery JSON array.


    Args:
        payload: payload (str) used by this operation.
        label: label (str) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by parse BigQuery JSON array.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        rows = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise BigQueryHelperError(f"{label} did not return valid JSON") from exc
    if not isinstance(rows, list):
        raise BigQueryHelperError(f"{label} did not return a row array")
    return [row for row in rows if isinstance(row, dict)]


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
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise BigQueryHelperError("bq command was not found in PATH") from exc
    return CommandResult(result.returncode, result.stdout, result.stderr)
