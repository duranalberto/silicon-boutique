#!/usr/bin/env python3
"""One-command local benchmark workflow with BigQuery proof and debug logs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from silicon_boutique_shared.automation import (  # noqa: E402
    CommandResult,
    shell_join,
    utc_now,
    write_json,
)

from automation.scripts import run_local_benchmark  # noqa: E402


RUN_ID_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
SECRET_KEY_PATTERN = re.compile(
    r"(credential|key|token|secret|password|provider|service_account)", re.I
)
PREVIEW_LIMIT = 800


class LocalWorkflowError(RuntimeError):
    """Raised when the one-command local workflow cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        step: str,
        exit_code: int | None = None,
        result: CommandResult | None = None,
        suggestion: str = "",
    ) -> None:
        super().__init__(message)
        self.step = step
        self.exit_code = exit_code
        self.result = result
        self.suggestion = suggestion


@dataclass(frozen=True)
class WorkflowConfig:
    run_id: str
    credential_env_file: Path
    artifacts_root: Path
    artifacts_dir: Path
    test_duration: str
    min_duration_seconds: int
    skip_minikube_repair: bool
    full_duration: bool
    extra_run_local_args: tuple[str, ...]
    bigquery_project_id: str
    bigquery_dataset: str
    bigquery_table: str
    bigquery_location: str
    env_presence: dict[str, bool]


class CommandRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return CommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")


class LocalBenchmarkWorkflow:
    def __init__(
        self,
        config: WorkflowConfig,
        *,
        runner: CommandRunner | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.runner = runner or CommandRunner()
        self.environ = dict(os.environ if environ is None else environ)
        self.commands_dir = config.artifacts_dir / "commands"
        self.workflow_log = config.artifacts_dir / "workflow.log"
        self.report_path = config.artifacts_dir / "local-workflow-report.json"
        self.issue_path = config.artifacts_dir / "issue-report.json"
        self.steps: list[dict[str, Any]] = []

    def run(self) -> int:
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.commands_dir.mkdir(parents=True, exist_ok=True)
        self.write_report("running")
        try:
            self.log_env_presence()
            self.run_step("verify-toolchain", [".devcontainer/verify-toolchain.sh"])
            self.ensure_kubernetes_ready()
            self.preflight_bigquery()
            self.run_local_benchmark()
            row = self.validate_bigquery_row()
            self.write_report("validated", bigquery_row=row)
        except LocalWorkflowError as exc:
            self.write_issue(exc)
            self.write_report("failed", issue=str(self.issue_path))
            print(str(exc), file=sys.stderr)
            if exc.suggestion:
                print(exc.suggestion, file=sys.stderr)
            return exc.exit_code or 2
        return 0

    def log_env_presence(self) -> None:
        safe_presence = {
            key: {
                "present": present,
                "redacted": bool(SECRET_KEY_PATTERN.search(key)),
            }
            for key, present in sorted(self.config.env_presence.items())
        }
        self.append_workflow_log("credential_env_presence=" + json.dumps(safe_presence, sort_keys=True))

    def ensure_kubernetes_ready(self) -> None:
        result = self.run_step(
            "kubectl-context-check",
            [
                "kubectl",
                "get",
                "nodes",
                "--context",
                "siliconboutique",
                "--request-timeout=10s",
            ],
            check=False,
        )
        if result.returncode == 0:
            return
        if self.config.skip_minikube_repair:
            raise LocalWorkflowError(
                "Kubernetes context 'siliconboutique' is not reachable.",
                step="kubectl-context-check",
                exit_code=2,
                result=result,
                suggestion="Run `.devcontainer/post-create.sh` or omit --skip-minikube-repair.",
            )
        self.run_step("repair-minikube", [".devcontainer/post-create.sh"])
        repaired = self.run_step(
            "kubectl-context-recheck",
            [
                "kubectl",
                "get",
                "nodes",
                "--context",
                "siliconboutique",
                "--request-timeout=10s",
            ],
            check=False,
        )
        if repaired.returncode != 0:
            raise LocalWorkflowError(
                "Kubernetes context 'siliconboutique' is still not reachable after repair.",
                step="kubectl-context-recheck",
                exit_code=2,
                result=repaired,
                suggestion="Inspect the Docker socket, minikube status, and the repair log.",
            )

    def preflight_bigquery(self) -> None:
        self.run_step(
            "bigquery-preflight",
            [
                sys.executable,
                "automation/scripts/load_benchmark_summary_to_bigquery.py",
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
                str(self.config.artifacts_dir / "bigquery-preflight-report.json"),
                "--duplicate-policy",
                "fail",
                "--preflight-only",
            ],
        )

    def run_local_benchmark(self) -> None:
        command = [
            sys.executable,
            "automation/scripts/run_local_benchmark.py",
            "--run-id",
            self.config.run_id,
            "--artifacts-dir",
            str(self.config.artifacts_dir),
            "--persist-bigquery",
            "--bigquery-env-file",
            str(self.config.credential_env_file),
        ]
        if not self.config.full_duration:
            command.extend(
                [
                    "--test-duration",
                    self.config.test_duration,
                    "--min-duration-seconds",
                    str(self.config.min_duration_seconds),
                ]
            )
        command.extend(self.config.extra_run_local_args)
        self.run_step("local-benchmark", command)

    def validate_bigquery_row(self) -> dict[str, Any]:
        table = (
            f"{self.config.bigquery_project_id}."
            f"{self.config.bigquery_dataset}."
            f"{self.config.bigquery_table}"
        )
        query = (
            "SELECT run_id, machine_type, benchmark_start, benchmark_end, summary_status "
            f"FROM `{table}` WHERE run_id = {sql_string(self.config.run_id)}"
        )
        result = self.run_step(
            "bigquery-row-validation",
            [
                "bq",
                "--format=json",
                "--project_id",
                self.config.bigquery_project_id,
                "--location",
                self.config.bigquery_location,
                "query",
                "--nouse_legacy_sql",
                query,
            ],
            check=False,
        )
        if result.returncode != 0:
            raise LocalWorkflowError(
                "BigQuery row validation query failed.",
                step="bigquery-row-validation",
                exit_code=2,
                result=result,
                suggestion="Inspect the BigQuery CLI output and authentication state.",
            )
        try:
            rows = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise LocalWorkflowError(
                "BigQuery row validation did not return valid JSON.",
                step="bigquery-row-validation",
                exit_code=2,
                result=result,
            ) from exc
        if not isinstance(rows, list):
            raise LocalWorkflowError(
                "BigQuery row validation did not return a row array.",
                step="bigquery-row-validation",
                exit_code=2,
                result=result,
            )
        if len(rows) != 1:
            raise LocalWorkflowError(
                f"BigQuery row validation expected exactly one row, found {len(rows)}.",
                step="bigquery-row-validation",
                exit_code=2,
                result=result,
                suggestion="Check for failed loads, duplicate run IDs, or a mismatched BigQuery destination.",
            )
        row = rows[0]
        if not isinstance(row, dict) or row.get("run_id") != self.config.run_id:
            raise LocalWorkflowError(
                "BigQuery row validation returned the wrong run_id.",
                step="bigquery-row-validation",
                exit_code=2,
                result=result,
            )
        if row.get("summary_status") != "complete":
            raise LocalWorkflowError(
                "BigQuery row validation found an incomplete benchmark summary.",
                step="bigquery-row-validation",
                exit_code=2,
                result=result,
                suggestion="Inspect benchmark-summary.json and comparability-report.json.",
            )
        return row

    def run_step(
        self,
        step: str,
        command: list[str],
        *,
        check: bool = True,
    ) -> CommandResult:
        started_at = utc_now()
        self.append_workflow_log(f"[{started_at}] start {step}: {shell_join(command)}")
        result = self.runner.run(command, cwd=REPO_ROOT, env=self.environ)
        finished_at = utc_now()
        self.write_command_log(step, command, result, started_at, finished_at)
        self.steps.append(
            {
                "step": step,
                "command": command_for_report(command),
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_code": result.returncode,
                "log_path": str(self.commands_dir / f"{step}.log"),
            }
        )
        self.append_workflow_log(f"[{finished_at}] finish {step}: exit_code={result.returncode}")
        if check and result.returncode != 0:
            raise LocalWorkflowError(
                f"{step} failed with exit {result.returncode}.",
                step=step,
                exit_code=2,
                result=result,
                suggestion=suggestion_for_step(step),
            )
        return result

    def write_command_log(
        self,
        step: str,
        command: list[str],
        result: CommandResult,
        started_at: str,
        finished_at: str,
    ) -> None:
        path = self.commands_dir / f"{step}.log"
        path.write_text(
            "\n".join(
                [
                    f"started_at={started_at}",
                    f"finished_at={finished_at}",
                    f"command={shell_join(command)}",
                    f"exit_code={result.returncode}",
                    "",
                    "stdout:",
                    redact_text(result.stdout),
                    "",
                    "stderr:",
                    redact_text(result.stderr),
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def append_workflow_log(self, line: str) -> None:
        with self.workflow_log.open("a", encoding="utf-8") as handle:
            handle.write(redact_text(line) + "\n")

    def write_issue(self, exc: LocalWorkflowError) -> None:
        write_json(
            self.issue_path,
            {
                "status": "failed",
                "failed_step": exc.step,
                "exit_code": exc.exit_code,
                "message": str(exc),
                "suggestion": exc.suggestion,
                "stdout_preview": preview_text(exc.result.stdout if exc.result else ""),
                "stderr_preview": preview_text(exc.result.stderr if exc.result else ""),
                "artifacts": diagnostic_artifacts(self.config.artifacts_dir),
                "steps": self.steps,
                "written_at": utc_now(),
            },
        )

    def write_report(
        self,
        status: str,
        *,
        bigquery_row: dict[str, Any] | None = None,
        issue: str | None = None,
    ) -> None:
        write_json(
            self.report_path,
            {
                "status": status,
                "run_id": self.config.run_id,
                "artifacts_dir": str(self.config.artifacts_dir),
                "workflow_log": str(self.workflow_log),
                "issue_report": issue,
                "bigquery": {
                    "project_id": self.config.bigquery_project_id,
                    "dataset": self.config.bigquery_dataset,
                    "table": self.config.bigquery_table,
                    "location": self.config.bigquery_location,
                    "validated_row": bigquery_row,
                },
                "artifacts": diagnostic_artifacts(self.config.artifacts_dir),
                "steps": self.steps,
                "written_at": utc_now(),
            },
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full local SiliconBoutique benchmark workflow and validate BigQuery persistence."
    )
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--credential-env-file", type=Path, default=Path("credential.env"))
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts/local-workflow"))
    parser.add_argument("--test-duration", default="2m")
    parser.add_argument("--min-duration-seconds", type=int, default=60)
    parser.add_argument("--skip-minikube-repair", action="store_true")
    parser.add_argument(
        "--full-duration",
        action="store_true",
        help="Use run_local_benchmark.py's normal benchmark duration defaults instead of smoke overrides.",
    )
    parser.add_argument(
        "--extra-run-local-arg",
        action="append",
        default=[],
        help="Extra argument passed through to run_local_benchmark.py; repeat for multiple args.",
    )
    args = parser.parse_args(argv)
    validate_args(args, parser)
    return args


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not RUN_ID_PATTERN.match(args.run_id) or len(args.run_id) > 46:
        parser.error("--run-id must be lowercase DNS-safe and at most 46 characters")
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    try:
        run_local_benchmark.parse_duration_seconds(args.test_duration)
    except ValueError as exc:
        parser.error(str(exc))


def config_from_args(
    args: argparse.Namespace,
    *,
    environ: dict[str, str] | None = None,
) -> WorkflowConfig:
    env = os.environ if environ is None else environ
    env_values = run_local_benchmark.read_env_file(args.credential_env_file)
    for key, value in env_values.items():
        env.setdefault(key, value)
    bigquery = resolve_bigquery_settings(env_values, env)
    missing = [name for name, value in bigquery.items() if not value]
    if missing:
        raise ValueError(
            "credential env must provide BigQuery settings for: "
            + ", ".join(sorted(missing))
        )
    return WorkflowConfig(
        run_id=args.run_id,
        credential_env_file=args.credential_env_file,
        artifacts_root=args.artifacts_root,
        artifacts_dir=args.artifacts_root / args.run_id,
        test_duration=args.test_duration,
        min_duration_seconds=args.min_duration_seconds,
        skip_minikube_repair=args.skip_minikube_repair,
        full_duration=args.full_duration,
        extra_run_local_args=tuple(args.extra_run_local_arg),
        bigquery_project_id=bigquery["project_id"],
        bigquery_dataset=bigquery["dataset"],
        bigquery_table=bigquery["table"],
        bigquery_location=bigquery["location"],
        env_presence=env_presence(env_values, env),
    )


def resolve_bigquery_settings(
    env_values: dict[str, str], env: dict[str, str]
) -> dict[str, str]:
    def value(*names: str) -> str:
        for name in names:
            existing = env.get(name, "").strip()
            if existing:
                return existing
        for name in names:
            file_value = env_values.get(name, "").strip()
            if file_value:
                return file_value
        return ""

    return {
        "project_id": value("BIGQUERY_PROJECT_ID", "PROJECT_ID"),
        "dataset": value("BIGQUERY_DATASET"),
        "table": value("BIGQUERY_TABLE"),
        "location": value("BIGQUERY_LOCATION"),
    }


def env_presence(env_values: dict[str, str], env: dict[str, str]) -> dict[str, bool]:
    keys = set(env_values) | {
        "PROJECT_ID",
        "BIGQUERY_PROJECT_ID",
        "BIGQUERY_DATASET",
        "BIGQUERY_TABLE",
        "BIGQUERY_LOCATION",
        "GOOGLE_APPLICATION_CREDENTIALS",
    }
    return {key: bool(env.get(key) or env_values.get(key)) for key in keys}


def default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("local-smoke-%Y%m%d-%H%M%S")


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def preview_text(value: str) -> str:
    text = redact_text(value).strip()
    if len(text) <= PREVIEW_LIMIT:
        return text
    return text[: PREVIEW_LIMIT - 14] + "...<truncated>"


def redact_text(value: str) -> str:
    redacted = value or ""
    patterns = [
        (r"(?i)(authorization:\s*)(bearer|basic)\s+\S+", r"\1<redacted>"),
        (r"(?i)((?:token|secret|password|credential|key)[A-Za-z0-9_ -]*[=:]\s*)\S+", r"\1<redacted>"),
        (r"gha-creds-[A-Za-z0-9._-]+\.json", "gha-creds-<redacted>.json"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def command_for_report(command: list[str]) -> list[str]:
    return [redact_text(part) for part in command]


def diagnostic_artifacts(artifacts_dir: Path) -> dict[str, str]:
    names = (
        "teardown-status.env",
        "teardown-precheck.txt",
        "teardown-destroy.log",
        "bigquery-load-report.json",
        "workflow-trace.json",
    )
    return {name: str(artifacts_dir / name) for name in names}


def suggestion_for_step(step: str) -> str:
    suggestions = {
        "verify-toolchain": "Rebuild or reopen the devcontainer, then rerun the workflow.",
        "repair-minikube": "Check Docker access from the devcontainer and rerun `.devcontainer/post-create.sh`.",
        "bigquery-preflight": "Check credential.env, ADC/service-account auth, table schema, and BigQuery IAM.",
        "local-benchmark": "Inspect workflow logs plus the benchmark artifacts in the run-scoped artifacts directory.",
    }
    return suggestions.get(step, "Inspect the command log for this step.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        environ = dict(os.environ)
        config = config_from_args(args, environ=environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    workflow = LocalBenchmarkWorkflow(config, environ=environ)
    return workflow.run()


if __name__ == "__main__":
    raise SystemExit(main())
