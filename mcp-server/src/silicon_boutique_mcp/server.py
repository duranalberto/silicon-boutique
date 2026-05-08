"""Discoverable entry point for the SiliconBoutique MCP boundary package."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from silicon_boutique_mcp.fixtures import (
    SummaryStoreFixtureAdapter,
    WorkflowTraceFixtureAdapter,
)
from silicon_boutique_mcp.models import (
    BoundaryCapability,
    BoundaryManifest,
    HistoricalMetricsQuery,
)
from silicon_boutique_mcp.tools import (
    ToolContractError,
    get_benchmark_status,
    query_historical_metrics,
    response_to_dict,
    tool_definitions_as_dicts,
)


BOUNDARY_VERSION = "p5.2"
PLANNED_CAPABILITIES = (
    BoundaryCapability(
        name="trigger_benchmark_run",
        description="Planned run-control capability behind a workflow adapter.",
    ),
    BoundaryCapability(
        name="get_benchmark_status",
        description="Contract-ready status lookup capability over trace metadata.",
        readiness="contract_ready",
    ),
    BoundaryCapability(
        name="query_historical_metrics",
        description="Contract-ready historical benchmark summary query capability.",
        readiness="contract_ready",
    ),
)


def build_boundary_manifest() -> BoundaryManifest:
    """Return the static P5.2 boundary manifest."""
    return BoundaryManifest(
        service_name="silicon-boutique-mcp",
        boundary_version=BOUNDARY_VERSION,
        capabilities=PLANNED_CAPABILITIES,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="silicon-boutique-mcp",
        description="Inspect the SiliconBoutique MCP boundary package.",
    )
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Print the boundary manifest as JSON.",
    )
    parser.add_argument(
        "--tools",
        action="store_true",
        help="Print exposed P5.2 tool contracts as JSON.",
    )
    subparsers = parser.add_subparsers(dest="command")

    status_parser = subparsers.add_parser(
        "status",
        help="Run get_benchmark_status against a local trace fixture.",
    )
    status_parser.add_argument("--run-id", required=True)
    status_parser.add_argument("--trace-fixture", type=Path, required=True)

    history_parser = subparsers.add_parser(
        "history",
        help="Run query_historical_metrics against a local summary store.",
    )
    history_parser.add_argument("--summary-store", type=Path, required=True)
    history_parser.add_argument("--machine-type")
    history_parser.add_argument("--processor-family")
    history_parser.add_argument("--architecture")
    history_parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.manifest:
            print(
                json.dumps(
                    build_boundary_manifest().to_dict(),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.tools:
            print(json.dumps(tool_definitions_as_dicts(), indent=2, sort_keys=True))
            return 0
        if args.command == "status":
            controller = WorkflowTraceFixtureAdapter(args.trace_fixture)
            response = get_benchmark_status(args.run_id, controller)
            print(json.dumps(response_to_dict(response), indent=2, sort_keys=True))
            return 0
        if args.command == "history":
            history_store = SummaryStoreFixtureAdapter(args.summary_store)
            query = HistoricalMetricsQuery(
                machine_type=args.machine_type,
                processor_family=args.processor_family,
                architecture=args.architecture,
                limit=args.limit,
            )
            response = query_historical_metrics(query, history_store)
            print(json.dumps(response_to_dict(response), indent=2, sort_keys=True))
            return 0
    except (OSError, ValueError, ToolContractError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0
