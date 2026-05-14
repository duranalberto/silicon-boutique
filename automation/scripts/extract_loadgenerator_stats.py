#!/usr/bin/env python3
"""Extract aggregate Locust request stats from Online Boutique loadgenerator logs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared.automation import write_json


AGGREGATED_RE = re.compile(
    r"^\s*Aggregated\s+(?P<requests>\d+)\s+"
    r"(?P<failures>\d+)(?:\([^)]*\))?\s+\|.*\|\s+"
    r"(?P<rps>[0-9]+(?:\.[0-9]+)?)\s+"
    r"(?P<failures_per_second>[0-9]+(?:\.[0-9]+)?)\s*$"
)


class LoadgeneratorStatsError(RuntimeError):
    """Raised when loadgenerator stats cannot be extracted."""


def parse_args() -> argparse.Namespace:
    """Parse arguments.


    Returns:
        argparse.Namespace value produced by parse arguments.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    parser = argparse.ArgumentParser(
        description="Parse aggregate Locust stats from loadgenerator logs."
    )
    parser.add_argument("--logs-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--duration-seconds",
        type=int,
        help="Benchmark window duration used to validate request totals against reported RPS.",
    )
    parser.add_argument(
        "--min-request-rps-window-ratio",
        type=float,
        default=0.5,
        help="Minimum request_count_total / (avg_requests_per_second * duration_seconds).",
    )
    parser.add_argument(
        "--log-source",
        choices=("current", "previous"),
        default="current",
        help="Whether logs came from the current container or a previous terminated container.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if aggregate request stats cannot be parsed.",
    )
    args = parser.parse_args()
    if args.duration_seconds is not None and args.duration_seconds < 1:
        parser.error("--duration-seconds must be at least 1")
    if not 0 <= args.min_request_rps_window_ratio <= 1:
        parser.error("--min-request-rps-window-ratio must be between 0 and 1")
    return args


def main() -> int:
    """Run the command-line entrypoint.


    Returns:
        Process exit code for the command.
    """
    args = parse_args()
    try:
        logs = args.logs_input.read_text(encoding="utf-8")
        stats = parse_locust_stats(
            logs,
            run_id=args.run_id,
            duration_seconds=args.duration_seconds,
            min_request_rps_window_ratio=args.min_request_rps_window_ratio,
            log_source=args.log_source,
        )
        write_json(args.output, stats)
    except (OSError, LoadgeneratorStatsError) as exc:
        failure = {
            "run_id": args.run_id,
            "request_count_total": None,
            "request_success_count": None,
            "request_failure_count": None,
            "avg_requests_per_second": None,
            "avg_failures_per_second": None,
            "log_source": args.log_source,
            "aggregated_row_count": 0,
            "request_rps_window_ratio": None,
            "parse_status": "failed",
            "error": str(exc),
        }
        write_json(args.output, failure)
        if args.strict:
            print(str(exc), file=sys.stderr)
            return 2
    return 0


def parse_locust_stats(
    logs: str,
    *,
    run_id: str,
    duration_seconds: int | None = None,
    min_request_rps_window_ratio: float = 0.5,
    log_source: str = "current",
) -> dict[str, Any]:
    """Parse locust stats.


    Args:
        logs: logs (str) used by this operation.
        run_id: run ID (str) used by this operation.

    Returns:
        dict[str, Any] value produced by parse Locust stats.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    matches = [match for line in logs.splitlines() if (match := AGGREGATED_RE.match(line))]
    if not matches:
        raise LoadgeneratorStatsError("loadgenerator logs do not contain an Aggregated Locust stats row")

    match = matches[-1]
    total = int(match.group("requests"))
    failures = int(match.group("failures"))
    if failures > total:
        raise LoadgeneratorStatsError("Locust failure count exceeds total request count")

    rps = round(float(match.group("rps")), 6)
    ratio = request_rps_window_ratio(
        request_count_total=total,
        avg_requests_per_second=rps,
        duration_seconds=duration_seconds,
    )
    if ratio is not None and ratio < min_request_rps_window_ratio:
        raise LoadgeneratorStatsError(
            "Locust request total is too low for the benchmark window: "
            f"ratio {ratio:g} < {min_request_rps_window_ratio:g}"
        )

    return {
        "run_id": run_id,
        "request_count_total": total,
        "request_success_count": total - failures,
        "request_failure_count": failures,
        "avg_requests_per_second": rps,
        "avg_failures_per_second": round(float(match.group("failures_per_second")), 6),
        "log_source": log_source,
        "aggregated_row_count": len(matches),
        "request_rps_window_ratio": ratio,
        "parse_status": "parsed",
    }


def request_rps_window_ratio(
    *,
    request_count_total: int,
    avg_requests_per_second: float,
    duration_seconds: int | None,
) -> float | None:
    """Compute request total to reported RPS window ratio."""
    if duration_seconds is None or avg_requests_per_second <= 0:
        return None
    return round(request_count_total / (avg_requests_per_second * duration_seconds), 6)


if __name__ == "__main__":
    raise SystemExit(main())
