#!/usr/bin/env python3
"""Command-line workflow for render acceptance summary in the benchmark automation pipeline.


The module exposes a CLI entrypoint plus focused helper functions so tests can exercise the workflow without running external infrastructure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared.automation import read_json


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments.


    Args:
        argv: argv (list[str] | None) used by this operation.

    Returns:
        argparse.Namespace value produced by parse arguments.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    parser = argparse.ArgumentParser(description="Render acceptance demo summary Markdown.")
    parser.add_argument("--report", type=Path, default=Path("artifacts/acceptance-demo-report.json"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the command-line entrypoint.


    Args:
        argv: argv (list[str] | None) used by this operation.

    Returns:
        Process exit code for the command.
    """
    args = parse_args(argv)
    print(render_summary(read_json(args.report)))
    return 0


def render_summary(report: dict) -> str:
    """Render summary.


    Args:
        report: report (dict) used by this operation.

    Returns:
        str value produced by render summary.
    """
    dashboard = report["checks"]["dashboard"]
    bigquery = report["checks"]["bigquery"]
    rows = [
        "### Acceptance Demo",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| status | `{report['status']}` |",
        f"| run_id | `{report['run_id']}` |",
        f"| artifact | `{report['artifacts_dir']}` |",
        f"| bigquery_summary_table | `{bigquery.get('summary_table', '')}` |",
        f"| dashboard_uid | `{dashboard.get('dashboard_uid', '')}` |",
        f"| dashboard_title | `{dashboard.get('dashboard_title', '')}` |",
        "| dashboard_location | `service/sb-monitoring-grafana, dashboard uid silicon-boutique-online-boutique` |",
    ]
    return "\n".join(rows)


if __name__ == "__main__":
    raise SystemExit(main())
