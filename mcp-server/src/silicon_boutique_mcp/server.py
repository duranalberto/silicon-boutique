"""Discoverable entry point for the SiliconBoutique MCP boundary package."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from silicon_boutique_mcp.bigquery_history import BigQueryHistoryStore
from silicon_boutique_mcp.fixtures import (
    SummaryStoreFixtureAdapter,
    WorkflowTraceFixtureAdapter,
)
from silicon_boutique_mcp.github_actions import GitHubActionsBenchmarkRunController
from silicon_boutique_mcp.models import (
    BenchmarkRunRequest,
    BoundaryCapability,
    BoundaryManifest,
    HistoricalMetricsQuery,
)
from silicon_boutique_mcp.tools import (
    ToolContractError,
    get_benchmark_status,
    query_historical_metrics,
    response_to_dict,
    trigger_benchmark_run,
    tool_definitions_as_dicts,
)


BOUNDARY_VERSION = "p9.4"
PLANNED_CAPABILITIES = (
    BoundaryCapability(
        name="trigger_benchmark_run",
        description="Production GitHub Actions workflow dispatch capability.",
        readiness="production_adapter_ready",
    ),
    BoundaryCapability(
        name="get_benchmark_status",
        description="Production GitHub Actions status lookup capability.",
        readiness="production_adapter_ready",
    ),
    BoundaryCapability(
        name="query_historical_metrics",
        description="Production BigQuery historical benchmark query capability.",
        readiness="production_adapter_ready",
    ),
)


def build_boundary_manifest() -> BoundaryManifest:
    """Return the static boundary manifest."""
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
        help="Print exposed tool contracts as JSON.",
    )
    subparsers = parser.add_subparsers(dest="command")

    status_parser = subparsers.add_parser(
        "status",
        help="Run get_benchmark_status against GitHub Actions or a local trace fixture.",
    )
    status_parser.add_argument("--run-id", required=True)
    status_parser.add_argument("--trace-fixture", type=Path)

    history_parser = subparsers.add_parser(
        "history",
        help="Run query_historical_metrics against BigQuery or a local summary store.",
    )
    history_parser.add_argument("--summary-store", type=Path)
    history_parser.add_argument("--machine-type")
    history_parser.add_argument("--processor-family")
    history_parser.add_argument("--architecture")
    history_parser.add_argument("--limit", type=int, default=10)

    trigger_parser = subparsers.add_parser(
        "trigger",
        help="Dispatch the production benchmark workflow through GitHub Actions.",
    )
    trigger_parser.add_argument("--request-json", type=Path, required=True)
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
            if args.trace_fixture is not None:
                controller = WorkflowTraceFixtureAdapter(args.trace_fixture)
            else:
                controller = GitHubActionsBenchmarkRunController.from_env()
            response = get_benchmark_status(args.run_id, controller)
            print(json.dumps(response_to_dict(response), indent=2, sort_keys=True))
            return 0
        if args.command == "history":
            if args.summary_store is not None:
                history_store = SummaryStoreFixtureAdapter(args.summary_store)
            else:
                history_store = BigQueryHistoryStore.from_env()
            query = HistoricalMetricsQuery(
                machine_type=args.machine_type,
                processor_family=args.processor_family,
                architecture=args.architecture,
                limit=args.limit,
            )
            response = query_historical_metrics(query, history_store)
            print(json.dumps(response_to_dict(response), indent=2, sort_keys=True))
            return 0
        if args.command == "trigger":
            request = benchmark_request_from_json(args.request_json)
            controller = GitHubActionsBenchmarkRunController.from_env()
            identity = trigger_benchmark_run(request, controller)
            print(json.dumps(response_to_dict(identity), indent=2, sort_keys=True))
            return 0
    except (OSError, ValueError, ToolContractError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def benchmark_request_from_json(path: Path) -> BenchmarkRunRequest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ToolContractError("trigger request JSON must be an object")
    try:
        return BenchmarkRunRequest(
            cloud_provider=payload["cloud_provider"],
            project_id=payload["project_id"],
            region=payload["region"],
            zone=payload["zone"],
            machine_type=payload["machine_type"],
            node_count=payload["node_count"],
            processor_family=payload["processor_family"],
            architecture=payload["architecture"],
            concurrent_users=payload["concurrent_users"],
            users_per_second=payload["users_per_second"],
            test_duration=payload["test_duration"],
            pricing_model=payload.get("pricing_model", "spot"),
            cpu_platform=payload.get("cpu_platform"),
        )
    except KeyError as exc:
        raise ToolContractError(f"missing trigger request field: {exc.args[0]}") from exc
