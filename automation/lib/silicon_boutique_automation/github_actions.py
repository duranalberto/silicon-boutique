"""GitHub Actions workflow orchestration through the gh CLI."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .command import CommandResult, Runner, command_for_report, preview_text


class GitHubActionsError(RuntimeError):
    """Error raised for GitHubactionserror failures."""
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
class GitHubRun:
    """Container for git Hub Run state and behavior.


    Attributes:
        workflow_file: workflow file (str) stored on the object.
        workflow_run_id: workflow run ID (str) stored on the object.
        run_id: run ID (str) stored on the object.
        url: uRL (str | None) stored on the object.
        status: status (str | None) stored on the object.
        conclusion: conclusion (str | None) stored on the object.
        artifact_name: artifact name (str | None) stored on the object.
    """
    workflow_file: str
    workflow_run_id: str
    run_id: str
    url: str | None
    status: str | None = None
    conclusion: str | None = None
    artifact_name: str | None = None


class GitHubWorkflowClient:
    """Container for git Hub Workflow Client state and behavior.
    """
    def __init__(
        self,
        *,
        runner: Runner,
        repo_root: Path,
        github_ref: str = "main",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the object with the provided configuration.


        Args:
            runner: runner (Runner) used by this operation.
            repo_root: repo root (Path) used by this operation.
            github_ref: GitHub ref (str) used by this operation.
            sleep: sleep (Callable[[float], None]) used by this operation.

        Returns:
            None.
        """
        self.runner = runner
        self.repo_root = repo_root
        self.github_ref = github_ref
        self.sleep = sleep

    def preflight(self, workflow_file: str) -> list[dict[str, Any]]:
        """Compute preflight.


        Args:
            workflow_file: workflow file (str) used by this operation.

        Returns:
            list[dict[str, Any]] value produced by preflight.
        """
        steps: list[dict[str, Any]] = []
        steps.append(self._run_checked("gh-version", ["gh", "--version"]))
        steps.append(self._run_checked("gh-auth-status", ["gh", "auth", "status"]))
        steps.append(
            self._run_checked(
                "gh-workflow-view",
                ["gh", "workflow", "view", workflow_file],
            )
        )
        return steps

    def dispatch(self, *, workflow_file: str, inputs: dict[str, Any]) -> tuple[GitHubRun, list[dict[str, Any]]]:
        """Compute dispatch.


        Args:
            workflow_file: workflow file (str) used by this operation.
            inputs: inputs (dict[str, Any]) used by this operation.

        Returns:
            tuple[GitHubRun, list[dict[str, Any]]] value produced by dispatch.
        """
        steps: list[dict[str, Any]] = []
        command = ["gh", "workflow", "run", workflow_file, "--ref", self.github_ref]
        for key, value in sorted(inputs.items()):
            command.extend(["-f", f"{key}={format_workflow_input(value)}"])
        steps.append(self._run_checked("gh-workflow-run", command))
        run = self.lookup_latest_run(workflow_file)
        run = GitHubRun(
            workflow_file=run.workflow_file,
            workflow_run_id=run.workflow_run_id,
            run_id=run.run_id,
            url=run.url,
            status=run.status,
            conclusion=run.conclusion,
            artifact_name=artifact_name_for(workflow_file, run.workflow_run_id),
        )
        return run, steps

    def lookup_latest_run(self, workflow_file: str) -> GitHubRun:
        """Look up latest run.


        Args:
            workflow_file: workflow file (str) used by this operation.

        Returns:
            GitHubRun value produced by lookup latest run.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        command = [
            "gh",
            "run",
            "list",
            "--workflow",
            workflow_file,
            "--event",
            "workflow_dispatch",
            "--limit",
            "5",
            "--json",
            "databaseId,url,status,conclusion,createdAt,headBranch",
        ]
        result = self.runner.run(command, cwd=self.repo_root)
        if result.returncode != 0:
            raise GitHubActionsError(
                "GitHub workflow run lookup failed.",
                step="gh-run-list",
                result=result,
            )
        rows = parse_json_array(result.stdout, label="gh run list")
        if not rows:
            raise GitHubActionsError("GitHub dispatch succeeded, but no workflow run was found.", step="gh-run-list")
        first_created = rows[0].get("createdAt")
        same_created = [row for row in rows if row.get("createdAt") == first_created]
        if len(same_created) > 1:
            raise GitHubActionsError(
                "GitHub dispatch matched multiple workflow runs with the same timestamp.",
                step="gh-run-list",
                result=result,
            )
        return run_from_payload(workflow_file, rows[0])

    def wait_for_completion(
        self,
        run: GitHubRun,
        *,
        timeout_seconds: int,
        poll_interval_seconds: int,
    ) -> GitHubRun:
        """Compute wait for completion.


        Args:
            run: run (GitHubRun) used by this operation.
            timeout_seconds: timeout seconds (int) used by this operation.
            poll_interval_seconds: poll interval seconds (int) used by this operation.

        Returns:
            GitHubRun value produced by wait for completion.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        deadline = time.monotonic() + timeout_seconds
        latest = run
        while True:
            latest = self.view_run(run.workflow_run_id, workflow_file=run.workflow_file)
            if latest.status == "completed":
                if latest.conclusion == "success":
                    return latest
                raise GitHubActionsError(
                    f"GitHub workflow completed with conclusion {latest.conclusion or 'unknown'}.",
                    step="gh-run-watch",
                )
            if time.monotonic() >= deadline:
                raise GitHubActionsError(
                    "Timed out waiting for GitHub workflow completion.",
                    step="gh-run-watch",
                )
            self.sleep(poll_interval_seconds)

    def view_run(self, workflow_run_id: str, *, workflow_file: str) -> GitHubRun:
        """Compute view run.


        Args:
            workflow_run_id: workflow run ID (str) used by this operation.
            workflow_file: workflow file (str) used by this operation.

        Returns:
            GitHubRun value produced by view run.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        command = [
            "gh",
            "run",
            "view",
            workflow_run_id,
            "--json",
            "databaseId,url,status,conclusion",
        ]
        result = self.runner.run(command, cwd=self.repo_root)
        if result.returncode != 0:
            raise GitHubActionsError("GitHub workflow run status lookup failed.", step="gh-run-view", result=result)
        payload = parse_json_object(result.stdout, label="gh run view")
        run = run_from_payload(workflow_file, payload)
        return GitHubRun(
            workflow_file=run.workflow_file,
            workflow_run_id=run.workflow_run_id,
            run_id=run.run_id,
            url=run.url,
            status=run.status,
            conclusion=run.conclusion,
            artifact_name=artifact_name_for(workflow_file, run.workflow_run_id),
        )

    def download_artifact(self, run: GitHubRun, output_dir: Path) -> dict[str, Any]:
        """Compute download artifact.


        Args:
            run: run (GitHubRun) used by this operation.
            output_dir: output dir (Path) used by this operation.

        Returns:
            dict[str, Any] value produced by download artifact.
        """
        artifact_name = run.artifact_name or artifact_name_for(run.workflow_file, run.workflow_run_id)
        command = [
            "gh",
            "run",
            "download",
            run.workflow_run_id,
            "--name",
            artifact_name,
            "--dir",
            str(output_dir),
        ]
        step = self._run_checked("gh-run-download", command)
        return {
            **step,
            "artifact_name": artifact_name,
            "artifacts_dir": str(normalize_downloaded_artifact_dir(output_dir)),
        }

    def _run_checked(self, step: str, command: list[str]) -> dict[str, Any]:
        """Compute run checked.


        Args:
            step: step (str) used by this operation.
            command: command (list[str]) used by this operation.

        Returns:
            dict[str, Any] value produced by run checked.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        result = self.runner.run(command, cwd=self.repo_root)
        record = {
            "step": step,
            "command": command_for_report(command),
            "exit_code": result.returncode,
            "stdout_preview": preview_text(result.stdout),
            "stderr_preview": preview_text(result.stderr),
        }
        if result.returncode != 0:
            raise GitHubActionsError(f"{step} failed.", step=step, result=result)
        return record


def format_workflow_input(value: Any) -> str:
    """Format workflow input.


    Args:
        value: value (Any) used by this operation.

    Returns:
        str value produced by format workflow input.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def parse_json_array(payload: str, *, label: str) -> list[dict[str, Any]]:
    """Parse jSON array.


    Args:
        payload: payload (str) used by this operation.
        label: label (str) used by this operation.

    Returns:
        list[dict[str, Any]] value produced by parse JSON array.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        value = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise GitHubActionsError(f"{label} did not return valid JSON.", step=label) from exc
    if not isinstance(value, list):
        raise GitHubActionsError(f"{label} did not return an array.", step=label)
    return [item for item in value if isinstance(item, dict)]


def parse_json_object(payload: str, *, label: str) -> dict[str, Any]:
    """Parse jSON object.


    Args:
        payload: payload (str) used by this operation.
        label: label (str) used by this operation.

    Returns:
        dict[str, Any] value produced by parse JSON object.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        value = json.loads(payload or "{}")
    except json.JSONDecodeError as exc:
        raise GitHubActionsError(f"{label} did not return valid JSON.", step=label) from exc
    if not isinstance(value, dict):
        raise GitHubActionsError(f"{label} did not return an object.", step=label)
    return value


def run_from_payload(workflow_file: str, payload: dict[str, Any]) -> GitHubRun:
    """Run from payload.


    Args:
        workflow_file: workflow file (str) used by this operation.
        payload: payload (dict[str, Any]) used by this operation.

    Returns:
        GitHubRun value produced by run from payload.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    workflow_run_id = str(payload.get("databaseId") or payload.get("id") or "").strip()
    if not workflow_run_id:
        raise GitHubActionsError("GitHub workflow run did not include databaseId.", step="gh-run-parse")
    return GitHubRun(
        workflow_file=workflow_file,
        workflow_run_id=workflow_run_id,
        run_id=f"gha-{workflow_run_id}-1",
        url=str(payload.get("url") or "").strip() or None,
        status=str(payload.get("status") or "").strip() or None,
        conclusion=str(payload.get("conclusion") or "").strip() or None,
        artifact_name=artifact_name_for(workflow_file, workflow_run_id),
    )


def artifact_name_for(workflow_file: str, workflow_run_id: str) -> str:
    """Compute artifact name for.


    Args:
        workflow_file: workflow file (str) used by this operation.
        workflow_run_id: workflow run ID (str) used by this operation.

    Returns:
        str value produced by artifact name for.
    """
    if workflow_file == "benchmark-aws.yml" or workflow_file.endswith("/benchmark-aws.yml"):
        return f"benchmark-aws-{workflow_run_id}-1"
    return f"benchmark-gha-{workflow_run_id}-1"


def normalize_downloaded_artifact_dir(output_dir: Path) -> Path:
    """Normalize downloaded artifact dir.


    Args:
        output_dir: output dir (Path) used by this operation.

    Returns:
        Path value produced by normalize downloaded artifact dir.
    """
    expected = output_dir / "workflow-trace.json"
    if expected.exists():
        return output_dir
    if not output_dir.exists():
        return output_dir
    children = [child for child in output_dir.iterdir() if child.is_dir()]
    if len(children) == 1 and (children[0] / "workflow-trace.json").exists():
        return children[0]
    return output_dir
