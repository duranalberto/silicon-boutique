#!/usr/bin/env python3
"""Command-line workflow for write workflow trace in the benchmark automation pipeline.


The module exposes a CLI entrypoint plus focused helper functions so tests can exercise the workflow without running external infrastructure.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared.automation import write_json


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments.


    Args:
        argv: argv (list[str] | None) used by this operation.

    Returns:
        argparse.Namespace value produced by parse arguments.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    parser = argparse.ArgumentParser(description="Write SiliconBoutique workflow trace JSON.")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the command-line entrypoint.


    Args:
        argv: argv (list[str] | None) used by this operation.

    Returns:
        Process exit code for the command.
    """
    args = parse_args(argv)
    trace_path = args.output or args.artifacts_dir / "workflow-trace.json"
    write_json(trace_path, build_trace(args.artifacts_dir, trace_path, os.environ))
    return 0


def build_trace(artifacts_dir: Path, trace_path: Path, env: dict[str, str]) -> dict[str, Any]:
    """Build trace.


    Args:
        artifacts_dir: artifacts dir (Path) used by this operation.
        trace_path: trace path (Path) used by this operation.
        env: environment (dict[str, str]) used by this operation.

    Returns:
        dict[str, Any] value produced by build trace.
    """
    summary_path = artifacts_dir / "benchmark-summary.json"
    summary_store_path = artifacts_dir / "benchmark-summaries.ndjson"
    loadgenerator_stats_path = artifacts_dir / "loadgenerator-stats.json"
    bigquery_load_report_path = artifacts_dir / "bigquery-load-report.json"
    acceptance_report_path = artifacts_dir / "acceptance-demo-report.json"
    cloud_provider = first_env(env, "TRACE_CLOUD_PROVIDER", "CLOUD_PROVIDER") or "gcp"
    project_id = env.get("PROJECT_ID", "")
    bigquery_dataset = env.get("BIGQUERY_DATASET", "")
    bigquery_table = env.get("BIGQUERY_TABLE", "")
    bigquery_summary_table = (
        first_env(env, "TRACE_BIGQUERY_SUMMARY_TABLE")
        or f"{project_id}.{bigquery_dataset}.{bigquery_table}"
    )

    return {
        "GitHub": {
            "workflow": env.get("GITHUB_WORKFLOW", ""),
            "run_id": env.get("GITHUB_RUN_ID", ""),
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
            "ref": env.get("GITHUB_REF", ""),
            "sha": env.get("GITHUB_SHA", ""),
        },
        "benchmark": {
            "run_id": env.get("RUN_ID", ""),
            "environment": first_env(env, "TRACE_ENVIRONMENT", "ENVIRONMENT") or cloud_provider,
            "cloud_provider": cloud_provider,
            "namespace": env.get("NAMESPACE", ""),
            "machine_type": env.get("MACHINE_TYPE", ""),
            "processor_family": env.get("PROCESSOR_FAMILY", ""),
            "cpu_platform": env.get("CPU_PLATFORM", "") or None,
            "architecture": env.get("ARCHITECTURE", ""),
            "region": env.get("REGION", ""),
            "zone": env.get("ZONE", ""),
            "node_count": env.get("NODE_COUNT", ""),
            "pricing_model": env.get("PRICING_MODEL", ""),
            "benchmark_start": first_env(env, "TRACE_BENCHMARK_START", "BENCHMARK_START"),
            "benchmark_end": first_env(env, "TRACE_BENCHMARK_END", "BENCHMARK_END"),
            "load_concurrent_users": env.get("CONCURRENT_USERS", ""),
            "load_users_per_second": env.get("USERS_PER_SECOND", ""),
            "load_profile_source": env.get("LOAD_PROFILE_SOURCE", "manual"),
        },
        "gcp": {
            "project_id": project_id,
            "region": env.get("REGION", ""),
            "zone": env.get("ZONE", ""),
        },
        "bigquery": {
            "dataset": bigquery_dataset,
            "table": bigquery_table,
            "location": env.get("BIGQUERY_LOCATION", ""),
            "summary_table": bigquery_summary_table,
            "load_report_path": str(bigquery_load_report_path),
            "load_report_exists": str(bigquery_load_report_path.exists()).lower(),
        },
        "artifacts": {
            "artifact_name": env.get("SUMMARY_ARTIFACT_NAME", ""),
            "summary_path": str(summary_path),
            "summary_store_path": str(summary_store_path),
            "loadgenerator_stats_path": str(loadgenerator_stats_path),
            "bigquery_load_report_path": str(bigquery_load_report_path),
            "acceptance_report_path": str(acceptance_report_path),
            "trace_path": str(trace_path),
            "summary_exists": str(summary_path.exists()).lower(),
            "summary_store_exists": str(summary_store_path.exists()).lower(),
            "loadgenerator_stats_exists": str(loadgenerator_stats_path.exists()).lower(),
            "bigquery_load_report_exists": str(bigquery_load_report_path.exists()).lower(),
            "acceptance_report_exists": str(acceptance_report_path.exists()).lower(),
        },
        "teardown": {
            "destroy_attempted": first_env(env, "TRACE_DESTROY_ATTEMPTED") or "pending",
            "destroy_succeeded": first_env(env, "TRACE_DESTROY_SUCCEEDED") or "pending",
        },
        "inputs": {
            "failure_stage": env.get("FAILURE_STAGE", ""),
            "acceptance_demo": env.get("ACCEPTANCE_DEMO", ""),
        },
    }


def first_env(env: dict[str, str], *names: str) -> str:
    """Compute first environment.


    Args:
        env: environment (dict[str, str]) used by this operation.
        names: names (str) used by this operation.

    Returns:
        str value produced by first environment.
    """
    for name in names:
        value = env.get(name, "")
        if value:
            return value
    return ""


if __name__ == "__main__":
    raise SystemExit(main())

