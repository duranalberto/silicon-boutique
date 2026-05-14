"""Command execution and redaction helpers for automation workflows."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


PREVIEW_LIMIT = 800


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


class Runner(Protocol):
    """Container for runner state and behavior.
    """
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """Run the configured operation.


        Args:
            command: command (list[str]) used by this operation.
            cwd: cwd (Path | None) used by this operation.
            env: environment (dict[str, str] | None) used by this operation.

        Returns:
            CommandResult value produced by run.
        """


class SubprocessRunner:
    """Container for subprocess Runner state and behavior.
    """
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """Run the configured operation.


        Args:
            command: command (list[str]) used by this operation.
            cwd: cwd (Path | None) used by this operation.
            env: environment (dict[str, str] | None) used by this operation.

        Returns:
            CommandResult value produced by run.
        """
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return CommandResult(127, "", str(exc))
        return CommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def shell_join(command: list[str]) -> str:
    """Compute shell join.


    Args:
        command: command (list[str]) used by this operation.

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


def redact_text(value: str) -> str:
    """Compute redact text.


    Args:
        value: value (str) used by this operation.

    Returns:
        str value produced by redact text.
    """
    redacted = value or ""
    patterns = [
        (r"(?i)(authorization:\s*)(bearer|basic)\s+\S+", r"\1<redacted>"),
        (r"(?i)((?:token|secret|password|credential|key)[A-Za-z0-9_ -]*[=:]\s*)\S+", r"\1<redacted>"),
        (r"gha-creds-[A-Za-z0-9._-]+\.json", "gha-creds-<redacted>.json"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def preview_text(value: str, *, max_length: int = PREVIEW_LIMIT) -> str:
    """Compute preview text.


    Args:
        value: value (str) used by this operation.
        max_length: max length (int) used by this operation.

    Returns:
        str value produced by preview text.
    """
    text = redact_text(value).strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 14] + "...<truncated>"


def command_for_report(command: list[str]) -> list[str]:
    """Compute command for report.


    Args:
        command: command (list[str]) used by this operation.

    Returns:
        list[str] value produced by command for report.
    """
    return [redact_text(str(part)) for part in command]
