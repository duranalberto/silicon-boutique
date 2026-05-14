"""Unified SiliconBoutique benchmark workflow orchestration."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .command import CommandResult, Runner, SubprocessRunner, command_for_report, preview_text, shell_join
from .env import BigQuerySettings, env_presence, read_env_file, resolve_bigquery_settings
from .github_actions import GitHubActionsError, GitHubRun, GitHubWorkflowClient, normalize_downloaded_artifact_dir
from .reporting import read_json, teardown_status_from_artifacts, utc_now, write_json


RUN_ID_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
REPO_ROOT = Path(__file__).resolve().parents[3]


class UnifiedWorkflowError(RuntimeError):
    """Error raised for unified workflow failures."""
    def __init__(
        self,
        message: str,
        *,
        step: str,
        result: CommandResult | None = None,
    ) -> None:
        """Initialize the object with the provided configuration.


        Args:
            message: message (str) used by this operation.
            step: step (str) used by this operation.
            result: result (CommandResult | None) used by this operation.

        Returns:
            None.
        """
        super().__init__(message)
        self.step = step
        self.result = result


@dataclass(frozen=True)
class ProviderInputs:
    """Container for provider Inputs state and behavior.


    Attributes:
        project_id: project ID (str) stored on the object.
        region: region (str) stored on the object.
        zone: zone (str) stored on the object.
        secondary_zone: secondary zone (str) stored on the object.
        machine_type: machine type (str) stored on the object.
        processor_family: processor family (str) stored on the object.
        cpu_platform: CPU platform (str) stored on the object.
        architecture: architecture (str) stored on the object.
        pricing_model: pricing model (str) stored on the object.
        node_count: node count (int) stored on the object.
        concurrent_users: concurrent users (int) stored on the object.
        users_per_second: users per second (int) stored on the object.
        test_duration: test duration (str) stored on the object.
    """
    project_id: str
    region: str
    zone: str
    secondary_zone: str
    machine_type: str
    processor_family: str
    cpu_platform: str
    architecture: str
    pricing_model: str
    node_count: int
    concurrent_users: int
    users_per_second: int
    test_duration: str


@dataclass(frozen=True)
class UnifiedWorkflowConfig:
    """Container for unified Workflow Config state and behavior.


    Attributes:
        target: target (str) stored on the object.
        profile: profile (str) stored on the object.
        run_id: run ID (str) stored on the object.
        artifacts_root: artifacts root (Path) stored on the object.
        report_dir: report dir (Path) stored on the object.
        credential_env_file: credential environment file (Path) stored on the object.
        dashboard: dashboard (str) stored on the object.
        no_wait: no wait (bool) stored on the object.
        github_ref: GitHub ref (str) stored on the object.
        workflow_timeout_seconds: workflow timeout seconds (int) stored on the object.
        poll_interval_seconds: poll interval seconds (int) stored on the object.
        test_duration: test duration (str) stored on the object.
        min_duration_seconds: min duration seconds (int) stored on the object.
        min_coverage_ratio: min coverage ratio (float) stored on the object.
        bigquery: BigQuery (BigQuerySettings) stored on the object.
        env_values: environment values (dict[str, str]) stored on the object.
        env_presence: environment presence (dict[str, bool]) stored on the object.
        local_inputs: local inputs (ProviderInputs | None) stored on the object.
        gcp_inputs: GCP inputs (ProviderInputs | None) stored on the object.
        aws_inputs: AWS inputs (ProviderInputs | None) stored on the object.
    """
    target: str
    profile: str
    run_id: str
    artifacts_root: Path
    report_dir: Path
    credential_env_file: Path
    dashboard: str
    no_wait: bool
    github_ref: str
    workflow_timeout_seconds: int
    poll_interval_seconds: int
    test_duration: str
    min_duration_seconds: int
    min_coverage_ratio: float
    bigquery: BigQuerySettings
    env_values: dict[str, str] = field(default_factory=dict)
    env_presence: dict[str, bool] = field(default_factory=dict)
    local_inputs: ProviderInputs | None = None
    gcp_inputs: ProviderInputs | None = None
    aws_inputs: ProviderInputs | None = None


class UnifiedBenchmarkWorkflow:
    """Container for unified Benchmark Workflow state and behavior.
    """
    def __init__(
        self,
        config: UnifiedWorkflowConfig,
        *,
        runner: Runner | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        """Initialize the object with the provided configuration.


        Args:
            config: config (UnifiedWorkflowConfig) used by this operation.
            runner: runner (Runner | None) used by this operation.
            environ: environ (dict[str, str] | None) used by this operation.

        Returns:
            None.
        """
        self.config = config
        self.runner = runner or SubprocessRunner()
        self.environ = dict(os.environ if environ is None else environ)
        self.report_path = config.report_dir / "workflow-report.json"
        self.steps: list[dict[str, Any]] = []
        self.provider_results: dict[str, dict[str, Any]] = {}
        self.dashboard_outputs: dict[str, Any] | None = None
        self.acceptance_matrix: dict[str, Any] | None = None

    def run(self) -> int:
        """Run the configured operation.


        Returns:
            int value produced by run.
        """
        self.config.report_dir.mkdir(parents=True, exist_ok=True)
        self.write_report("running")
        try:
            selected = selected_targets(self.config.target)
            if any(target in {"gcp", "aws"} for target in selected):
                self.require_bigquery("cloud benchmark dispatch")
            if "local" in selected:
                self.provider_results["local"] = self.run_local()
            if "gcp" in selected:
                self.provider_results["gcp"] = self.run_cloud("gcp")
            if "aws" in selected:
                self.provider_results["aws"] = self.run_cloud("aws")
            if self.config.target == "all" and not self.config.no_wait:
                self.acceptance_matrix = self.run_acceptance_matrix()
            if self.config.dashboard == "generate" and not self.config.no_wait:
                self.dashboard_outputs = self.generate_dashboard()
            status = "dispatched" if self.config.no_wait and any(t in {"gcp", "aws"} for t in selected) else "passed"
            self.write_report(status)
            return 0
        except UnifiedWorkflowError as exc:
            self.write_report("failed", error=error_payload(exc))
            print(str(exc), file=sys.stderr)
            return 2
        except GitHubActionsError as exc:
            self.write_report("failed", error=error_payload(exc))
            print(str(exc), file=sys.stderr)
            return 2

    def run_local(self) -> dict[str, Any]:
        """Run local.


        Returns:
            dict[str, Any] value produced by run local.
        """
        run_id = self.config.run_id
        local_root = self.config.report_dir / "local"
        artifacts_dir = local_root / run_id
        if self.config.bigquery.configured:
            command = [
                sys.executable,
                "automation/scripts/run_local_benchmark_workflow.py",
                "--run-id",
                run_id,
                "--credential-env-file",
                str(self.config.credential_env_file),
                "--artifacts-root",
                str(local_root),
            ]
            if self.config.profile == "full":
                command.append("--full-duration")
            else:
                command.extend(
                    [
                        "--test-duration",
                        self.config.test_duration,
                        "--min-duration-seconds",
                        str(self.config.min_duration_seconds),
                    ]
                )
            for extra in local_extra_args(self.config.local_inputs):
                command.append(f"--extra-run-local-arg={extra}")
        else:
            command = [
                sys.executable,
                "automation/scripts/run_local_benchmark.py",
                "--run-id",
                run_id,
                "--artifacts-dir",
                str(artifacts_dir),
            ]
            if self.config.profile == "smoke":
                command.extend(
                    [
                        "--test-duration",
                        self.config.test_duration,
                        "--min-duration-seconds",
                        str(self.config.min_duration_seconds),
                    ]
                )
            command.extend(local_extra_args(self.config.local_inputs))
        self.run_step("local-workflow", command)
        report_path = artifacts_dir / "local-workflow-report.json"
        local_report = read_json(report_path) if report_path.exists() else None
        return {
            "run_id": run_id,
            "artifacts_dir": str(artifacts_dir),
            "workflow_report": str(report_path) if report_path.exists() else None,
            "bigquery_validation": local_report.get("bigquery") if isinstance(local_report, dict) else None,
            "teardown_status": teardown_status_from_artifacts(artifacts_dir),
        }

    def run_cloud(self, provider: str) -> dict[str, Any]:
        """Run cloud.


        Args:
            provider: provider (str) used by this operation.

        Returns:
            dict[str, Any] value produced by run cloud.
        """
        workflow_file = "benchmark.yml" if provider == "gcp" else "benchmark-aws.yml"
        provider_dir = self.config.report_dir / provider
        provider_dir.mkdir(parents=True, exist_ok=True)
        client = GitHubWorkflowClient(
            runner=self.runner,
            repo_root=REPO_ROOT,
            github_ref=self.config.github_ref,
        )
        self.steps.extend(client.preflight(workflow_file))
        run, dispatch_steps = client.dispatch(
            workflow_file=workflow_file,
            inputs=cloud_workflow_inputs(provider, self.config),
        )
        self.steps.extend(dispatch_steps)
        result: dict[str, Any] = cloud_run_payload(run, provider=provider)
        if self.config.no_wait:
            result["status"] = "dispatched"
            return result

        completed = client.wait_for_completion(
            run,
            timeout_seconds=self.config.workflow_timeout_seconds,
            poll_interval_seconds=self.config.poll_interval_seconds,
        )
        result.update(cloud_run_payload(completed, provider=provider))
        download = client.download_artifact(completed, provider_dir)
        self.steps.append(download)
        artifacts_dir = normalize_downloaded_artifact_dir(provider_dir)
        result.update(
            {
                "status": "completed",
                "artifacts_dir": str(artifacts_dir),
                "bigquery_load_report": str(artifacts_dir / "bigquery-load-report.json"),
                "teardown_status": teardown_status_from_artifacts(artifacts_dir),
            }
        )
        result["verification"] = self.verify_cloud_artifacts(provider, artifacts_dir)
        return result

    def verify_cloud_artifacts(self, provider: str, artifacts_dir: Path) -> dict[str, Any]:
        """Compute verify cloud artifacts.


        Args:
            provider: provider (str) used by this operation.
            artifacts_dir: artifacts dir (Path) used by this operation.

        Returns:
            dict[str, Any] value produced by verify cloud artifacts.
        """
        output_dir = self.config.report_dir / f"{provider}-verification"
        command = [
            sys.executable,
            "automation/scripts/run_acceptance_matrix.py",
            "--mode",
            "verify",
            "--artifacts-dir",
            str(output_dir),
            f"--{provider}-artifacts",
            str(artifacts_dir),
            "--min-duration-seconds",
            str(self.config.min_duration_seconds),
            "--min-coverage-ratio",
            str(self.config.min_coverage_ratio),
        ]
        self.run_step(f"{provider}-artifact-verification", command)
        report_path = output_dir / "acceptance-matrix-report.json"
        report = read_json(report_path) if report_path.exists() else {}
        return {
            "report": str(report_path),
            "status": report.get("status"),
        }

    def run_acceptance_matrix(self) -> dict[str, Any]:
        """Run acceptance matrix.


        Returns:
            dict[str, Any] value produced by run acceptance matrix.
        """
        output_dir = self.config.report_dir / "acceptance-matrix"
        command = [
            sys.executable,
            "automation/scripts/run_acceptance_matrix.py",
            "--mode",
            "verify",
            "--artifacts-dir",
            str(output_dir),
            "--min-duration-seconds",
            str(self.config.min_duration_seconds),
            "--min-coverage-ratio",
            str(self.config.min_coverage_ratio),
        ]
        local = self.provider_results.get("local", {}).get("artifacts_dir")
        gcp = self.provider_results.get("gcp", {}).get("artifacts_dir")
        aws = self.provider_results.get("aws", {}).get("artifacts_dir")
        if local:
            command.extend(["--local-artifacts", str(local)])
        if gcp:
            command.extend(["--gcp-artifacts", str(gcp)])
        if aws:
            command.extend(["--aws-artifacts", str(aws)])
        self.run_step("acceptance-matrix", command)
        report_path = output_dir / "acceptance-matrix-report.json"
        report = read_json(report_path) if report_path.exists() else {}
        return {
            "report": str(report_path),
            "status": report.get("status"),
            "comparison_report": str(output_dir / "acceptance-matrix-comparison.json"),
        }

    def generate_dashboard(self) -> dict[str, Any]:
        """Compute generate dashboard.


        Returns:
            dict[str, Any] value produced by generate dashboard.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        output_dir = self.config.report_dir / "dashboard"
        command = [
            sys.executable,
            "automation/scripts/launch_metrics_dashboard.py",
            "--output-dir",
            str(output_dir),
            "--no-serve",
            "--no-browser",
            "--min-duration-seconds",
            str(self.config.min_duration_seconds),
            "--min-coverage-ratio",
            str(self.config.min_coverage_ratio),
        ]
        selected = selected_targets(self.config.target)
        if any(target in {"gcp", "aws"} for target in selected):
            self.require_bigquery("cloud dashboard generation")
            command.extend(
                [
                    "--project-id",
                    self.config.bigquery.project_id,
                    "--dataset-id",
                    self.config.bigquery.dataset,
                    "--table-id",
                    self.config.bigquery.table,
                    "--location",
                    self.config.bigquery.location,
                ]
            )
        else:
            local_artifacts = self.provider_results.get("local", {}).get("artifacts_dir")
            if not local_artifacts:
                raise UnifiedWorkflowError("Local dashboard generation requires local artifacts.", step="dashboard")
            command.extend(["--summary-store", str(Path(local_artifacts) / "benchmark-summaries.ndjson")])
        self.run_step("dashboard-generate", command)
        return {
            "output_dir": str(output_dir),
            "index_html": str(output_dir / "index.html"),
            "dashboard_data": str(output_dir / "dashboard-data.json"),
        }

    def require_bigquery(self, reason: str) -> None:
        """Compute require bigquery.


        Args:
            reason: reason (str) used by this operation.

        Returns:
            None.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        if not self.config.bigquery.configured:
            missing = ", ".join(self.config.bigquery.missing_fields())
            raise UnifiedWorkflowError(
                f"BigQuery settings are required for {reason}: {missing}.",
                step="bigquery-config",
            )

    def run_step(self, step: str, command: list[str]) -> CommandResult:
        """Run step.


        Args:
            step: step (str) used by this operation.
            command: command (list[str]) used by this operation.

        Returns:
            CommandResult value produced by run step.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        result = self.runner.run(command, cwd=REPO_ROOT, env=self.environ)
        record = {
            "step": step,
            "command": command_for_report(command),
            "exit_code": result.returncode,
            "stdout_preview": preview_text(result.stdout),
            "stderr_preview": preview_text(result.stderr),
        }
        self.steps.append(record)
        if result.returncode != 0:
            raise UnifiedWorkflowError(
                f"{step} failed with exit {result.returncode}: {shell_join(command)}",
                step=step,
                result=result,
            )
        return result

    def write_report(self, status: str, *, error: dict[str, Any] | None = None) -> None:
        """Write report.


        Args:
            status: status (str) used by this operation.
            error: error (dict[str, Any] | None) used by this operation.

        Returns:
            None.
        """
        payload = {
            "status": status,
            "run_id": self.config.run_id,
            "selected_targets": selected_targets(self.config.target),
            "profile": self.config.profile,
            "provider_inputs": provider_inputs_payload(self.config),
            "artifacts_root": str(self.config.artifacts_root),
            "report_dir": str(self.config.report_dir),
            "workflow_report": str(self.report_path),
            "bigquery": {
                "configured": self.config.bigquery.configured,
                "project_id": self.config.bigquery.project_id,
                "dataset": self.config.bigquery.dataset,
                "table": self.config.bigquery.table,
                "location": self.config.bigquery.location,
            },
            "env_presence": self.config.env_presence,
            "provider_results": self.provider_results,
            "dashboard": self.dashboard_outputs,
            "acceptance_matrix": self.acceptance_matrix,
            "steps": self.steps,
            "error": error,
            "written_at": utc_now(),
        }
        write_json(self.report_path, payload)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments.


    Args:
        argv: argv (list[str] | None) used by this operation.

    Returns:
        argparse.Namespace value produced by parse arguments.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    parser = argparse.ArgumentParser(
        description="Run the unified SiliconBoutique benchmark workflow."
    )
    parser.add_argument("--target", choices=("local", "gcp", "aws", "all"), default="local")
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--run-id")
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts/unified-workflow"))
    parser.add_argument("--bigquery-env-file", type=Path, default=Path("credential.env"))
    parser.add_argument("--bigquery-project-id")
    parser.add_argument("--bigquery-dataset")
    parser.add_argument("--bigquery-table")
    parser.add_argument("--bigquery-location")
    parser.add_argument("--project-id")
    parser.add_argument("--region")
    parser.add_argument("--zone")
    parser.add_argument("--secondary-zone", default="us-east-1b")
    parser.add_argument("--machine-type")
    parser.add_argument("--processor-family")
    parser.add_argument("--cpu-platform", default="")
    parser.add_argument("--architecture", choices=("x86_64", "arm64"), default="x86_64")
    parser.add_argument("--pricing-model", choices=("local", "spot", "on_demand"))
    parser.add_argument("--node-count", type=int, default=1)
    parser.add_argument("--concurrent-users", type=int, default=10)
    parser.add_argument("--users-per-second", type=int, default=1)
    parser.add_argument("--test-duration", default="2m")
    parser.add_argument("--min-duration-seconds", type=int, default=60)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    parser.add_argument("--dashboard", choices=("generate", "skip"), default="generate")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--github-ref", default="main")
    parser.add_argument("--workflow-timeout-seconds", type=int, default=7200)
    parser.add_argument("--poll-interval-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    validate_args(args, parser)
    return args


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Validate arguments.


    Args:
        args: arguments (argparse.Namespace) used by this operation.
        parser: parser (argparse.ArgumentParser) used by this operation.

    Returns:
        None.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    if args.run_id is not None and (
        not RUN_ID_PATTERN.match(args.run_id) or len(args.run_id) > 46
    ):
        parser.error("--run-id must be lowercase DNS-safe and at most 46 characters")
    if args.node_count < 1:
        parser.error("--node-count must be at least 1")
    if args.concurrent_users < 1:
        parser.error("--concurrent-users must be at least 1")
    if args.users_per_second < 1:
        parser.error("--users-per-second must be at least 1")
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if not 0 <= args.min_coverage_ratio <= 1:
        parser.error("--min-coverage-ratio must be between 0 and 1")
    if args.workflow_timeout_seconds < 1:
        parser.error("--workflow-timeout-seconds must be at least 1")
    if args.poll_interval_seconds < 1:
        parser.error("--poll-interval-seconds must be at least 1")
    try:
        parse_duration_seconds(args.test_duration)
    except ValueError as exc:
        parser.error(str(exc))
    if args.target == "local" and args.pricing_model not in (None, "local"):
        parser.error("--pricing-model must be local for --target local")


def config_from_args(
    args: argparse.Namespace,
    *,
    environ: dict[str, str] | None = None,
) -> UnifiedWorkflowConfig:
    """Compute config from arguments.


    Args:
        args: arguments (argparse.Namespace) used by this operation.
        environ: environ (dict[str, str] | None) used by this operation.

    Returns:
        UnifiedWorkflowConfig value produced by config from arguments.
    """
    env = dict(os.environ if environ is None else environ)
    env_values = read_env_file(args.bigquery_env_file)
    for key, value in env_values.items():
        env.setdefault(key, value)
    bigquery = resolve_bigquery_settings(
        env_values=env_values,
        environ=env,
        project_id_override=args.bigquery_project_id,
        dataset_override=args.bigquery_dataset,
        table_override=args.bigquery_table,
        location_override=args.bigquery_location,
    )
    run_id = args.run_id or default_run_id(args.target)
    report_dir = args.artifacts_root / run_id
    return UnifiedWorkflowConfig(
        target=args.target,
        profile=args.profile,
        run_id=run_id,
        artifacts_root=args.artifacts_root,
        report_dir=report_dir,
        credential_env_file=args.bigquery_env_file,
        dashboard=args.dashboard,
        no_wait=args.no_wait,
        github_ref=args.github_ref,
        workflow_timeout_seconds=args.workflow_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        test_duration=args.test_duration,
        min_duration_seconds=args.min_duration_seconds,
        min_coverage_ratio=args.min_coverage_ratio,
        bigquery=bigquery,
        env_values=env_values,
        env_presence=env_presence(env_values, env),
        local_inputs=provider_inputs("local", args, bigquery),
        gcp_inputs=provider_inputs("gcp", args, bigquery),
        aws_inputs=provider_inputs("aws", args, bigquery),
    )


def provider_inputs(
    provider: str,
    args: argparse.Namespace,
    bigquery: BigQuerySettings,
) -> ProviderInputs:
    """Compute provider inputs.


    Args:
        provider: provider (str) used by this operation.
        args: arguments (argparse.Namespace) used by this operation.
        bigquery: BigQuery (BigQuerySettings) used by this operation.

    Returns:
        ProviderInputs value produced by provider inputs.
    """
    defaults = {
        "local": {
            "project_id": "",
            "region": "local",
            "zone": "local",
            "secondary_zone": "",
            "machine_type": "local",
            "processor_family": "local",
            "pricing_model": "local",
        },
        "gcp": {
            "project_id": args.project_id or bigquery.project_id,
            "region": "us-central1",
            "zone": "us-central1-a",
            "secondary_zone": "",
            "machine_type": "e2-standard-4",
            "processor_family": "e2",
            "pricing_model": "spot",
        },
        "aws": {
            "project_id": bigquery.project_id,
            "region": "us-east-1",
            "zone": "us-east-1a",
            "secondary_zone": args.secondary_zone,
            "machine_type": "m7i.xlarge",
            "processor_family": "m7i",
            "pricing_model": "spot",
        },
    }[provider]
    return ProviderInputs(
        project_id=defaults["project_id"],
        region=args.region or defaults["region"],
        zone=args.zone or defaults["zone"],
        secondary_zone=args.secondary_zone if provider == "aws" else defaults["secondary_zone"],
        machine_type=args.machine_type or defaults["machine_type"],
        processor_family=args.processor_family or defaults["processor_family"],
        cpu_platform=args.cpu_platform or "",
        architecture=args.architecture,
        pricing_model=args.pricing_model or defaults["pricing_model"],
        node_count=args.node_count,
        concurrent_users=args.concurrent_users,
        users_per_second=args.users_per_second,
        test_duration=args.test_duration,
    )


def cloud_workflow_inputs(provider: str, config: UnifiedWorkflowConfig) -> dict[str, Any]:
    """Compute cloud workflow inputs.


    Args:
        provider: provider (str) used by this operation.
        config: config (UnifiedWorkflowConfig) used by this operation.

    Returns:
        dict[str, Any] value produced by cloud workflow inputs.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    inputs = config.gcp_inputs if provider == "gcp" else config.aws_inputs
    if inputs is None:
        raise UnifiedWorkflowError(f"Missing provider inputs for {provider}.", step=f"{provider}-inputs")
    common = {
        "region": inputs.region,
        "zone": inputs.zone,
        "machine_type": inputs.machine_type,
        "node_count": inputs.node_count,
        "processor_family": inputs.processor_family,
        "cpu_platform": inputs.cpu_platform,
        "architecture": inputs.architecture,
        "concurrent_users": inputs.concurrent_users,
        "users_per_second": inputs.users_per_second,
        "load_profile_source": "manual",
        "pricing_model": inputs.pricing_model,
        "test_duration": config.test_duration if config.profile == "smoke" else "20m",
        "failure_stage": "none",
        "acceptance_demo": True,
    }
    if provider == "gcp":
        return {
            "project_id": inputs.project_id,
            **common,
            "bigquery_dataset": config.bigquery.dataset,
            "bigquery_table": config.bigquery.table,
            "bigquery_location": config.bigquery.location,
        }
    return {
        **common,
        "secondary_zone": inputs.secondary_zone,
        "bigquery_project_id": config.bigquery.project_id,
        "bigquery_dataset": config.bigquery.dataset,
        "bigquery_table": config.bigquery.table,
        "bigquery_location": config.bigquery.location,
    }


def local_extra_args(inputs: ProviderInputs | None) -> list[str]:
    """Compute local extra arguments.


    Args:
        inputs: inputs (ProviderInputs | None) used by this operation.

    Returns:
        list[str] value produced by local extra arguments.
    """
    if inputs is None:
        return []
    return [
        "--machine-type",
        inputs.machine_type,
        "--processor-family",
        inputs.processor_family,
        "--architecture",
        inputs.architecture,
        "--region",
        inputs.region,
        "--zone",
        inputs.zone,
        "--node-count",
        str(inputs.node_count),
        "--concurrent-users",
        str(inputs.concurrent_users),
        "--users-per-second",
        str(inputs.users_per_second),
        "--pricing-model",
        inputs.pricing_model,
    ]


def selected_targets(target: str) -> list[str]:
    """Compute selected targets.


    Args:
        target: target (str) used by this operation.

    Returns:
        list[str] value produced by selected targets.
    """
    return ["local", "gcp", "aws"] if target == "all" else [target]


def provider_inputs_payload(config: UnifiedWorkflowConfig) -> dict[str, Any]:
    """Compute provider inputs payload.


    Args:
        config: config (UnifiedWorkflowConfig) used by this operation.

    Returns:
        dict[str, Any] value produced by provider inputs payload.
    """
    return {
        "local": dataclass_payload(config.local_inputs),
        "gcp": dataclass_payload(config.gcp_inputs),
        "aws": dataclass_payload(config.aws_inputs),
    }


def dataclass_payload(value: ProviderInputs | None) -> dict[str, Any] | None:
    """Compute dataclass payload.


    Args:
        value: value (ProviderInputs | None) used by this operation.

    Returns:
        dict[str, Any] | None value produced by dataclass payload.
    """
    if value is None:
        return None
    return {
        "project_id": value.project_id,
        "region": value.region,
        "zone": value.zone,
        "secondary_zone": value.secondary_zone,
        "machine_type": value.machine_type,
        "processor_family": value.processor_family,
        "cpu_platform": value.cpu_platform,
        "architecture": value.architecture,
        "pricing_model": value.pricing_model,
        "node_count": value.node_count,
        "concurrent_users": value.concurrent_users,
        "users_per_second": value.users_per_second,
        "test_duration": value.test_duration,
    }


def cloud_run_payload(run: GitHubRun, *, provider: str) -> dict[str, Any]:
    """Compute cloud run payload.


    Args:
        run: run (GitHubRun) used by this operation.
        provider: provider (str) used by this operation.

    Returns:
        dict[str, Any] value produced by cloud run payload.
    """
    return {
        "provider": provider,
        "run_id": run.run_id,
        "github_workflow_run_id": run.workflow_run_id,
        "github_workflow_url": run.url,
        "workflow_file": run.workflow_file,
        "github_status": run.status,
        "github_conclusion": run.conclusion,
        "artifact_name": run.artifact_name,
    }


def error_payload(exc: UnifiedWorkflowError | GitHubActionsError) -> dict[str, Any]:
    """Compute error payload.


    Args:
        exc: exc (UnifiedWorkflowError | GitHubActionsError) used by this operation.

    Returns:
        dict[str, Any] value produced by error payload.
    """
    result = getattr(exc, "result", None)
    return {
        "failed_step": getattr(exc, "step", "unknown"),
        "message": str(exc),
        "exit_code": result.returncode if result else None,
        "stdout_preview": preview_text(result.stdout if result else ""),
        "stderr_preview": preview_text(result.stderr if result else ""),
    }


def parse_duration_seconds(value: str) -> int:
    """Parse duration seconds.


    Args:
        value: value (str) used by this operation.

    Returns:
        int value produced by parse duration seconds.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    match = re.fullmatch(r"([1-9][0-9]*)(?:([smh]))?", value)
    if not match:
        raise ValueError("duration must be a positive number of seconds, Ns, Nm, or Nh")
    amount = int(match.group(1))
    unit = match.group(2) or "s"
    return amount * {"s": 1, "m": 60, "h": 3600}[unit]


def default_run_id(target: str = "unified") -> str:
    """Compute default run ID.


    Returns:
        str value produced by default run ID.
    """
    if target == "local":
        return datetime.now(timezone.utc).strftime("local-smoke-%Y%m%d-%H%M%S")
    return datetime.now(timezone.utc).strftime("unified-%Y%m%d-%H%M%S")


def main(argv: list[str] | None = None) -> int:
    """Run the command-line entrypoint.


    Args:
        argv: argv (list[str] | None) used by this operation.

    Returns:
        Process exit code for the command.
    """
    args = parse_args(argv)
    config = config_from_args(args)
    return UnifiedBenchmarkWorkflow(config).run()
