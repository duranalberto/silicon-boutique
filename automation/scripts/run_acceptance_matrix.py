#!/usr/bin/env python3
"""Run or verify the SiliconBoutique multi-cloud acceptance matrix."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import generate_comparison_report
import validate_benchmark_comparability


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared.automation import read_json, write_json


REPORT_NAME = "acceptance-matrix-report.json"
SUMMARY_SCHEMA = Path("automation/templates/benchmark-summary.schema.json")
PASSED = "passed"
FAILED = "failed"
SKIPPED_OPTIONAL = "skipped_optional"
SKIPPED_REQUIRES_CREDENTIALS = "skipped_requires_credentials"


@dataclass(frozen=True)
class MatrixConfig:
    mode: str
    artifacts_dir: Path
    local_artifacts: Path | None
    gcp_artifacts: Path | None
    aws_artifacts: Path | None
    local_test_duration: str
    local_min_duration_seconds: int
    dashboard_hold_seconds: int
    schema: Path
    min_duration_seconds: int
    min_coverage_ratio: float

    @property
    def report_path(self) -> Path:
        return self.artifacts_dir / REPORT_NAME

    @property
    def default_local_artifacts(self) -> Path:
        return self.artifacts_dir / "local"


class AcceptanceMatrixError(RuntimeError):
    """Raised when matrix verification cannot inspect an artifact set."""


class AcceptanceMatrix:
    def __init__(self, config: MatrixConfig, *, runner=subprocess.run) -> None:
        self.config = config
        self.runner = runner

    def run(self) -> int:
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifacts = self.artifact_paths()
        if self.config.mode in {"local", "full"}:
            self.run_local_acceptance(artifacts["local"])

        verified = {
            "local": self.verify_optional_local(artifacts["local"]),
            "gcp": self.verify_cloud("gcp", artifacts["gcp"]),
            "aws": self.verify_cloud("aws", artifacts["aws"]),
        }
        comparison = self.build_multi_cloud_comparison(verified)
        report = self.build_report(verified, comparison)
        write_json(self.config.report_path, report)
        return 0 if report["status"] == PASSED else 2

    def artifact_paths(self) -> dict[str, Path | None]:
        local = self.config.local_artifacts
        if self.config.mode in {"local", "full"} and local is None:
            local = self.config.default_local_artifacts
        return {
            "local": local,
            "gcp": self.config.gcp_artifacts,
            "aws": self.config.aws_artifacts,
        }

    def run_local_acceptance(self, artifacts_dir: Path | None) -> None:
        if artifacts_dir is None:
            raise AcceptanceMatrixError("local artifacts directory is required")
        command = [
            sys.executable,
            "automation/scripts/run_acceptance_demo.py",
            "--mode",
            "local",
            "--artifacts-dir",
            str(artifacts_dir),
            "--test-duration",
            self.config.local_test_duration,
            "--min-duration-seconds",
            str(self.config.local_min_duration_seconds),
            "--dashboard-hold-seconds",
            str(self.config.dashboard_hold_seconds),
        ]
        completed = self.runner(command, cwd=REPO_ROOT, text=True)
        if completed.returncode != 0:
            raise AcceptanceMatrixError(
                f"local acceptance demo failed with exit {completed.returncode}"
            )

    def verify_optional_local(self, path: Path | None) -> dict[str, Any]:
        if path is None:
            return {"status": SKIPPED_OPTIONAL, "reason": "local artifacts were not supplied"}
        if not path.exists():
            return {"status": SKIPPED_OPTIONAL, "reason": f"local artifacts do not exist: {path}"}
        return self.verify_artifact_set(path, expected_provider="local", require_bigquery=False)

    def verify_cloud(self, provider: str, path: Path | None) -> dict[str, Any]:
        if path is None:
            return {
                "status": SKIPPED_REQUIRES_CREDENTIALS,
                "reason": f"{provider.upper()} artifacts were not supplied",
            }
        if not path.exists():
            return {
                "status": SKIPPED_REQUIRES_CREDENTIALS,
                "reason": f"{provider.upper()} artifacts do not exist: {path}",
            }
        return self.verify_artifact_set(path, expected_provider=provider, require_bigquery=True)

    def verify_artifact_set(
        self, path: Path, *, expected_provider: str, require_bigquery: bool
    ) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "status": PASSED,
            "artifacts_dir": str(path),
            "cloud_provider": expected_provider,
            "errors": [],
        }
        try:
            trace = read_required_json(path / "workflow-trace.json")
            summary = read_required_json(path / "benchmark-summary.json")
            acceptance = read_required_json(path / "acceptance-demo-report.json")
            comparability = read_required_json(path / "comparability-report.json")
            teardown = read_required_env(path / "teardown-status.env")
            bigquery = read_optional_json(path / "bigquery-load-report.json")
        except AcceptanceMatrixError as exc:
            evidence["status"] = FAILED
            evidence["errors"].append(str(exc))
            return evidence

        trace_run_id = str(trace.get("benchmark", {}).get("run_id") or "")
        summary_run_id = str(summary.get("run_id") or "")
        acceptance_run_id = str(acceptance.get("run_id") or "")
        provider = str(summary.get("cloud_provider") or "")
        evidence.update(
            {
                "run_id": trace_run_id,
                "summary_path": str(path / "benchmark-summary.json"),
                "workflow_trace_path": str(path / "workflow-trace.json"),
                "acceptance_report_path": str(path / "acceptance-demo-report.json"),
                "teardown_status_path": str(path / "teardown-status.env"),
            }
        )

        errors = evidence["errors"]
        if not trace_run_id:
            errors.append("workflow trace is missing benchmark.run_id")
        if summary_run_id != trace_run_id:
            errors.append("benchmark summary run_id does not match workflow trace")
        if acceptance_run_id != trace_run_id:
            errors.append("acceptance report run_id does not match workflow trace")
        if provider != expected_provider:
            errors.append(f"summary cloud_provider is {provider!r}, expected {expected_provider!r}")
        if summary.get("summary_status") != "complete":
            errors.append("benchmark summary is not complete")

        dashboard = acceptance.get("checks", {}).get("dashboard", {})
        grafana = dashboard.get("grafana_load_status", {})
        if acceptance.get("status") != PASSED or grafana.get("status") != PASSED:
            errors.append("acceptance report does not prove Grafana dashboard API success")

        comparable = comparability.get("comparable_run_ids", [])
        if (
            comparability.get("summary_validation_status") != "pass"
            or trace_run_id not in comparable
        ):
            errors.append("comparability report does not accept the benchmark run")

        if teardown.get("destroy_succeeded") != "true":
            errors.append("teardown-status.env does not prove destroy_succeeded=true")
        if str(trace.get("teardown", {}).get("destroy_succeeded")) != "true":
            errors.append("workflow trace does not prove teardown success")

        if require_bigquery:
            if bigquery is None:
                errors.append("missing required BigQuery load report")
            elif bigquery.get("status") not in {"loaded", "validated"} or trace_run_id not in bigquery.get("run_ids", []):
                errors.append("BigQuery load report does not prove the benchmark run_id")
            else:
                evidence["bigquery_summary_table"] = bigquery.get("summary_table", "")
        elif bigquery is not None:
            evidence["bigquery_summary_table"] = bigquery.get("summary_table", "")

        if errors:
            evidence["status"] = FAILED
        return evidence

    def build_multi_cloud_comparison(
        self, verified: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        cloud_runs = [
            verified[provider]
            for provider in ("gcp", "aws")
            if verified[provider].get("status") == PASSED
        ]
        if len(cloud_runs) < 2:
            return {
                "status": SKIPPED_REQUIRES_CREDENTIALS,
                "reason": "both GCP and AWS accepted artifact sets are required",
            }

        summaries = [read_json(Path(run["summary_path"])) for run in cloud_runs]
        store_path = self.config.artifacts_dir / "acceptance-matrix-summaries.ndjson"
        report_path = self.config.artifacts_dir / "acceptance-matrix-comparison.json"
        markdown_path = self.config.artifacts_dir / "acceptance-matrix-comparison.md"
        store_path.write_text(
            "".join(json.dumps(summary, sort_keys=True) + "\n" for summary in summaries),
            encoding="utf-8",
        )
        schema = validate_benchmark_comparability.load_json(self.config.schema, "schema")
        report = generate_comparison_report.build_comparison_report(
            rows=summaries,
            source={"type": "ndjson", "summary_store": str(store_path)},
            schema=schema,
            schema_path=self.config.schema,
            min_duration_seconds=self.config.min_duration_seconds,
            min_coverage_ratio=self.config.min_coverage_ratio,
        )
        generate_comparison_report.write_json(report_path, report)
        generate_comparison_report.write_text(
            markdown_path,
            generate_comparison_report.render_markdown(report),
        )
        status = PASSED if report["status"] in {"pass", "warn"} else FAILED
        return {
            "status": status,
            "comparison_status": report["status"],
            "report_path": str(report_path),
            "markdown_path": str(markdown_path),
            "summary_store_path": str(store_path),
            "comparable_run_count": report["comparable_run_count"],
            "comparison_group_count": report["comparison_group_count"],
        }

    def build_report(
        self,
        verified: dict[str, dict[str, Any]],
        comparison: dict[str, Any],
    ) -> dict[str, Any]:
        accepted = [
            run for run in verified.values() if run.get("status") == PASSED
        ]
        cloud_accepted = [
            run for run in (verified["gcp"], verified["aws"]) if run.get("status") == PASSED
        ]
        dashboard_status = aggregate_required(
            [
                {
                    "provider": run.get("cloud_provider"),
                    "run_id": run.get("run_id"),
                    "status": run.get("status"),
                }
                for run in accepted
            ],
            empty_status=SKIPPED_OPTIONAL,
            empty_reason="no accepted artifact sets were available",
        )
        canonical_status = aggregate_required(cloud_accepted, empty_status=SKIPPED_REQUIRES_CREDENTIALS)
        durable_status = aggregate_required(cloud_accepted, empty_status=SKIPPED_REQUIRES_CREDENTIALS)
        teardown_status = aggregate_required(accepted, empty_status=SKIPPED_OPTIONAL)
        checks = {
            "local_smoke": verified["local"],
            "gcp_live_benchmark": verified["gcp"],
            "aws_live_benchmark": verified["aws"],
            "dashboard_api_proof": dashboard_status,
            "canonical_summaries": canonical_status,
            "durable_summary_storage": durable_status,
            "comparison_report": comparison,
            "teardown_evidence": teardown_status,
        }
        status = PASSED
        if any(check.get("status") == FAILED for check in checks.values()):
            status = FAILED
        return {
            "status": status,
            "mode": self.config.mode,
            "generated_at": utc_now(),
            "artifacts_dir": str(self.config.artifacts_dir),
            "checks": checks,
        }


def aggregate_required(
    runs: list[dict[str, Any]],
    *,
    empty_status: str,
    empty_reason: str | None = None,
) -> dict[str, Any]:
    if not runs:
        payload = {"status": empty_status}
        if empty_reason:
            payload["reason"] = empty_reason
        return payload
    status = FAILED if any(run.get("status") == FAILED for run in runs) else PASSED
    return {
        "status": status,
        "run_ids": [run.get("run_id") for run in runs if run.get("run_id")],
        "providers": [run.get("cloud_provider") for run in runs if run.get("cloud_provider")],
    }


def read_required_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AcceptanceMatrixError(f"missing required artifact: {path}")
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise AcceptanceMatrixError(f"artifact is not a JSON object: {path}")
    return payload


def read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_required_json(path)


def read_required_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise AcceptanceMatrixError(f"missing required artifact: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or verify the SiliconBoutique multi-cloud acceptance matrix."
    )
    parser.add_argument("--mode", choices=("local", "verify", "full"), default="verify")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--local-artifacts", type=Path)
    parser.add_argument("--gcp-artifacts", type=Path)
    parser.add_argument("--aws-artifacts", type=Path)
    parser.add_argument("--local-test-duration", default="2m")
    parser.add_argument("--local-min-duration-seconds", type=int, default=60)
    parser.add_argument("--dashboard-hold-seconds", type=int, default=0)
    parser.add_argument("--schema", type=Path, default=SUMMARY_SCHEMA)
    parser.add_argument("--min-duration-seconds", type=int, default=1200)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    args = parser.parse_args(argv)
    if args.local_min_duration_seconds < 1:
        parser.error("--local-min-duration-seconds must be at least 1")
    if args.dashboard_hold_seconds < 0:
        parser.error("--dashboard-hold-seconds must be at least 0")
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if not 0 <= args.min_coverage_ratio <= 1:
        parser.error("--min-coverage-ratio must be between 0 and 1")
    return args


def config_from_args(args: argparse.Namespace) -> MatrixConfig:
    return MatrixConfig(
        mode=args.mode,
        artifacts_dir=args.artifacts_dir,
        local_artifacts=args.local_artifacts,
        gcp_artifacts=args.gcp_artifacts,
        aws_artifacts=args.aws_artifacts,
        local_test_duration=args.local_test_duration,
        local_min_duration_seconds=args.local_min_duration_seconds,
        dashboard_hold_seconds=args.dashboard_hold_seconds,
        schema=args.schema,
        min_duration_seconds=args.min_duration_seconds,
        min_coverage_ratio=args.min_coverage_ratio,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return AcceptanceMatrix(config_from_args(args)).run()
    except AcceptanceMatrixError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
