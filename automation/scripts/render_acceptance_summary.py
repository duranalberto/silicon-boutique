#!/usr/bin/env python3
"""Render the acceptance demo Markdown step summary."""

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
    parser = argparse.ArgumentParser(description="Render acceptance demo summary Markdown.")
    parser.add_argument("--report", type=Path, default=Path("artifacts/acceptance-demo-report.json"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(render_summary(read_json(args.report)))
    return 0


def render_summary(report: dict) -> str:
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
