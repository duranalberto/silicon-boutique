#!/usr/bin/env python3
"""Run the SiliconBoutique benchmark flow against local Kubernetes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ID_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class LocalBenchmarkError(RuntimeError):
    """Raised when the local benchmark flow fails."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class BenchmarkConfig:
    run_id: str
    artifacts_dir: Path
    terraform_dir: Path
    workload_chart: Path
    monitoring_chart: Path
    workload_release: str
    monitoring_release: str
    machine_type: str
    processor_family: str
    cpu_platform: str | None
    architecture: str
    region: str
    zone: str
    node_count: int
    concurrent_users: str
    users_per_second: str
    test_duration: str
    test_duration_seconds: int
    pricing_model: str
    load_profile_source: str
    prometheus_port: int
    min_duration_seconds: int
    min_coverage_ratio: float
    failure_stage: str
    skip_destroy: bool

    environment: str = "local"
    cloud_provider: str = "local"
    namespace: str = ""
    kube_context: str = "siliconboutique"
    benchmark_start: str = ""
    benchmark_end: str = ""
    destroy_attempted: str = "unknown"
    destroy_succeeded: str = "unknown"

    @property
    def summary_artifact_name(self) -> str:
        return f"benchmark-local-{self.run_id}"


class CommandRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        capture: bool = False,
        log_path: Path | None = None,
        input_text: str | None = None,
        timeout: str | None = None,
    ) -> CommandResult:
        rendered = command
        if timeout:
            rendered = ["timeout", timeout, *command]

        completed = subprocess.run(
            rendered,
            cwd=cwd,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE if capture or log_path else None,
            stderr=subprocess.PIPE if capture or log_path else None,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if log_path:
            append_log(log_path, rendered, stdout, stderr, completed.returncode)
        if check and completed.returncode != 0:
            raise LocalBenchmarkError(
                f"command failed with exit {completed.returncode}: {shell_join(rendered)}"
            )
        return CommandResult(completed.returncode, stdout, stderr)


class LocalBenchmark:
    def __init__(
        self,
        config: BenchmarkConfig,
        *,
        runner: CommandRunner | None = None,
        sleep=time.sleep,
        popen=subprocess.Popen,
    ) -> None:
        self.config = config
        self.runner = runner or CommandRunner()
        self.sleep = sleep
        self.popen = popen
        self.apply_attempted = False
        self.primary_error: Exception | None = None

    def run(self) -> int:
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.provision()
            self.fail_if_requested("after_provision")
            self.deploy_workload()
            self.deploy_monitoring()
            self.wait_for_required_metrics()
            self.fail_if_requested("after_monitoring_ready")
            self.run_benchmark_window()
            self.update_monitoring_benchmark_window()
            self.fail_if_requested("before_extract")
            self.extract_and_summarize()
        except Exception as exc:
            self.primary_error = exc
        finally:
            teardown_error = self.cleanup()
            self.write_trace()

        if teardown_error:
            print(str(teardown_error), file=sys.stderr)
            return 2
        if self.primary_error:
            print(str(self.primary_error), file=sys.stderr)
            return 2
        return 0

    def provision(self) -> None:
        self.validate_kubernetes_context()

        terraform_dir = self.config.terraform_dir
        self.runner.run(["terraform", "init", "-input=false"], cwd=terraform_dir)
        self.runner.run(["terraform", "validate"], cwd=terraform_dir)

        self.write_provision_status(
            {
                "apply_started": "true",
                "run_id": self.config.run_id,
                "environment": self.config.environment,
            }
        )
        self.apply_attempted = True
        result = self.runner.run(
            [
                "terraform",
                "apply",
                "-auto-approve",
                *self.terraform_vars(),
            ],
            cwd=terraform_dir,
            check=False,
            capture=True,
            log_path=self.config.artifacts_dir / "terraform-apply.log",
        )
        self.write_provision_status(
            {
                "apply_exit_code": str(result.returncode),
                "apply_succeeded": bool_string(result.returncode == 0),
            },
            append=True,
        )
        if result.returncode != 0:
            detail = summarize_command_failure(result)
            suffix = f": {detail}" if detail else ""
            raise LocalBenchmarkError(
                "terraform apply failed; inspect artifacts/terraform-apply.log"
                f"{suffix}"
            )

        outputs = self.terraform_outputs()
        self.config.run_id = output_value(outputs, "run_id", self.config.run_id)
        self.config.namespace = output_value(
            outputs, "namespace", f"silicon-boutique-{self.config.run_id}"
        )
        self.config.environment = output_value(outputs, "environment", "local")
        self.config.machine_type = output_value(
            outputs, "machine_type", self.config.machine_type
        )
        self.config.processor_family = output_value(
            outputs, "processor_family", self.config.processor_family
        )
        self.config.architecture = output_value(
            outputs, "architecture", self.config.architecture
        )
        self.config.region = output_value(outputs, "region", self.config.region)
        self.config.node_count = int(output_value(outputs, "node_count", self.config.node_count))
        self.config.kube_context = output_value(outputs, "kube_context", "siliconboutique")

        write_json(
            self.config.artifacts_dir / "terraform-labels.json",
            output_value(outputs, "labels", {}),
        )
        write_json(
            self.config.artifacts_dir / "teardown-check-commands.json",
            output_value(outputs, "teardown_check_commands", []),
        )
        write_json(
            self.config.artifacts_dir / "managed-resource-names.json",
            {
                "namespace": self.config.namespace,
                "name_prefix": output_value(outputs, "name_prefix", ""),
            },
        )

    def validate_kubernetes_context(self) -> None:
        result = self.runner.run(
            [
                "kubectl",
                "get",
                "nodes",
                "--context",
                self.config.kube_context,
                "--request-timeout=10s",
            ],
            check=False,
            capture=True,
        )
        if result.returncode == 0:
            return

        status = self.runner.run(
            ["minikube", "status", "--profile", self.config.kube_context],
            check=False,
            capture=True,
        )
        details = summarize_command_failure(result)
        minikube_status = summarize_command_failure(status)
        message = (
            f"Kubernetes context {self.config.kube_context!r} is not reachable before "
            "Terraform apply. Start or repair the devcontainer-managed minikube profile "
            f"with `.devcontainer/post-create.sh` or `minikube start --profile "
            f"{self.config.kube_context}`."
        )
        if details:
            message += f" kubectl reported: {details}."
        if minikube_status:
            message += f" minikube status: {minikube_status}."
        raise LocalBenchmarkError(message)

    def terraform_vars(self) -> list[str]:
        return [
            f"-var=run_id={self.config.run_id}",
            f"-var=machine_type={self.config.machine_type}",
            f"-var=region={self.config.region}",
            f"-var=node_count={self.config.node_count}",
            f"-var=processor_family={self.config.processor_family}",
            f"-var=architecture={self.config.architecture}",
        ]

    def terraform_outputs(self) -> dict[str, Any]:
        result = self.runner.run(
            ["terraform", "output", "-json"],
            cwd=self.config.terraform_dir,
            capture=True,
        )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LocalBenchmarkError("terraform output -json returned invalid JSON") from exc

    def deploy_workload(self) -> None:
        self.runner.run(["helm", "dependency", "update", str(self.config.workload_chart)])
        self.runner.run(["helm", "lint", str(self.config.workload_chart)])
        self.runner.run(
            [
                "bash",
                "-lc",
                "helm plugin list | awk 'NR > 1 {print $1}' | grep -qx "
                "silicon-boutique-metadata || helm plugin install "
                f"{shell_quote(str(self.config.workload_chart / 'post-renderer'))}",
            ]
        )
        self.runner.run(
            [
                "helm",
                "upgrade",
                "--install",
                self.config.workload_release,
                str(self.config.workload_chart),
                "--namespace",
                self.config.namespace,
                "--kube-context",
                self.config.kube_context,
                "--set-string",
                f"siliconBoutique.runId={self.config.run_id}",
                "--set-string",
                f"siliconBoutique.environment={self.config.environment}",
                "--set-string",
                f"siliconBoutique.machineType={self.config.machine_type}",
                "--set-string",
                f"siliconBoutique.processorFamily={self.config.processor_family}",
                "--set-string",
                f"siliconBoutique.architecture={self.config.architecture}",
                "--set",
                f"siliconBoutique.loadGenerator.concurrentUsers={self.config.concurrent_users}",
                "--set",
                f"siliconBoutique.loadGenerator.usersPerSecond={self.config.users_per_second}",
                "--set-string",
                f"siliconBoutique.loadGenerator.testDuration={self.config.test_duration}",
                "--post-renderer",
                "silicon-boutique-metadata",
            ]
        )
        self.runner.run(
            [
                "kubectl",
                "wait",
                "deployment",
                "--all",
                "--for=condition=Available",
                "--timeout=10m",
                "--namespace",
                self.config.namespace,
                "--context",
                self.config.kube_context,
            ]
        )

    def deploy_monitoring(self) -> None:
        self.runner.run(["helm", "dependency", "update", str(self.config.monitoring_chart)])
        self.runner.run(["helm", "lint", str(self.config.monitoring_chart)])
        self.runner.run(
            [
                "helm",
                "upgrade",
                "--install",
                self.config.monitoring_release,
                str(self.config.monitoring_chart),
                "--namespace",
                self.config.namespace,
                "--kube-context",
                self.config.kube_context,
                "--set-string",
                f"siliconBoutique.runId={self.config.run_id}",
                "--set-string",
                f"siliconBoutique.environment={self.config.environment}",
                "--set-string",
                f"siliconBoutique.machineType={self.config.machine_type}",
                "--set-string",
                f"siliconBoutique.processorFamily={self.config.processor_family}",
                "--set-string",
                f"siliconBoutique.architecture={self.config.architecture}",
                "--set-string",
                f"siliconBoutique.workloadNamespace={self.config.namespace}",
            ]
        )
        for command in (
            [
                "kubectl",
                "rollout",
                "status",
                "deployment/sb-monitoring-grafana",
            ],
            [
                "kubectl",
                "rollout",
                "status",
                "deployment/sb-monitoring-kube-state-metrics",
            ],
            [
                "kubectl",
                "rollout",
                "status",
                "deployment/sb-monitoring-prometheus-blackbox-exporter",
            ],
            [
                "kubectl",
                "rollout",
                "status",
                "daemonset/sb-monitoring-prometheus-node-exporter",
            ],
        ):
            self.runner.run(
                [
                    *command,
                    "--namespace",
                    self.config.namespace,
                    "--context",
                    self.config.kube_context,
                    "--timeout=10m",
                ]
            )
        self.runner.run(
            [
                "kubectl",
                "wait",
                "pod",
                "--for=condition=Ready",
                "--selector",
                "app.kubernetes.io/name=prometheus",
                "--timeout=10m",
                "--namespace",
                self.config.namespace,
                "--context",
                self.config.kube_context,
            ]
        )

    def wait_for_required_metrics(self) -> None:
        readiness_path = self.config.artifacts_dir / "prometheus-metrics-readiness.json"
        with self.port_forward_prometheus():
            for attempt in range(1, 41):
                end = utc_now()
                start = utc_offset(seconds=-60)
                result = self.runner.run(
                    [
                        sys.executable,
                        "automation/scripts/extract_prometheus_metrics.py",
                        "--prometheus-url",
                        f"http://127.0.0.1:{self.config.prometheus_port}",
                        "--run-id",
                        self.config.run_id,
                        "--namespace",
                        self.config.namespace,
                        "--start",
                        start,
                        "--end",
                        end,
                        "--step",
                        "15s",
                        "--output",
                        str(readiness_path),
                        "--strict",
                    ],
                    cwd=REPO_ROOT,
                    check=False,
                    capture=True,
                )
                if result.returncode == 0:
                    return
                if attempt == 40:
                    detail = summarize_command_failure(result)
                    suffix = f": {detail}" if detail else ""
                    raise LocalBenchmarkError(
                        "Prometheus required metrics did not become ready before "
                        "the benchmark window; inspect "
                        f"{readiness_path}{suffix}"
                    )
                self.sleep(15)

    def run_benchmark_window(self) -> None:
        self.runner.run(
            [
                "kubectl",
                "rollout",
                "restart",
                "deployment/loadgenerator",
                "--namespace",
                self.config.namespace,
                "--context",
                self.config.kube_context,
            ]
        )
        self.runner.run(
            [
                "kubectl",
                "rollout",
                "status",
                "deployment/loadgenerator",
                "--namespace",
                self.config.namespace,
                "--context",
                self.config.kube_context,
                "--timeout=10m",
            ]
        )
        self.config.benchmark_start = utc_now()
        self.sleep(self.config.test_duration_seconds)
        self.config.benchmark_end = utc_now()

    def update_monitoring_benchmark_window(self) -> None:
        self.runner.run(
            [
                "helm",
                "upgrade",
                "--install",
                self.config.monitoring_release,
                str(self.config.monitoring_chart),
                "--namespace",
                self.config.namespace,
                "--kube-context",
                self.config.kube_context,
                "--reuse-values",
                "--set-string",
                f"siliconBoutique.benchmarkStart={self.config.benchmark_start}",
                "--set-string",
                f"siliconBoutique.benchmarkEnd={self.config.benchmark_end}",
            ]
        )

    def extract_and_summarize(self) -> None:
        metrics_path = self.config.artifacts_dir / "prometheus-metrics.json"
        loadgenerator_logs_path = self.config.artifacts_dir / "loadgenerator.log"
        loadgenerator_stats_path = self.config.artifacts_dir / "loadgenerator-stats.json"
        summary_path = self.config.artifacts_dir / "benchmark-summary.json"
        summary_store_path = self.config.artifacts_dir / "benchmark-summaries.ndjson"
        report_path = self.config.artifacts_dir / "comparability-report.json"

        with self.port_forward_prometheus():
            self.runner.run(
                [
                    sys.executable,
                    "automation/scripts/extract_prometheus_metrics.py",
                    "--prometheus-url",
                    f"http://127.0.0.1:{self.config.prometheus_port}",
                    "--run-id",
                    self.config.run_id,
                    "--namespace",
                    self.config.namespace,
                    "--start",
                    self.config.benchmark_start,
                    "--end",
                    self.config.benchmark_end,
                    "--step",
                    "15s",
                    "--output",
                    str(metrics_path),
                    "--strict",
                ],
                cwd=REPO_ROOT,
            )
        logs = self.runner.run(
            [
                "kubectl",
                "logs",
                "deployment/loadgenerator",
                "--namespace",
                self.config.namespace,
                "--context",
                self.config.kube_context,
            ],
            capture=True,
        )
        loadgenerator_logs_path.write_text(logs.stdout, encoding="utf-8")
        self.runner.run(
            [
                sys.executable,
                "automation/scripts/extract_loadgenerator_stats.py",
                "--logs-input",
                str(loadgenerator_logs_path),
                "--output",
                str(loadgenerator_stats_path),
                "--run-id",
                self.config.run_id,
                "--strict",
            ],
            cwd=REPO_ROOT,
        )
        self.runner.run(
            [
                sys.executable,
                "automation/scripts/generate_benchmark_summary.py",
                "--metrics-input",
                str(metrics_path),
                "--loadgenerator-stats",
                str(loadgenerator_stats_path),
                "--summary-output",
                str(summary_path),
                "--summary-store",
                str(summary_store_path),
                "--environment",
                self.config.environment,
                "--machine-type",
                self.config.machine_type,
                "--processor-family",
                self.config.processor_family,
                "--architecture",
                self.config.architecture,
                "--cloud-provider",
                self.config.cloud_provider,
                "--region",
                self.config.region,
                "--zone",
                self.config.zone,
                "--node-count",
                str(self.config.node_count),
                "--pricing-model",
                self.config.pricing_model,
                "--concurrent-users",
                self.config.concurrent_users,
                "--users-per-second",
                self.config.users_per_second,
                "--load-profile-source",
                self.config.load_profile_source,
                "--strict",
            ],
            cwd=REPO_ROOT,
        )
        self.runner.run(
            [
                sys.executable,
                "automation/scripts/validate_benchmark_comparability.py",
                "--summary-store",
                str(summary_store_path),
                "--schema",
                "automation/templates/benchmark-summary.schema.json",
                "--report-output",
                str(report_path),
                "--run-id",
                self.config.run_id,
                "--mode",
                "summary",
                "--min-duration-seconds",
                str(self.config.min_duration_seconds),
                "--min-coverage-ratio",
                str(self.config.min_coverage_ratio),
                "--strict",
            ],
            cwd=REPO_ROOT,
        )

    @contextmanager
    def port_forward_prometheus(self):
        command = [
            "kubectl",
            "port-forward",
            "service/sb-monitoring-kube-prometh-prometheus",
            f"{self.config.prometheus_port}:9090",
            "--namespace",
            self.config.namespace,
            "--context",
            self.config.kube_context,
        ]
        process = self.popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            ready_url = f"http://127.0.0.1:{self.config.prometheus_port}/-/ready"
            ready = False
            for _ in range(30):
                result = self.runner.run(
                    ["curl", "-fsS", ready_url],
                    check=False,
                    capture=True,
                )
                if result.returncode == 0:
                    ready = True
                    break
                self.sleep(2)
            if not ready:
                raise LocalBenchmarkError("Prometheus port-forward did not become ready")
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    def cleanup(self) -> Exception | None:
        if self.config.skip_destroy:
            self.write_teardown_status(False, 0, "skipped")
            self.config.destroy_attempted = "false"
            self.config.destroy_succeeded = "skipped"
            return None

        self.capture_teardown_check("teardown-precheck.txt", "precheck")
        self.helm_cleanup()
        destroy_error = self.terraform_destroy()
        self.capture_teardown_check("teardown-postcheck.txt", "postcheck")
        return destroy_error

    def capture_teardown_check(self, filename: str, label: str) -> None:
        path = self.config.artifacts_dir / filename
        with path.open("w", encoding="utf-8") as handle:
            handle.write(f"teardown_{label}_started_at={utc_now()}\n")
            handle.write(f"run_id={self.config.run_id}\n")
            handle.write(f"namespace={self.config.namespace}\n\n")

        if not self.apply_attempted:
            append_text(path, "Terraform apply was not attempted; no local teardown check is required.\n")
            return
        if not self.config.namespace:
            append_text(path, "Namespace is unavailable; skipping Kubernetes teardown check.\n")
            return
        self.runner.run(
            [
                "kubectl",
                "get",
                "namespace",
                self.config.namespace,
                "--context",
                self.config.kube_context,
                "--show-labels",
            ],
            check=False,
            log_path=path,
            timeout="2m",
        )
        self.runner.run(
            [
                "kubectl",
                "get",
                "pods,services",
                "--namespace",
                self.config.namespace,
                "--context",
                self.config.kube_context,
            ],
            check=False,
            log_path=path,
            timeout="2m",
        )

    def helm_cleanup(self) -> None:
        path = self.config.artifacts_dir / "helm-cleanup.log"
        with path.open("w", encoding="utf-8") as handle:
            handle.write(f"helm_cleanup_started_at={utc_now()}\n")
            handle.write(f"namespace={self.config.namespace}\n\n")

        if not self.apply_attempted:
            append_text(path, "Terraform apply was not attempted; skipping Helm cleanup.\n")
            return
        if not self.config.namespace:
            append_text(path, "Namespace is unavailable; skipping Helm cleanup.\n")
            return
        for release in (self.config.monitoring_release, self.config.workload_release):
            self.runner.run(
                [
                    "helm",
                    "uninstall",
                    release,
                    "--namespace",
                    self.config.namespace,
                    "--kube-context",
                    self.config.kube_context,
                ],
                check=False,
                log_path=path,
                timeout="5m",
            )

    def terraform_destroy(self) -> Exception | None:
        path = self.config.artifacts_dir / "teardown-destroy.log"
        with path.open("w", encoding="utf-8") as handle:
            handle.write(f"destroy_started_at={utc_now()}\n")
            handle.write(f"run_id={self.config.run_id}\n")
            handle.write(f"namespace={self.config.namespace}\n\n")

        if not self.apply_attempted:
            append_text(path, "Terraform apply was not attempted; skipping destroy.\n")
            self.write_teardown_status(False, 0, "true")
            return None

        result = self.runner.run(
            [
                "terraform",
                "destroy",
                "-auto-approve",
                *self.terraform_vars(),
            ],
            cwd=self.config.terraform_dir,
            check=False,
            log_path=path,
            timeout="30m",
        )
        succeeded = result.returncode == 0
        self.write_teardown_status(True, result.returncode, bool_string(succeeded))
        if not succeeded:
            return LocalBenchmarkError("terraform destroy failed; inspect artifacts/teardown-destroy.log")
        return None

    def write_teardown_status(
        self, attempted: bool, exit_code: int, succeeded: str
    ) -> None:
        self.config.destroy_attempted = bool_string(attempted)
        self.config.destroy_succeeded = succeeded
        write_env_file(
            self.config.artifacts_dir / "teardown-status.env",
            {
                "destroy_attempted": self.config.destroy_attempted,
                "destroy_exit_code": str(exit_code),
                "destroy_succeeded": self.config.destroy_succeeded,
                "destroy_finished_at": utc_now(),
            },
        )

    def write_provision_status(
        self, values: dict[str, str], *, append: bool = False
    ) -> None:
        path = self.config.artifacts_dir / "provision-status.env"
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")

    def write_trace(self) -> None:
        artifacts_dir = self.config.artifacts_dir
        summary_path = artifacts_dir / "benchmark-summary.json"
        summary_store_path = artifacts_dir / "benchmark-summaries.ndjson"
        trace_path = artifacts_dir / "workflow-trace.json"
        trace = {
            "github": {},
            "benchmark": {
                "run_id": self.config.run_id,
                "environment": self.config.environment,
                "cloud_provider": self.config.cloud_provider,
                "namespace": self.config.namespace,
                "machine_type": self.config.machine_type,
                "processor_family": self.config.processor_family,
                "cpu_platform": self.config.cpu_platform,
                "architecture": self.config.architecture,
                "region": self.config.region,
                "zone": self.config.zone,
                "node_count": self.config.node_count,
                "pricing_model": self.config.pricing_model,
                "benchmark_start": self.config.benchmark_start,
                "benchmark_end": self.config.benchmark_end,
                "load_concurrent_users": self.config.concurrent_users,
                "load_users_per_second": self.config.users_per_second,
                "load_profile_source": self.config.load_profile_source,
            },
            "gcp": {
                "project_id": "",
                "region": self.config.region,
                "zone": self.config.zone,
            },
            "artifacts": {
                "artifact_name": self.config.summary_artifact_name,
                "summary_path": str(summary_path),
                "summary_store_path": str(summary_store_path),
                "loadgenerator_stats_path": str(artifacts_dir / "loadgenerator-stats.json"),
                "trace_path": str(trace_path),
                "summary_exists": bool_string(summary_path.exists()),
                "summary_store_exists": bool_string(summary_store_path.exists()),
                "loadgenerator_stats_exists": bool_string((artifacts_dir / "loadgenerator-stats.json").exists()),
            },
            "teardown": {
                "destroy_attempted": self.config.destroy_attempted,
                "destroy_succeeded": self.config.destroy_succeeded,
            },
            "inputs": {
                "failure_stage": self.config.failure_stage,
            },
        }
        write_json(trace_path, trace)
        write_env_file(
            artifacts_dir / "workflow-trace.env",
            {
                "run_id": self.config.run_id,
                "environment": self.config.environment,
                "cloud_provider": self.config.cloud_provider,
                "project_id": "",
                "region": self.config.region,
                "zone": self.config.zone,
                "machine_type": self.config.machine_type,
                "processor_family": self.config.processor_family,
                "cpu_platform": self.config.cpu_platform or "",
                "architecture": self.config.architecture,
                "node_count": str(self.config.node_count),
                "pricing_model": self.config.pricing_model,
                "namespace": self.config.namespace,
                "benchmark_start": self.config.benchmark_start,
                "benchmark_end": self.config.benchmark_end,
                "summary_artifact_name": self.config.summary_artifact_name,
                "summary_path": str(summary_path),
                "summary_store_path": str(summary_store_path),
                "loadgenerator_stats_path": str(artifacts_dir / "loadgenerator-stats.json"),
                "trace_path": str(trace_path),
                "teardown_succeeded": self.config.destroy_succeeded,
                "destroy_attempted": self.config.destroy_attempted,
                "failure_stage": self.config.failure_stage,
            },
        )

    def fail_if_requested(self, stage: str) -> None:
        if self.config.failure_stage == stage:
            raise LocalBenchmarkError(
                f"Controlled failure requested with failure_stage={stage}."
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the SiliconBoutique benchmark flow against local Kubernetes."
    )
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--terraform-dir", type=Path, default=Path("infra/terraform/local-kubernetes")
    )
    parser.add_argument(
        "--workload-chart",
        type=Path,
        default=Path("k8s/charts/silicon-boutique-online-boutique"),
    )
    parser.add_argument(
        "--monitoring-chart",
        type=Path,
        default=Path("k8s/charts/silicon-boutique-monitoring"),
    )
    parser.add_argument(
        "--workload-release", default="silicon-boutique-online-boutique"
    )
    parser.add_argument("--monitoring-release", default="sb-monitoring")
    parser.add_argument("--machine-type", default="local")
    parser.add_argument("--processor-family", default="local")
    parser.add_argument("--cpu-platform", default=None)
    parser.add_argument("--architecture", choices=("x86_64", "arm64"), default="x86_64")
    parser.add_argument("--region", default="local")
    parser.add_argument("--zone", default="local")
    parser.add_argument("--node-count", type=int, default=1)
    parser.add_argument("--concurrent-users", default="10")
    parser.add_argument("--users-per-second", default="1")
    parser.add_argument("--test-duration", default="20m")
    parser.add_argument("--pricing-model", choices=("local", "spot", "on_demand"), default="local")
    parser.add_argument(
        "--load-profile-file",
        type=Path,
        help="Use load_concurrent_users and load_users_per_second from a calibration JSON file.",
    )
    parser.add_argument("--prometheus-port", type=int, default=9090)
    parser.add_argument("--min-duration-seconds", type=int, default=1200)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    parser.add_argument(
        "--failure-stage",
        choices=("none", "after_provision", "after_monitoring_ready", "before_extract"),
        default="none",
    )
    parser.add_argument(
        "--skip-destroy",
        action="store_true",
        help="Leave the Terraform-owned namespace in place for debugging.",
    )
    args = parser.parse_args(argv)
    validate_args(args, parser)
    return args


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not RUN_ID_PATTERN.match(args.run_id) or len(args.run_id) > 46:
        parser.error("--run-id must be lowercase DNS-safe and at most 46 characters")
    if args.node_count < 1:
        parser.error("--node-count must be at least 1")
    if args.prometheus_port < 1 or args.prometheus_port > 65535:
        parser.error("--prometheus-port must be between 1 and 65535")
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if not 0 <= args.min_coverage_ratio <= 1:
        parser.error("--min-coverage-ratio must be between 0 and 1")
    try:
        parse_duration_seconds(args.test_duration)
    except ValueError as exc:
        parser.error(str(exc))


def config_from_args(args: argparse.Namespace) -> BenchmarkConfig:
    load_profile = load_profile_from_file(args.load_profile_file)
    concurrent_users = str(
        load_profile.get("load_concurrent_users", args.concurrent_users)
    )
    users_per_second = str(
        load_profile.get("load_users_per_second", args.users_per_second)
    )
    load_profile_source = (
        str(load_profile.get("load_profile_source") or args.load_profile_file)
        if args.load_profile_file
        else "manual"
    )
    return BenchmarkConfig(
        run_id=args.run_id,
        artifacts_dir=args.artifacts_dir,
        terraform_dir=args.terraform_dir,
        workload_chart=args.workload_chart,
        monitoring_chart=args.monitoring_chart,
        workload_release=args.workload_release,
        monitoring_release=args.monitoring_release,
        machine_type=args.machine_type,
        processor_family=args.processor_family,
        cpu_platform=args.cpu_platform,
        architecture=args.architecture,
        region=args.region,
        zone=args.zone,
        node_count=args.node_count,
        concurrent_users=concurrent_users,
        users_per_second=users_per_second,
        test_duration=args.test_duration,
        test_duration_seconds=parse_duration_seconds(args.test_duration),
        pricing_model=args.pricing_model,
        load_profile_source=load_profile_source,
        prometheus_port=args.prometheus_port,
        min_duration_seconds=args.min_duration_seconds,
        min_coverage_ratio=args.min_coverage_ratio,
        failure_stage=args.failure_stage,
        skip_destroy=args.skip_destroy,
    )


def load_profile_from_file(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "selected_profile" in payload and isinstance(payload["selected_profile"], dict):
        payload = payload["selected_profile"]
    return payload if isinstance(payload, dict) else {}


def parse_duration_seconds(value: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", value):
        return int(value)
    match = re.fullmatch(r"([1-9][0-9]*)([smh])", value)
    if not match:
        raise ValueError("test_duration must be a positive number of seconds, Ns, Nm, or Nh")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return amount
    if unit == "m":
        return amount * 60
    return amount * 3600


def default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("local-%Y%m%d%H%M%S")


def output_value(outputs: dict[str, Any], name: str, default: Any) -> Any:
    value = outputs.get(name)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def append_log(
    path: Path, command: Iterable[str], stdout: str, stderr: str, returncode: int
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {shell_join(command)}\n")
        if stdout:
            handle.write(stdout)
            if not stdout.endswith("\n"):
                handle.write("\n")
        if stderr:
            handle.write(stderr)
            if not stderr.endswith("\n"):
                handle.write("\n")
        handle.write(f"exit_code={returncode}\n\n")


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def summarize_command_failure(result: CommandResult) -> str:
    output = (result.stderr or result.stdout).strip()
    if not output:
        return ""
    output = re.sub(r"\s+", " ", output)
    if len(output) > 500:
        return output[:497] + "..."
    return output


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_offset(*, seconds: int) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(seconds=seconds))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def bool_string(value: bool) -> str:
    return "true" if value else "false"


def shell_join(command: Iterable[str]) -> str:
    return " ".join(shell_quote(part) for part in command)


def shell_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    benchmark = LocalBenchmark(config_from_args(args))
    return benchmark.run()


if __name__ == "__main__":
    raise SystemExit(main())
