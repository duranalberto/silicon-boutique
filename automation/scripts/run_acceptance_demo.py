#!/usr/bin/env python3
"""Run and verify the SiliconBoutique end-to-end acceptance demo."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_local_benchmark


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared.automation import read_json, write_json

REPORT_NAME = "acceptance-demo-report.json"
DASHBOARD_KEY = "online-boutique-benchmark.json"
EXPECTED_DASHBOARD_UID = "silicon-boutique-online-boutique"
EXPECTED_DASHBOARD_TITLE = "SiliconBoutique Online Boutique Benchmark"
EXPECTED_PANEL_EXPRESSIONS = (
    "silicon_boutique:workload_cpu_usage_cores:rate5m",
    "silicon_boutique:workload_cpu_utilization_pct",
    "silicon_boutique:workload_memory_working_set_bytes",
    "silicon_boutique:workload_cpu_throttling_ratio:rate5m",
    "silicon_boutique:frontend_probe_latency_seconds",
    "silicon_boutique:workload_ready_pods",
    "silicon_boutique:workload_restarts_total",
)
REQUIRED_METRICS = (
    "cpu_usage_cores",
    "cpu_utilization_pct",
    "memory_working_set_bytes",
    "cpu_throttling_ratio",
    "frontend_probe_latency_seconds",
    "ready_pods",
    "restarts_total",
)


class AcceptanceDemoError(RuntimeError):
    """Raised when acceptance demo evidence is missing or inconsistent."""


@dataclass
class AcceptanceConfig:
    mode: str
    run_id: str
    artifacts_dir: Path
    test_duration: str
    min_duration_seconds: int
    concurrent_users: str
    users_per_second: str
    prometheus_port: int
    dashboard_hold_seconds: int
    grafana_port: int
    bigquery_project_id: str
    bigquery_dataset: str
    bigquery_table: str
    bigquery_location: str
    require_bigquery: bool
    cloud_provider: str
    namespace: str

    @property
    def report_path(self) -> Path:
        return self.artifacts_dir / REPORT_NAME


class AcceptanceDemo:
    def __init__(
        self,
        config: AcceptanceConfig,
        *,
        runner: run_local_benchmark.CommandRunner | None = None,
        sleep=time.sleep,
        popen=subprocess.Popen,
    ) -> None:
        self.config = config
        self.runner = runner or run_local_benchmark.CommandRunner()
        self.sleep = sleep
        self.popen = popen
        self.dashboard_evidence: dict[str, Any] = {}
        self.bigquery_evidence: dict[str, Any] = {}
        self.primary_error: Exception | None = None

    def run(self) -> int:
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        if self.config.mode == "local":
            return self.run_local()
        return self.verify_existing()

    def run_local(self) -> int:
        benchmark = run_local_benchmark.LocalBenchmark(
            self.local_benchmark_config(),
            runner=self.runner,
            sleep=self.sleep,
            popen=self.popen,
        )
        def capture_evidence(completed_benchmark: run_local_benchmark.LocalBenchmark) -> None:
            self.dashboard_evidence = self.capture_dashboard_evidence(
                namespace=completed_benchmark.config.namespace,
                kube_context=completed_benchmark.config.kube_context,
                run_id=completed_benchmark.config.run_id,
            )
            self.bigquery_evidence = self.maybe_load_bigquery(completed_benchmark.config.run_id)
            self.hold_dashboard_if_requested(
                namespace=completed_benchmark.config.namespace,
                kube_context=completed_benchmark.config.kube_context,
            )

        result = benchmark.execute(after_extract=capture_evidence)
        self.primary_error = result.primary_error
        if result.teardown_error and self.primary_error is None:
            self.primary_error = result.teardown_error

        status = self.write_acceptance_report(
            run_id=benchmark.config.run_id,
            namespace=benchmark.config.namespace,
            cloud_provider=benchmark.config.cloud_provider,
        )
        if self.primary_error:
            print(str(self.primary_error), file=sys.stderr)
            return 2
        return 0 if status == "passed" else 2

    def verify_existing(self) -> int:
        try:
            run_id = self.expected_run_id()
            namespace = self.namespace_from_trace(fallback=self.config.namespace)
            self.dashboard_evidence = self.capture_dashboard_evidence(
                namespace=namespace,
                kube_context="",
                run_id=run_id,
            )
            self.bigquery_evidence = self.verify_bigquery_report(run_id)
        except Exception as exc:
            self.primary_error = exc
        run_id = self.expected_run_id(fallback=self.config.run_id)
        status = self.write_acceptance_report(
            run_id=run_id,
            namespace=self.namespace_from_trace(fallback=self.config.namespace),
            cloud_provider=self.config.cloud_provider,
        )
        if self.primary_error:
            print(str(self.primary_error), file=sys.stderr)
            return 2
        return 0 if status == "passed" else 2

    def local_benchmark_config(self) -> run_local_benchmark.BenchmarkConfig:
        args = run_local_benchmark.parse_args(
            [
                "--run-id",
                self.config.run_id,
                "--artifacts-dir",
                str(self.config.artifacts_dir),
                "--test-duration",
                self.config.test_duration,
                "--min-duration-seconds",
                str(self.config.min_duration_seconds),
                "--concurrent-users",
                self.config.concurrent_users,
                "--users-per-second",
                self.config.users_per_second,
                "--prometheus-port",
                str(self.config.prometheus_port),
            ]
        )
        return run_local_benchmark.config_from_args(args)

    def capture_dashboard_evidence(
        self, *, namespace: str, kube_context: str, run_id: str
    ) -> dict[str, Any]:
        command = [
            "kubectl",
            "get",
            "configmap",
            "--namespace",
            namespace,
            "-l",
            "grafana_dashboard=1",
            "-o",
            "json",
        ]
        if kube_context:
            command.extend(["--context", kube_context])
        result = self.runner.run(command, capture=True)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AcceptanceDemoError("dashboard ConfigMap query returned invalid JSON") from exc

        dashboards = []
        for item in payload.get("items", []):
            data = item.get("data", {})
            if DASHBOARD_KEY not in data:
                continue
            try:
                dashboard = json.loads(data[DASHBOARD_KEY])
            except json.JSONDecodeError as exc:
                raise AcceptanceDemoError("dashboard ConfigMap contains invalid JSON") from exc
            dashboard_json = json.dumps(dashboard, sort_keys=True)
            missing_expressions = [
                expression
                for expression in EXPECTED_PANEL_EXPRESSIONS
                if expression not in dashboard_json
            ]
            dashboards.append(
                {
                    "configmap": item.get("metadata", {}).get("name", ""),
                    "key": DASHBOARD_KEY,
                    "uid": dashboard.get("uid"),
                    "title": dashboard.get("title"),
                    "run_id_present": run_id in dashboard_json,
                    "missing_panel_expressions": missing_expressions,
                }
            )

        selected = next(
            (
                dashboard
                for dashboard in dashboards
                if dashboard["uid"] == EXPECTED_DASHBOARD_UID
                and dashboard["title"] == EXPECTED_DASHBOARD_TITLE
            ),
            None,
        )
        if selected is None:
            raise AcceptanceDemoError("expected Grafana dashboard ConfigMap was not found")
        if selected["missing_panel_expressions"]:
            raise AcceptanceDemoError("Grafana dashboard is missing expected panel expressions")
        if not selected["run_id_present"]:
            raise AcceptanceDemoError("Grafana dashboard evidence does not include the acceptance run_id")

        metrics_evidence = self.prometheus_metrics_evidence(run_id)
        if metrics_evidence["status"] != "passed":
            raise AcceptanceDemoError("Prometheus metric evidence is missing required samples")
        grafana_load_status = self.grafana_dashboard_load_evidence(
            namespace=namespace,
            kube_context=kube_context,
        )
        if grafana_load_status["status"] == "failed":
            raise AcceptanceDemoError("Grafana dashboard API returned unexpected dashboard metadata")
        return {
            "status": "passed",
            "dashboard_service": "sb-monitoring-grafana",
            "dashboard_uid": selected["uid"],
            "dashboard_title": selected["title"],
            "dashboard_configmap": selected["configmap"],
            "dashboard_key": selected["key"],
            "run_id_present": selected["run_id_present"],
            "missing_panel_expressions": selected["missing_panel_expressions"],
            "prometheus_metrics": metrics_evidence,
            "grafana_load_status": grafana_load_status,
        }

    def grafana_dashboard_load_evidence(
        self, *, namespace: str, kube_context: str
    ) -> dict[str, Any]:
        try:
            with self.port_forward_grafana(namespace=namespace, kube_context=kube_context):
                result = self.runner.run(
                    [
                        "curl",
                        "-fsS",
                        "-u",
                        "admin:prom-operator",
                        f"http://127.0.0.1:{self.config.grafana_port}/api/dashboards/uid/{EXPECTED_DASHBOARD_UID}",
                    ],
                    check=False,
                    capture=True,
                )
        except Exception as exc:
            return {
                "status": "skipped_unavailable",
                "reason": str(exc),
                "dashboard_uid": EXPECTED_DASHBOARD_UID,
            }
        if result.returncode != 0:
            return {
                "status": "skipped_unavailable",
                "reason": result.stderr.strip() or "Grafana API request failed",
                "dashboard_uid": EXPECTED_DASHBOARD_UID,
            }
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "status": "skipped_unavailable",
                "reason": "Grafana API did not return JSON dashboard metadata",
                "dashboard_uid": EXPECTED_DASHBOARD_UID,
            }
        dashboard = payload.get("dashboard") if isinstance(payload, dict) else None
        uid = dashboard.get("uid") if isinstance(dashboard, dict) else None
        title = dashboard.get("title") if isinstance(dashboard, dict) else None
        status = "passed" if uid == EXPECTED_DASHBOARD_UID and title == EXPECTED_DASHBOARD_TITLE else "failed"
        return {
            "status": status,
            "dashboard_uid": uid,
            "dashboard_title": title,
            "url": f"http://127.0.0.1:{self.config.grafana_port}/api/dashboards/uid/{EXPECTED_DASHBOARD_UID}",
        }

    def prometheus_metrics_evidence(self, run_id: str) -> dict[str, Any]:
        metrics_path = self.config.artifacts_dir / "prometheus-metrics.json"
        if not metrics_path.exists():
            raise AcceptanceDemoError("missing Prometheus metrics artifact")
        payload = read_json(metrics_path)
        if payload.get("run_id") != run_id:
            raise AcceptanceDemoError("Prometheus metrics run_id does not match acceptance run_id")
        metrics = payload.get("metrics", {})
        missing = []
        empty = []
        for name in REQUIRED_METRICS:
            metric = metrics.get(name)
            if not isinstance(metric, dict):
                missing.append(name)
                continue
            if int(metric.get("sample_count") or 0) < 1:
                empty.append(name)
        return {
            "metrics_path": str(metrics_path),
            "required_metrics": list(REQUIRED_METRICS),
            "missing_metrics": missing,
            "empty_metrics": empty,
            "coverage_ratio": payload.get("quality", {}).get("coverage_ratio"),
            "status": "passed" if not missing and not empty else "failed",
        }

    def maybe_load_bigquery(self, run_id: str) -> dict[str, Any]:
        provided = all(
            (
                self.config.bigquery_project_id,
                self.config.bigquery_dataset,
                self.config.bigquery_table,
                self.config.bigquery_location,
            )
        )
        report_path = self.config.artifacts_dir / "bigquery-load-report.json"
        if not provided:
            if self.config.require_bigquery:
                raise AcceptanceDemoError("BigQuery settings are required for this acceptance mode")
            return {
                "status": "skipped_optional",
                "reason": "BigQuery settings were not provided for local acceptance.",
                "load_report_path": str(report_path),
            }
        self.runner.run(
            [
                sys.executable,
                "automation/scripts/load_benchmark_summary_to_bigquery.py",
                "--summary-store",
                str(self.config.artifacts_dir / "benchmark-summaries.ndjson"),
                "--project-id",
                self.config.bigquery_project_id,
                "--dataset-id",
                self.config.bigquery_dataset,
                "--table-id",
                self.config.bigquery_table,
                "--location",
                self.config.bigquery_location,
                "--schema",
                "automation/templates/benchmark-summary.bigquery-schema.json",
                "--load-report-output",
                str(report_path),
                "--duplicate-policy",
                "fail",
                "--run-id",
                run_id,
            ],
            cwd=REPO_ROOT,
        )
        return self.verify_bigquery_report(run_id)

    def verify_bigquery_report(self, run_id: str) -> dict[str, Any]:
        report_path = self.config.artifacts_dir / "bigquery-load-report.json"
        if not report_path.exists():
            if self.config.require_bigquery:
                raise AcceptanceDemoError("missing required BigQuery load report")
            return {
                "status": "skipped_optional",
                "reason": "BigQuery load report was not present.",
                "load_report_path": str(report_path),
            }
        payload = read_json(report_path)
        status = payload.get("status")
        run_ids = payload.get("run_ids", [])
        if status not in ("loaded", "validated") or run_id not in run_ids:
            raise AcceptanceDemoError("BigQuery load report does not prove the acceptance run_id")
        return {
            "status": "passed",
            "load_report_path": str(report_path),
            "summary_table": payload.get("summary_table", ""),
            "row_count": payload.get("row_count", 0),
            "run_ids": run_ids,
            "dry_run": payload.get("dry_run", False),
        }

    def hold_dashboard_if_requested(self, *, namespace: str, kube_context: str) -> None:
        if self.config.dashboard_hold_seconds <= 0:
            self.dashboard_evidence["live_inspection"] = {
                "status": "skipped_optional",
                "reason": "dashboard hold was not requested",
            }
            return
        with self.port_forward_grafana(namespace=namespace, kube_context=kube_context):
            self.dashboard_evidence["live_inspection"] = {
                "status": "passed",
                "url": f"http://127.0.0.1:{self.config.grafana_port}",
                "hold_seconds": self.config.dashboard_hold_seconds,
                "dashboard_uid": EXPECTED_DASHBOARD_UID,
                "dashboard_title": EXPECTED_DASHBOARD_TITLE,
            }
            self.sleep(self.config.dashboard_hold_seconds)

    @contextmanager
    def port_forward_grafana(self, *, namespace: str, kube_context: str):
        command = [
            "kubectl",
            "port-forward",
            "service/sb-monitoring-grafana",
            f"{self.config.grafana_port}:80",
            "--namespace",
            namespace,
        ]
        if kube_context:
            command.extend(["--context", kube_context])
        process = self.popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            self.sleep(2)
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    def write_acceptance_report(
        self, *, run_id: str, namespace: str, cloud_provider: str
    ) -> str:
        checks = {
            "trace": self.trace_check(run_id),
            "summary": self.summary_check(run_id),
            "summary_store": self.summary_store_check(run_id),
            "comparability": self.comparability_check(run_id),
            "dashboard": self.dashboard_evidence
            or {"status": "failed", "error": "dashboard evidence was not captured"},
            "bigquery": self.bigquery_evidence
            or self.verify_bigquery_report_best_effort(run_id),
        }
        if self.primary_error:
            checks["orchestration"] = {
                "status": "failed",
                "error": str(self.primary_error),
            }
        else:
            checks["orchestration"] = {"status": "passed"}

        status = "passed"
        for check in checks.values():
            if check.get("status") == "failed":
                status = "failed"
                break

        report = {
            "status": status,
            "run_id": run_id,
            "namespace": namespace,
            "cloud_provider": cloud_provider,
            "mode": self.config.mode,
            "artifacts_dir": str(self.config.artifacts_dir),
            "dashboard_location": {
                "service": "sb-monitoring-grafana",
                "dashboard_uid": EXPECTED_DASHBOARD_UID,
                "dashboard_title": EXPECTED_DASHBOARD_TITLE,
                "local_url": self.dashboard_evidence.get("live_inspection", {}).get("url"),
            },
            "checks": checks,
        }
        write_json(self.config.report_path, report)
        return status

    def verify_bigquery_report_best_effort(self, run_id: str) -> dict[str, Any]:
        try:
            return self.verify_bigquery_report(run_id)
        except AcceptanceDemoError as exc:
            return {"status": "failed", "error": str(exc)}

    def trace_check(self, run_id: str) -> dict[str, Any]:
        trace_path = self.config.artifacts_dir / "workflow-trace.json"
        if not trace_path.exists():
            return {"status": "failed", "error": "missing workflow trace", "path": str(trace_path)}
        trace = read_json(trace_path)
        actual = trace.get("benchmark", {}).get("run_id")
        teardown_status = trace.get("teardown", {}).get("destroy_succeeded", "")
        status = "passed" if actual == run_id else "failed"
        return {
            "status": status,
            "path": str(trace_path),
            "run_id": actual,
            "teardown_succeeded": teardown_status,
        }

    def summary_check(self, run_id: str) -> dict[str, Any]:
        path = self.config.artifacts_dir / "benchmark-summary.json"
        if not path.exists():
            return {"status": "failed", "error": "missing benchmark summary", "path": str(path)}
        summary = read_json(path)
        status = "passed"
        if summary.get("run_id") != run_id or summary.get("summary_status") != "complete":
            status = "failed"
        return {
            "status": status,
            "path": str(path),
            "run_id": summary.get("run_id"),
            "summary_status": summary.get("summary_status"),
            "avg_cpu_utilization_pct": summary.get("avg_cpu_utilization_pct"),
            "request_success_count": summary.get("request_success_count"),
        }

    def summary_store_check(self, run_id: str) -> dict[str, Any]:
        path = self.config.artifacts_dir / "benchmark-summaries.ndjson"
        if not path.exists():
            return {"status": "failed", "error": "missing summary store", "path": str(path)}
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        matches = [row for row in rows if row.get("run_id") == run_id]
        return {
            "status": "passed" if len(matches) == 1 else "failed",
            "path": str(path),
            "row_count": len(rows),
            "matching_run_count": len(matches),
        }

    def comparability_check(self, run_id: str) -> dict[str, Any]:
        path = self.config.artifacts_dir / "comparability-report.json"
        if not path.exists():
            return {"status": "failed", "error": "missing comparability report", "path": str(path)}
        report = read_json(path)
        comparable = report.get("comparable_run_ids", [])
        summary_status = report.get("summary_validation_status")
        status = "passed" if summary_status == "pass" and run_id in comparable else "failed"
        return {
            "status": status,
            "path": str(path),
            "summary_validation_status": summary_status,
            "comparable_run_ids": comparable,
        }

    def expected_run_id(self, *, fallback: str = "") -> str:
        if self.config.run_id:
            return self.config.run_id
        trace_path = self.config.artifacts_dir / "workflow-trace.json"
        if trace_path.exists():
            return str(read_json(trace_path).get("benchmark", {}).get("run_id", fallback))
        return fallback

    def namespace_from_trace(self, *, fallback: str = "") -> str:
        trace_path = self.config.artifacts_dir / "workflow-trace.json"
        if trace_path.exists():
            return str(read_json(trace_path).get("benchmark", {}).get("namespace", fallback))
        return fallback


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or verify the SiliconBoutique end-to-end acceptance demo."
    )
    parser.add_argument("--mode", choices=("local", "verify"), default="local")
    parser.add_argument("--run-id", default=run_local_benchmark.default_run_id())
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--test-duration", default="2m")
    parser.add_argument("--min-duration-seconds", type=int, default=60)
    parser.add_argument("--concurrent-users", default="10")
    parser.add_argument("--users-per-second", default="1")
    parser.add_argument("--prometheus-port", type=int, default=9090)
    parser.add_argument("--dashboard-hold-seconds", type=int, default=0)
    parser.add_argument("--grafana-port", type=int, default=3000)
    parser.add_argument("--bigquery-project-id", default="")
    parser.add_argument("--bigquery-dataset", default="")
    parser.add_argument("--bigquery-table", default="")
    parser.add_argument("--bigquery-location", default="")
    parser.add_argument("--require-bigquery", action="store_true")
    parser.add_argument("--cloud-provider", default="local")
    parser.add_argument("--namespace", default="")
    args = parser.parse_args(argv)
    validate_args(args, parser)
    return args


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if args.dashboard_hold_seconds < 0:
        parser.error("--dashboard-hold-seconds must be at least 0")
    if args.grafana_port < 1 or args.grafana_port > 65535:
        parser.error("--grafana-port must be between 1 and 65535")
    try:
        run_local_benchmark.parse_duration_seconds(args.test_duration)
    except ValueError as exc:
        parser.error(str(exc))


def config_from_args(args: argparse.Namespace) -> AcceptanceConfig:
    return AcceptanceConfig(
        mode=args.mode,
        run_id=args.run_id,
        artifacts_dir=args.artifacts_dir,
        test_duration=args.test_duration,
        min_duration_seconds=args.min_duration_seconds,
        concurrent_users=args.concurrent_users,
        users_per_second=args.users_per_second,
        prometheus_port=args.prometheus_port,
        dashboard_hold_seconds=args.dashboard_hold_seconds,
        grafana_port=args.grafana_port,
        bigquery_project_id=args.bigquery_project_id,
        bigquery_dataset=args.bigquery_dataset,
        bigquery_table=args.bigquery_table,
        bigquery_location=args.bigquery_location,
        require_bigquery=args.require_bigquery,
        cloud_provider=args.cloud_provider,
        namespace=args.namespace,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    demo = AcceptanceDemo(config_from_args(args))
    return demo.run()


if __name__ == "__main__":
    sys.exit(main())
