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
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]


def validate_destination(project_id: str, dataset_id: str, table_id: str, location: str) -> None:
    if not PROJECT_RE.match(project_id):
        raise BigQueryHelperError(f"invalid GCP project_id: {project_id}")
    for label, value in (("dataset_id", dataset_id), ("table_id", table_id)):
        if not IDENTIFIER_RE.match(value):
            raise BigQueryHelperError(f"invalid BigQuery {label}: {value}")
    if not LOCATION_RE.match(location):
        raise BigQueryHelperError(f"invalid BigQuery location: {location}")


def table_ref(project_id: str, dataset_id: str, table_id: str) -> str:
    return f"{project_id}:{dataset_id}.{table_id}"


def table_sql_name(project_id: str, dataset_id: str, table_id: str) -> str:
    return f"{project_id}.{dataset_id}.{table_id}"


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def parse_bq_json_array(payload: str, *, label: str = "bq query") -> list[dict[str, Any]]:
    try:
        rows = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise BigQueryHelperError(f"{label} did not return valid JSON") from exc
    if not isinstance(rows, list):
        raise BigQueryHelperError(f"{label} did not return a row array")
    return [row for row in rows if isinstance(row, dict)]


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
        raise BigQueryHelperError("bq command was not found in PATH") from exc
    return CommandResult(result.returncode, result.stdout, result.stderr)
