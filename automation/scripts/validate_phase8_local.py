#!/usr/bin/env python3
"""Run local-only Phase 8 validation without cloud credentials."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import generate_comparison_report
import validate_benchmark_comparability as comparability


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = Path("automation/templates/benchmark-summary.schema.json")
DEFAULT_SUMMARY_STORE = Path("artifacts/benchmark-summaries.ndjson")
DEFAULT_ARTIFACTS_DIR = Path("artifacts/phase8-local-validation")
MIN_DURATION_SECONDS = 1200
MIN_COVERAGE_RATIO = 0.95


class Phase8LocalValidationError(RuntimeError):
    """Raised when local Phase 8 validation cannot complete."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ValidationConfig:
    summary_store: Path
    artifacts_dir: Path
    schema: Path
    repo_root: Path
    min_duration_seconds: int = MIN_DURATION_SECONDS
    min_coverage_ratio: float = MIN_COVERAGE_RATIO


Runner = Callable[[list[str], Path], CommandResult]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Phase 8 locally with deterministic comparison evidence."
    )
    parser.add_argument("--summary-store", type=Path, default=DEFAULT_SUMMARY_STORE)
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--min-duration-seconds", type=int, default=MIN_DURATION_SECONDS)
    parser.add_argument("--min-coverage-ratio", type=float, default=MIN_COVERAGE_RATIO)
    args = parser.parse_args(argv)
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if not 0 <= args.min_coverage_ratio <= 1:
        parser.error("--min-coverage-ratio must be between 0 and 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = ValidationConfig(
        summary_store=args.summary_store,
        artifacts_dir=args.artifacts_dir,
        schema=args.schema,
        repo_root=REPO_ROOT,
        min_duration_seconds=args.min_duration_seconds,
        min_coverage_ratio=args.min_coverage_ratio,
    )
    try:
        report = run_validation(config)
    except Phase8LocalValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(report["summary_source_reason"])
    print(
        "Phase 8 local validation {status}; source={source}; "
        "comparability={comparability}; comparison={comparison}".format(
            status=report["status"],
            source=report["summary_source"],
            comparability=report["comparability_status"],
            comparison=report["comparison_status"],
        )
    )
    return 0 if report["status"] == "pass" else 2


def run_validation(
    config: ValidationConfig,
    *,
    runner: Runner = None,
) -> dict[str, Any]:
    runner = runner or run_command
    config.artifacts_dir.mkdir(parents=True, exist_ok=True)
    check_results = run_static_checks(config, runner)
    schema = comparability.load_json(resolve_path(config.repo_root, config.schema), "schema")
    selected = select_validation_rows(config, schema)

    valid_store = config.artifacts_dir / "benchmark-summaries-valid.ndjson"
    mixed_store = config.artifacts_dir / "benchmark-summaries-mixed.ndjson"
    comparability_report_path = config.artifacts_dir / "comparability-report.json"
    comparison_report_path = config.artifacts_dir / "comparison-report.json"
    markdown_report_path = config.artifacts_dir / "comparison-report.md"

    write_ndjson(valid_store, selected.valid_rows)
    mixed_rows = selected.valid_rows + [partial_fixture_row()]
    write_ndjson(mixed_store, mixed_rows)

    comparability_report = comparability.build_report(
        summary_store=valid_store,
        schema_path=config.schema,
        schema=schema,
        rows=selected.valid_rows,
        source_total_rows=len(selected.valid_rows),
        selected_run_id=None,
        mode="comparability",
        min_duration_seconds=config.min_duration_seconds,
        min_coverage_ratio=config.min_coverage_ratio,
    )
    comparability.write_json(comparability_report_path, comparability_report)

    comparison_report = generate_comparison_report.build_comparison_report(
        rows=mixed_rows,
        source={"type": "ndjson", "summary_store": str(mixed_store)},
        schema=schema,
        schema_path=config.schema,
        min_duration_seconds=config.min_duration_seconds,
        min_coverage_ratio=config.min_coverage_ratio,
    )
    generate_comparison_report.write_json(comparison_report_path, comparison_report)
    generate_comparison_report.write_text(
        markdown_report_path,
        generate_comparison_report.render_markdown(comparison_report),
    )

    status = overall_status(comparability_report, comparison_report)
    report = {
        "status": status,
        "generated_at": utc_now(),
        "summary_source": selected.source,
        "summary_source_reason": selected.reason,
        "summary_store": str(config.summary_store),
        "artifacts_dir": str(config.artifacts_dir),
        "valid_summary_store": str(valid_store),
        "mixed_summary_store": str(mixed_store),
        "comparability_report": str(comparability_report_path),
        "comparison_report": str(comparison_report_path),
        "markdown_report": str(markdown_report_path),
        "comparability_status": comparability_report["comparability_status"],
        "comparison_status": comparison_report["status"],
        "comparable_run_ids": comparability_report["comparable_run_ids"],
        "comparison_group_count": comparison_report["comparison_group_count"],
        "rejected_runs": comparison_report["rejected_runs"],
        "checks": check_results,
    }
    generate_comparison_report.write_json(
        config.artifacts_dir / "phase8-local-validation-report.json", report
    )
    return report


def run_static_checks(config: ValidationConfig, runner: Runner) -> list[dict[str, Any]]:
    aws_root = config.repo_root / "infra" / "terraform" / "aws-eks"
    checks = [
        ([sys.executable, "-m", "unittest", "discover", "-s", "automation/tests"], config.repo_root),
        (
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "mcp-server/tests",
            ],
            config.repo_root,
        ),
        (["terraform", "fmt", "-check", "-recursive", "infra/terraform"], config.repo_root),
        (["terraform", "init", "-backend=false", "-input=false"], aws_root),
        (["terraform", "validate"], aws_root),
        (["terraform", "plan", "-refresh=false", "-input=false"], aws_root),
    ]
    results: list[dict[str, Any]] = []
    for command, cwd in checks:
        environment = None
        if command[:4] == [sys.executable, "-m", "unittest", "discover"]:
            environment = "mcp" if "mcp-server/tests" in command else "automation"
        result = runner(command, cwd)
        results.append(
            {
                "command": command,
                "cwd": str(cwd),
                "returncode": result.returncode,
                "environment": environment,
            }
        )
        if result.returncode != 0:
            raise Phase8LocalValidationError(
                "Phase 8 local validation command failed: "
                + " ".join(command)
                + "\n"
                + (result.stderr or result.stdout)
            )
    return results


@dataclass(frozen=True)
class SelectedRows:
    source: str
    reason: str
    valid_rows: list[dict[str, Any]]


def select_validation_rows(config: ValidationConfig, schema: dict[str, Any]) -> SelectedRows:
    diagnostic_path = config.artifacts_dir.parent / "phase8-existing-comparability-check.json"
    existing_path = resolve_path(config.repo_root, config.summary_store)
    schema_fields = comparability.schema_field_set(schema)
    if existing_path.exists():
        rows = comparability.read_summary_store(existing_path)
        diagnostic = comparability.build_report(
            summary_store=config.summary_store,
            schema_path=config.schema,
            schema=schema,
            rows=rows,
            source_total_rows=len(rows),
            selected_run_id=None,
            mode="comparability",
            min_duration_seconds=config.min_duration_seconds,
            min_coverage_ratio=config.min_coverage_ratio,
        )
        comparability.write_json(diagnostic_path, diagnostic)
        accepted = accepted_rows(
            rows,
            schema_fields=schema_fields,
            min_duration_seconds=config.min_duration_seconds,
            min_coverage_ratio=config.min_coverage_ratio,
        )
        if len(accepted) >= 2:
            return SelectedRows(
                source="existing",
                reason=(
                    f"Using {len(accepted)} comparable rows from {config.summary_store}; "
                    "mixed report adds one intentional partial row for rejection evidence."
                ),
                valid_rows=accepted,
            )
        return SelectedRows(
            source="fixture",
            reason=(
                f"Bypassing {config.summary_store}: found {len(accepted)} comparable "
                "P8.1 rows; generated deterministic Phase 8 fixtures instead."
            ),
            valid_rows=comparable_fixture_rows(),
        )
    return SelectedRows(
        source="fixture",
        reason=(
            f"Bypassing {config.summary_store}: file does not exist; generated "
            "deterministic Phase 8 fixtures instead."
        ),
        valid_rows=comparable_fixture_rows(),
    )


def accepted_rows(
    rows: list[dict[str, Any]],
    *,
    schema_fields: set[str],
    min_duration_seconds: int,
    min_coverage_ratio: float,
) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        reasons = comparability.rejection_reasons(
            row=row,
            row_index=index,
            schema_fields=schema_fields,
            min_duration_seconds=min_duration_seconds,
            min_coverage_ratio=min_coverage_ratio,
        )
        if not reasons:
            accepted.append(row)
    field_sets = [
        sorted(field for field in row if field not in comparability.NULLABLE_COMPARABILITY_FIELDS)
        for row in accepted
    ]
    if field_sets and any(field_set != field_sets[0] for field_set in field_sets):
        return []
    return accepted


def comparable_fixture_rows() -> list[dict[str, Any]]:
    return [
        fixture_row(
            "phase8-local-fast-001",
            machine_type="local-fast",
            processor_family="local-x86",
            avg_cpu_usage_cores=1.8,
            max_cpu_usage_cores=2.4,
            memory_gb=2.6,
            latency_p50=72.0,
            latency_p95=165.0,
            latency_p99=230.0,
            latency_max=420.0,
            request_total=180000,
            avg_rps=100.0,
            failures=3,
            coverage=0.99,
            benchmark_start="2026-05-09T00:00:00Z",
            benchmark_end="2026-05-09T00:30:00Z",
        ),
        fixture_row(
            "phase8-local-fast-002",
            machine_type="local-fast",
            processor_family="local-x86",
            avg_cpu_usage_cores=1.7,
            max_cpu_usage_cores=2.3,
            memory_gb=2.4,
            latency_p50=70.0,
            latency_p95=158.0,
            latency_p99=220.0,
            latency_max=400.0,
            request_total=183600,
            avg_rps=102.0,
            failures=2,
            coverage=0.985,
            benchmark_start="2026-05-09T01:00:00Z",
            benchmark_end="2026-05-09T01:30:00Z",
        ),
        fixture_row(
            "phase8-local-efficient-001",
            machine_type="local-efficient",
            processor_family="local-arm64",
            architecture="arm64",
            avg_cpu_usage_cores=1.1,
            max_cpu_usage_cores=1.5,
            memory_gb=1.8,
            latency_p50=82.0,
            latency_p95=188.0,
            latency_p99=260.0,
            latency_max=470.0,
            request_total=153000,
            avg_rps=85.0,
            failures=2,
            coverage=0.98,
            benchmark_start="2026-05-09T00:00:00Z",
            benchmark_end="2026-05-09T00:30:00Z",
        ),
    ]


def partial_fixture_row() -> dict[str, Any]:
    row = fixture_row(
        "phase8-local-partial-001",
        machine_type="local-partial",
        processor_family="local-x86",
        avg_cpu_usage_cores=0.9,
        max_cpu_usage_cores=1.0,
        memory_gb=1.3,
        latency_p50=95.0,
        latency_p95=210.0,
        latency_p99=310.0,
        latency_max=600.0,
        request_total=6000,
        avg_rps=100.0,
        failures=25,
        coverage=0.97,
        benchmark_start="2026-05-09T02:00:00Z",
        benchmark_end="2026-05-09T02:01:00Z",
        duration_seconds=60,
    )
    row["summary_status"] = "partial"
    return row


def fixture_row(
    run_id: str,
    *,
    machine_type: str,
    processor_family: str,
    architecture: str = "amd64",
    avg_cpu_usage_cores: float,
    max_cpu_usage_cores: float,
    memory_gb: float,
    latency_p50: float,
    latency_p95: float,
    latency_p99: float,
    latency_max: float,
    request_total: int,
    avg_rps: float,
    failures: int,
    coverage: float,
    benchmark_start: str,
    benchmark_end: str,
    duration_seconds: int = 1800,
) -> dict[str, Any]:
    success = request_total - failures
    return {
        "architecture": architecture,
        "avg_cpu_throttling_ratio": 0.01,
        "avg_cpu_usage_cores": avg_cpu_usage_cores,
        "avg_cpu_utilization_pct": round(avg_cpu_usage_cores / 4 * 100, 2),
        "avg_memory_working_set_bytes": int(memory_gb * 1024**3 * 0.82),
        "avg_requests_per_second": avg_rps,
        "avg_ready_pods": 12,
        "benchmark_compute_cost_usd": 0.0,
        "benchmark_end": benchmark_end,
        "benchmark_start": benchmark_start,
        "cloud_provider": "local",
        "cost_per_1m_requests_usd": 0.0,
        "cpu_platform": None,
        "duration_seconds": duration_seconds,
        "empty_metrics": [],
        "environment": "local",
        "frontend_latency_max_ms": latency_max,
        "frontend_latency_p50_ms": latency_p50,
        "frontend_latency_p95_ms": latency_p95,
        "frontend_latency_p99_ms": latency_p99,
        "generated_at": "2026-05-09T00:00:00Z",
        "invalid_metric_samples": {},
        "load_concurrent_users": 50,
        "load_profile_source": "phase8-local-validation",
        "load_users_per_second": 10,
        "machine_type": machine_type,
        "max_cpu_throttling_ratio": 0.03,
        "max_cpu_usage_cores": max_cpu_usage_cores,
        "max_cpu_utilization_pct": round(max_cpu_usage_cores / 4 * 100, 2),
        "max_memory_used_gb": memory_gb,
        "max_memory_working_set_bytes": int(memory_gb * 1024**3),
        "max_ready_pods": 12,
        "max_restarts_total": 0,
        "metrics_coverage_ratio": coverage,
        "min_ready_pods": 12,
        "missing_metrics": [],
        "namespace": "silicon-boutique-validation",
        "node_count": 1,
        "node_hourly_price_usd": 0.0,
        "pricing_model": "local",
        "processor_family": processor_family,
        "region": "local",
        "request_count_total": request_total,
        "request_failure_count": failures,
        "request_success_count": success,
        "run_id": run_id,
        "summary_status": "complete",
        "zone": "local",
    }


def overall_status(
    comparability_report: dict[str, Any], comparison_report: dict[str, Any]
) -> str:
    if comparability_report.get("comparability_status") != "pass":
        return "fail"
    if comparison_report.get("status") not in {"pass", "warn"}:
        return "fail"
    if not comparison_report.get("rejected_runs"):
        return "fail"
    return "pass"


def write_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def run_command(command: list[str], cwd: Path) -> CommandResult:
    env = None
    if command[:4] == [sys.executable, "-m", "unittest", "discover"] and "mcp-server/tests" in command:
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "mcp-server" / "src")}
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise Phase8LocalValidationError(f"command not found: {command[0]}") from exc
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return CommandResult(result.returncode, result.stdout, result.stderr)


def resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


if __name__ == "__main__":
    raise SystemExit(main())
