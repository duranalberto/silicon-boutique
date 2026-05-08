#!/usr/bin/env python3
"""Extract aggregate Locust request stats from Online Boutique loadgenerator logs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


AGGREGATED_RE = re.compile(
    r"^\s*Aggregated\s+(?P<requests>\d+)\s+"
    r"(?P<failures>\d+)(?:\([^)]*\))?\s+\|.*\|\s+"
    r"(?P<rps>[0-9]+(?:\.[0-9]+)?)\s+"
    r"(?P<failures_per_second>[0-9]+(?:\.[0-9]+)?)\s*$"
)


class LoadgeneratorStatsError(RuntimeError):
    """Raised when loadgenerator stats cannot be extracted."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse aggregate Locust stats from loadgenerator logs."
    )
    parser.add_argument("--logs-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if aggregate request stats cannot be parsed.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        logs = args.logs_input.read_text(encoding="utf-8")
        stats = parse_locust_stats(logs, run_id=args.run_id)
        write_json(args.output, stats)
    except (OSError, LoadgeneratorStatsError) as exc:
        failure = {
            "run_id": args.run_id,
            "request_count_total": None,
            "request_success_count": None,
            "request_failure_count": None,
            "avg_requests_per_second": None,
            "parse_status": "failed",
            "error": str(exc),
        }
        write_json(args.output, failure)
        if args.strict:
            print(str(exc), file=sys.stderr)
            return 2
    return 0


def parse_locust_stats(logs: str, *, run_id: str) -> dict[str, Any]:
    matches = [match for line in logs.splitlines() if (match := AGGREGATED_RE.match(line))]
    if not matches:
        raise LoadgeneratorStatsError("loadgenerator logs do not contain an Aggregated Locust stats row")

    match = matches[-1]
    total = int(match.group("requests"))
    failures = int(match.group("failures"))
    if failures > total:
        raise LoadgeneratorStatsError("Locust failure count exceeds total request count")

    return {
        "run_id": run_id,
        "request_count_total": total,
        "request_success_count": total - failures,
        "request_failure_count": failures,
        "avg_requests_per_second": round(float(match.group("rps")), 6),
        "avg_failures_per_second": round(float(match.group("failures_per_second")), 6),
        "parse_status": "parsed",
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
