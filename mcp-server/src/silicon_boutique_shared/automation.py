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
    returncode: int
    stdout: str = ""
    stderr: str = ""


def run_command(command: list[str], *, cwd: Path | None = None) -> CommandResult:
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
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_ndjson(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def parse_duration_seconds(value: str, *, allow_milliseconds: bool = False) -> int:
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
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_offset(*, seconds: int) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(seconds=seconds))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def append_log(
    path: Path, command: Iterable[str], stdout: str, stderr: str, returncode: int
) -> None:
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
    output = (result.stderr or result.stdout).strip()
    if not output:
        return ""
    output = re.sub(r"\s+", " ", output)
    if len(output) > max_length:
        return output[: max_length - 3] + "..."
    return output


def bool_string(value: bool) -> str:
    return "true" if value else "false"


def shell_join(command: Iterable[str]) -> str:
    return " ".join(shell_quote(str(part)) for part in command)


def shell_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"

