"""Structured report helpers for unified benchmark workflows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    """Compute uTC now.


    Returns:
        str value produced by uTC now.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def read_json(path: Path) -> Any:
    """Read jSON.


    Args:
        path: path (Path) used by this operation.

    Returns:
        Any value produced by read JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def read_env_status(path: Path) -> dict[str, str]:
    """Read environment status.


    Args:
        path: path (Path) used by this operation.

    Returns:
        dict[str, str] value produced by read environment status.
    """
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def teardown_status_from_artifacts(artifacts_dir: Path | None) -> dict[str, str] | None:
    """Compute teardown status from artifacts.


    Args:
        artifacts_dir: artifacts dir (Path | None) used by this operation.

    Returns:
        dict[str, str] | None value produced by teardown status from artifacts.
    """
    if artifacts_dir is None:
        return None
    status = read_env_status(artifacts_dir / "teardown-status.env")
    return status or None
