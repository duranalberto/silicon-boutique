"""Small stdlib-only helpers shared by repository automation scripts."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class CommandResult:
    """Container for command Result state and behavior.


    Attributes:
        returncode: returncode (int) stored on the object.
        stdout: standard output (str) stored on the object.
        stderr: standard error (str) stored on the object.
    """
    returncode: int
    stdout: str = ""
    stderr: str = ""


def run_command(command: list[str], *, cwd: Path | None = None) -> CommandResult:
    """Run command.


    Args:
        command: command (list[str]) used by this operation.
        cwd: cwd (Path | None) used by this operation.

    Returns:
        CommandResult value produced by run command.
    """
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return CommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def read_json(path: Path) -> Any:
    """Read jSON.


    Args:
        path: path (Path) used by this operation.

    Returns:
        Any value produced by read JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    """Write jSON.


    Args:
        path: path (Path) used by this operation.
        payload: payload (Any) used by this operation.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    """Read nDJSON.


    Args:
        path: path (Path) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by read NDJSON.
    """
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_ndjson(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Write nDJSON.


    Args:
        path: path (Path) used by this operation.
        rows: rows (Iterable[dict[str, Any]]) used by this operation.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def resolve_path(repo_root: Path, path: Path) -> Path:
    """Compute resolve path.


    Args:
        repo_root: repo root (Path) used by this operation.
        path: path (Path) used by this operation.

    Returns:
        Path value produced by resolve path.
    """
    return path if path.is_absolute() else repo_root / path


def parse_duration_seconds(value: str, *, allow_milliseconds: bool = False) -> int:
    """Parse duration seconds.


    Args:
        value: value (str) used by this operation.
        allow_milliseconds: allow milliseconds (bool) used by this operation.

    Returns:
        int value produced by parse duration seconds.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    units = "ms|s|m|h" if allow_milliseconds else "s|m|h"
    match = re.fullmatch(rf"([1-9][0-9]*)(?:({units}))?", value)
    if not match:
        suffix = "seconds, Ns, Nm, or Nh"
        if allow_milliseconds:
            suffix = "milliseconds, seconds, minutes, or hours"
        raise ValueError(f"duration must be a positive number of {suffix}")
    amount = int(match.group(1))
    unit = match.group(2) or "s"
    multipliers = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    seconds = amount * multipliers[unit]
    if seconds < 1:
        raise ValueError("duration must be at least 1 second")
    return int(seconds)


def utc_now() -> str:
    """Compute uTC now.


    Returns:
        str value produced by uTC now.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_offset(*, seconds: int) -> str:
    """Compute uTC offset.


    Args:
        seconds: seconds (int) used by this operation.

    Returns:
        str value produced by uTC offset.
    """
    return (
        (datetime.now(timezone.utc) + timedelta(seconds=seconds))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def first_env(values: dict[str, str], *names: str) -> str:
    """Compute first environment.


    Args:
        values: values (dict[str, str]) used by this operation.
        names: names (str) used by this operation.

    Returns:
        str value produced by first environment.
    """
    for name in names:
        value = values.get(name, "").strip()
        if value:
            return value
    return ""


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Write environment file.


    Args:
        path: path (Path) used by this operation.
        values: values (dict[str, str]) used by this operation.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def append_text(path: Path, text: str) -> None:
    """Append text.


    Args:
        path: path (Path) used by this operation.
        text: text (str) used by this operation.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def append_log(
    path: Path, command: Iterable[str], stdout: str, stderr: str, returncode: int
) -> None:
    """Append log.


    Args:
        path: path (Path) used by this operation.
        command: command (Iterable[str]) used by this operation.
        stdout: standard output (str) used by this operation.
        stderr: standard error (str) used by this operation.
        returncode: returncode (int) used by this operation.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {shell_join(command)}\n")
        if stdout:
            handle.write(stdout)
            if not stdout.endswith("\n"):
                handle.write("\n")
        if stderr:
            handle.write(stderr)
            if not stderr.endswith("\n"):
                handle.write("\n")
        handle.write(f"exit_code={returncode}\n\n")


def summarize_command_failure(result: CommandResult, *, max_length: int = 500) -> str:
    """Compute summarize command failure.


    Args:
        result: result (CommandResult) used by this operation.
        max_length: max length (int) used by this operation.

    Returns:
        str value produced by summarize command failure.
    """
    output = (result.stderr or result.stdout).strip()
    if not output:
        return ""
    output = re.sub(r"\s+", " ", output)
    if len(output) > max_length:
        return output[: max_length - 3] + "..."
    return output


def bool_string(value: bool) -> str:
    """Compute boolean string.


    Args:
        value: value (bool) used by this operation.

    Returns:
        str value produced by boolean string.
    """
    return "true" if value else "false"


def shell_join(command: Iterable[str]) -> str:
    """Compute shell join.


    Args:
        command: command (Iterable[str]) used by this operation.

    Returns:
        str value produced by shell join.
    """
    return " ".join(shell_quote(str(part)) for part in command)


def shell_quote(value: str) -> str:
    """Compute shell quote.


    Args:
        value: value (str) used by this operation.

    Returns:
        str value produced by shell quote.
    """
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"
