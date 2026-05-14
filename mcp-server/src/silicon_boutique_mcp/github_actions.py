"""GitHub Actions adapter for production benchmark workflow dispatch."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from silicon_boutique_mcp.models import (
    BenchmarkRunRequest,
    BenchmarkRunStatus,
    RunIdentity,
    WorkflowTrace,
)
from silicon_boutique_shared.automation import first_env


DEFAULT_API_URL = "https://api.github.com"
DEFAULT_WORKFLOW_ID = "benchmark.yml"
DEFAULT_REF = "main"
DEFAULT_BIGQUERY_DATASET = "silicon_boutique"
DEFAULT_BIGQUERY_TABLE = "benchmark_summaries"
DEFAULT_BIGQUERY_LOCATION = "US"
API_VERSION = "2026-03-10"
RUN_ID_PATTERN = re.compile(r"^gha-(?P<workflow_run_id>[0-9]+)-(?P<attempt>[0-9]+)$")


class GitHubActionsAdapterError(ValueError):
    """Raised when workflow dispatch cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class GitHubActionsConfig:
    """Non-secret GitHub Actions dispatch configuration."""

    token: str
    owner: str
    repo: str
    ref: str = DEFAULT_REF
    workflow_id: str = DEFAULT_WORKFLOW_ID
    api_url: str = DEFAULT_API_URL
    bigquery_dataset: str = DEFAULT_BIGQUERY_DATASET
    bigquery_table: str = DEFAULT_BIGQUERY_TABLE
    bigquery_location: str = DEFAULT_BIGQUERY_LOCATION

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> GitHubActionsConfig:
        """Compute from environment.


        Args:
            env: environment (dict[str, str] | None) used by this operation.

        Returns:
            GitHubActionsConfig value produced by from environment.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        values = env if env is not None else os.environ
        token = first_env(values, "SILICON_BOUTIQUE_GITHUB_TOKEN", "GITHUB_TOKEN")
        repository = first_env(
            values,
            "SILICON_BOUTIQUE_GITHUB_REPOSITORY",
            "GITHUB_REPOSITORY",
        )
        if not token:
            raise GitHubActionsAdapterError(
                "SILICON_BOUTIQUE_GITHUB_TOKEN or GITHUB_TOKEN is required"
            )
        if not repository:
            raise GitHubActionsAdapterError(
                "SILICON_BOUTIQUE_GITHUB_REPOSITORY or GITHUB_REPOSITORY is required"
            )
        parts = repository.split("/", maxsplit=1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise GitHubActionsAdapterError(
                "GitHub repository must use owner/repo format"
            )
        return cls(
            token=token,
            owner=parts[0].strip(),
            repo=parts[1].strip(),
            ref=values.get("SILICON_BOUTIQUE_GITHUB_REF", DEFAULT_REF).strip()
            or DEFAULT_REF,
            workflow_id=values.get(
                "SILICON_BOUTIQUE_GITHUB_WORKFLOW_ID",
                DEFAULT_WORKFLOW_ID,
            ).strip()
            or DEFAULT_WORKFLOW_ID,
            api_url=values.get("SILICON_BOUTIQUE_GITHUB_API_URL", DEFAULT_API_URL).strip()
            or DEFAULT_API_URL,
            bigquery_dataset=values.get(
                "SILICON_BOUTIQUE_BIGQUERY_DATASET",
                DEFAULT_BIGQUERY_DATASET,
            ).strip()
            or DEFAULT_BIGQUERY_DATASET,
            bigquery_table=values.get(
                "SILICON_BOUTIQUE_BIGQUERY_TABLE",
                DEFAULT_BIGQUERY_TABLE,
            ).strip()
            or DEFAULT_BIGQUERY_TABLE,
            bigquery_location=values.get(
                "SILICON_BOUTIQUE_BIGQUERY_LOCATION",
                DEFAULT_BIGQUERY_LOCATION,
            ).strip()
            or DEFAULT_BIGQUERY_LOCATION,
        )


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Small HTTP response wrapper used by the injectable transport."""

    status: int
    body: bytes = b""
    headers: dict[str, str] | None = None


class HttpTransport(Protocol):
    """Minimal transport interface for deterministic adapter tests."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> HttpResponse:
        """Send an HTTP request."""
        ...


class UrlLibTransport:
    """stdlib urllib transport for GitHub REST calls."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> HttpResponse:
        """Compute request.


        Args:
            method: method (str) used by this operation.
            url: uRL (str) used by this operation.
            headers: headers (dict[str, str]) used by this operation.
            body: body (bytes | None) used by this operation.

        Returns:
            HttpResponse value produced by request.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                return HttpResponse(
                    status=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            return HttpResponse(
                status=exc.code,
                body=exc.read(),
                headers=dict(exc.headers.items()),
            )
        except URLError as exc:
            raise GitHubActionsAdapterError(
                f"GitHub API request failed: {exc.reason}"
            ) from exc


class GitHubActionsBenchmarkRunController:
    """Dispatch benchmark workflow runs through the GitHub Actions REST API."""

    def __init__(
        self,
        config: GitHubActionsConfig,
        transport: HttpTransport | None = None,
    ):
        """Initialize the object with the provided configuration.


        Args:
            config: config (GitHubActionsConfig) used by this operation.
            transport: transport (HttpTransport | None) used by this operation.

        Returns:
            None.
        """
        self.config = config
        self.transport = transport or UrlLibTransport()

    @classmethod
    def from_env(cls) -> GitHubActionsBenchmarkRunController:
        """Compute from environment.


        Returns:
            GitHubActionsBenchmarkRunController value produced by from environment.
        """
        return cls(GitHubActionsConfig.from_env())

    def trigger_benchmark_run(self, request: BenchmarkRunRequest) -> RunIdentity:
        """Trigger benchmark run.


        Args:
            request: request (BenchmarkRunRequest) used by this operation.

        Returns:
            RunIdentity value produced by trigger benchmark run.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        dispatch_started = datetime.now(timezone.utc)
        response = self.dispatch_workflow(request)
        if response.status == 200:
            payload = parse_json_object(response.body, "workflow dispatch response")
            identity = identity_from_dispatch_payload(payload)
            if identity is not None:
                return identity
            return self.lookup_dispatched_run(dispatch_started)
        if response.status == 204:
            return self.lookup_dispatched_run(dispatch_started)
        raise error_from_response(response, "GitHub workflow dispatch failed")

    def get_benchmark_status(self, run_id: str) -> WorkflowTrace:
        """Return benchmark status.


        Args:
            run_id: run ID (str) used by this operation.

        Returns:
            WorkflowTrace value produced by get benchmark status.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        lookup = parse_benchmark_run_id(run_id)
        response = self.transport.request(
            "GET",
            self.workflow_run_url(lookup.workflow_run_id),
            headers=self.headers(),
        )
        if response.status == 404:
            return unknown_workflow_trace(run_id)
        if response.status != 200:
            raise error_from_response(response, "GitHub workflow run lookup failed")

        payload = parse_json_object(response.body, "workflow run response")
        latest_attempt = int_or_none(payload.get("run_attempt")) or lookup.attempt
        if lookup.explicit_attempt and lookup.attempt != latest_attempt:
            payload = self.lookup_workflow_run_attempt(
                lookup.workflow_run_id,
                lookup.attempt,
            )
        elif not lookup.explicit_attempt:
            lookup = WorkflowRunLookup(
                workflow_run_id=lookup.workflow_run_id,
                attempt=latest_attempt,
                requested_run_id=lookup.requested_run_id,
                explicit_attempt=False,
            )
        return workflow_trace_from_run(payload, lookup)

    def lookup_workflow_run_attempt(
        self,
        workflow_run_id: str,
        attempt: int,
    ) -> dict[str, object]:
        """Look up workflow run attempt.


        Args:
            workflow_run_id: workflow run ID (str) used by this operation.
            attempt: attempt (int) used by this operation.

        Returns:
            dict[str, object] value produced by lookup workflow run attempt.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        response = self.transport.request(
            "GET",
            self.workflow_run_attempt_url(workflow_run_id, attempt),
            headers=self.headers(),
        )
        if response.status == 404:
            return {
                "id": workflow_run_id,
                "run_attempt": attempt,
                "status": "unknown",
            }
        if response.status != 200:
            raise error_from_response(
                response,
                "GitHub workflow run attempt lookup failed",
            )
        return parse_json_object(response.body, "workflow run attempt response")

    def dispatch_workflow(self, request: BenchmarkRunRequest) -> HttpResponse:
        """Dispatch workflow.


        Args:
            request: request (BenchmarkRunRequest) used by this operation.

        Returns:
            HttpResponse value produced by dispatch workflow.
        """
        payload = {
            "ref": self.config.ref,
            "inputs": workflow_inputs(request, self.config),
            "return_run_details": True,
        }
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        return self.transport.request(
            "POST",
            self.workflow_dispatch_url(),
            headers=self.headers(content_type=True),
            body=body,
        )

    def lookup_dispatched_run(self, dispatch_started: datetime) -> RunIdentity:
        """Look up dispatched run.


        Args:
            dispatch_started: dispatch started (datetime) used by this operation.

        Returns:
            RunIdentity value produced by lookup dispatched run.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        query = urlencode(
            {
                "branch": self.config.ref,
                "event": "workflow_dispatch",
                "per_page": "10",
            }
        )
        response = self.transport.request(
            "GET",
            f"{self.workflow_runs_url()}?{query}",
            headers=self.headers(),
        )
        if response.status != 200:
            raise error_from_response(response, "GitHub workflow run lookup failed")
        payload = parse_json_object(response.body, "workflow runs response")
        workflow_runs = payload.get("workflow_runs")
        if not isinstance(workflow_runs, list):
            raise GitHubActionsAdapterError(
                "GitHub workflow runs response did not include workflow_runs"
            )

        candidates = [
            run
            for run in workflow_runs
            if isinstance(run, dict)
            and run.get("event") == "workflow_dispatch"
            and created_at_or_none(run.get("created_at")) is not None
            and created_at_or_none(run.get("created_at")) >= dispatch_started
        ]
        if not candidates:
            raise GitHubActionsAdapterError(
                "GitHub dispatch succeeded, but no matching workflow run was found"
            )

        candidates.sort(
            key=lambda run: created_at_or_none(run.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        newest_created = created_at_or_none(candidates[0].get("created_at"))
        same_newest = [
            run
            for run in candidates
            if created_at_or_none(run.get("created_at")) == newest_created
        ]
        if len(same_newest) > 1:
            raise GitHubActionsAdapterError(
                "GitHub dispatch matched multiple workflow runs with the same timestamp"
            )
        return identity_from_run(candidates[0])

    def workflow_dispatch_url(self) -> str:
        """Compute workflow dispatch URL.


        Returns:
            str value produced by workflow dispatch URL.
        """
        return (
            f"{self.base_repo_url()}/actions/workflows/"
            f"{self.config.workflow_id}/dispatches"
        )

    def workflow_runs_url(self) -> str:
        """Compute workflow runs URL.


        Returns:
            str value produced by workflow runs URL.
        """
        return (
            f"{self.base_repo_url()}/actions/workflows/"
            f"{self.config.workflow_id}/runs"
        )

    def workflow_run_url(self, workflow_run_id: str) -> str:
        """Compute workflow run URL.


        Args:
            workflow_run_id: workflow run ID (str) used by this operation.

        Returns:
            str value produced by workflow run URL.
        """
        return f"{self.base_repo_url()}/actions/runs/{workflow_run_id}"

    def workflow_run_attempt_url(self, workflow_run_id: str, attempt: int) -> str:
        """Compute workflow run attempt URL.


        Args:
            workflow_run_id: workflow run ID (str) used by this operation.
            attempt: attempt (int) used by this operation.

        Returns:
            str value produced by workflow run attempt URL.
        """
        return f"{self.workflow_run_url(workflow_run_id)}/attempts/{attempt}"

    def base_repo_url(self) -> str:
        """Compute base repo URL.


        Returns:
            str value produced by base repo URL.
        """
        return (
            f"{self.config.api_url.rstrip('/')}/repos/"
            f"{self.config.owner}/{self.config.repo}"
        )

    def headers(self, *, content_type: bool = False) -> dict[str, str]:
        """Compute headers.


        Args:
            content_type: content type (bool) used by this operation.

        Returns:
            dict[str, str] value produced by headers.
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.config.token}",
            "X-github-Api-Version": API_VERSION,
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers


@dataclass(frozen=True, slots=True)
class WorkflowRunLookup:
    """Parsed benchmark run identity for GitHub workflow-run lookup."""

    workflow_run_id: str
    attempt: int
    requested_run_id: str
    explicit_attempt: bool = True

    @property
    def canonical_run_id(self) -> str:
        """Compute canonical run ID.


        Returns:
            str value produced by canonical run ID.
        """
        return f"gha-{self.workflow_run_id}-{self.attempt}"


def workflow_inputs(
    request: BenchmarkRunRequest,
    config: GitHubActionsConfig,
) -> dict[str, object]:
    """Compute workflow inputs.


    Args:
        request: request (BenchmarkRunRequest) used by this operation.
        config: config (GitHubActionsConfig) used by this operation.

    Returns:
        dict[str, object] value produced by workflow inputs.
    """
    inputs: dict[str, object] = {
        "project_id": request.project_id.strip(),
        "region": request.region.strip(),
        "zone": request.zone.strip(),
        "machine_type": request.machine_type.strip(),
        "node_count": str(request.node_count),
        "processor_family": request.processor_family.strip(),
        "cpu_platform": (request.cpu_platform or "").strip(),
        "architecture": request.architecture.strip(),
        "concurrent_users": str(request.concurrent_users),
        "users_per_second": str(request.users_per_second),
        "load_profile_source": "manual",
        "pricing_model": request.pricing_model.strip(),
        "test_duration": request.test_duration.strip(),
        "bigquery_dataset": config.bigquery_dataset,
        "bigquery_table": config.bigquery_table,
        "bigquery_location": config.bigquery_location,
        "failure_stage": "none",
        "acceptance_demo": False,
    }
    return inputs


def identity_from_dispatch_payload(payload: dict[str, object]) -> RunIdentity | None:
    """Compute identity from dispatch payload.


    Args:
        payload: payload (dict[str, object]) used by this operation.

    Returns:
        RunIdentity | None value produced by identity from dispatch payload.
    """
    workflow_run_id = payload.get("workflow_run_id")
    if workflow_run_id is None:
        return None
    return identity_from_external_values(
        workflow_run_id=workflow_run_id,
        html_url=payload.get("html_url"),
    )


def identity_from_run(run: dict[str, object]) -> RunIdentity:
    """Compute identity from run.


    Args:
        run: run (dict[str, object]) used by this operation.

    Returns:
        RunIdentity value produced by identity from run.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    workflow_run_id = run.get("id")
    if workflow_run_id is None:
        raise GitHubActionsAdapterError("GitHub workflow run did not include id")
    return identity_from_external_values(
        workflow_run_id=workflow_run_id,
        html_url=run.get("html_url"),
    )


def identity_from_external_values(
    *,
    workflow_run_id: object,
    html_url: object,
) -> RunIdentity:
    """Compute identity from external values.


    Args:
        workflow_run_id: workflow run ID (object) used by this operation.
        html_url: hTML URL (object) used by this operation.

    Returns:
        RunIdentity value produced by identity from external values.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    external_run_id = str(workflow_run_id).strip()
    if not external_run_id:
        raise GitHubActionsAdapterError("GitHub workflow run id was empty")
    external_run_url = str(html_url).strip() if html_url is not None else None
    return RunIdentity(
        run_id=canonical_benchmark_run_id(external_run_id, 1),
        external_run_id=external_run_id,
        external_run_url=external_run_url or None,
    )


def parse_benchmark_run_id(run_id: str) -> WorkflowRunLookup:
    """Parse benchmark run ID.


    Args:
        run_id: run ID (str) used by this operation.

    Returns:
        WorkflowRunLookup value produced by parse benchmark run ID.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    cleaned = run_id.strip() if isinstance(run_id, str) else ""
    match = RUN_ID_PATTERN.match(cleaned)
    if match:
        attempt = int(match.group("attempt"))
        if attempt < 1:
            raise GitHubActionsAdapterError("benchmark run attempt must be positive")
        return WorkflowRunLookup(
            workflow_run_id=match.group("workflow_run_id"),
            attempt=attempt,
            requested_run_id=cleaned,
            explicit_attempt=True,
        )
    if cleaned.isdigit():
        return WorkflowRunLookup(
            workflow_run_id=cleaned,
            attempt=1,
            requested_run_id=cleaned,
            explicit_attempt=False,
        )
    raise GitHubActionsAdapterError(
        "run_id must be a GitHub workflow run id or gha-<workflow-run-id>-<attempt>"
    )


def workflow_trace_from_run(
    run: dict[str, object],
    lookup: WorkflowRunLookup,
) -> WorkflowTrace:
    """Compute workflow trace from run.


    Args:
        run: run (dict[str, object]) used by this operation.
        lookup: lookup (WorkflowRunLookup) used by this operation.

    Returns:
        WorkflowTrace value produced by workflow trace from run.
    """
    workflow_run_id = string_or_default(run.get("id"), lookup.workflow_run_id)
    attempt = int_or_none(run.get("run_attempt")) or lookup.attempt
    status = map_workflow_run_status(
        string_or_none(run.get("status")),
        string_or_none(run.get("conclusion")),
    )
    run_started_at = string_or_none(run.get("run_started_at"))
    created_at = string_or_none(run.get("created_at"))
    updated_at = string_or_none(run.get("updated_at"))
    canonical_run_id = canonical_benchmark_run_id(workflow_run_id, attempt)
    return WorkflowTrace(
        identity=RunIdentity(
            run_id=canonical_run_id,
            external_run_id=workflow_run_id,
            external_run_url=string_or_none(run.get("html_url")),
        ),
        status=status,
        environment="gcp",
        cloud_provider="gcp",
        region="",
        zone="",
        machine_type="",
        processor_family="",
        architecture="",
        benchmark_start=run_started_at or created_at,
        benchmark_end=updated_at if status in {BenchmarkRunStatus.COMPLETED, BenchmarkRunStatus.FAILED} else None,
        summary_artifact_name=f"benchmark-{canonical_run_id}",
    )


def unknown_workflow_trace(run_id: str) -> WorkflowTrace:
    """Compute unknown workflow trace.


    Args:
        run_id: run ID (str) used by this operation.

    Returns:
        WorkflowTrace value produced by unknown workflow trace.
    """
    return WorkflowTrace(
        identity=RunIdentity(run_id=run_id),
        status=BenchmarkRunStatus.UNKNOWN,
        environment="",
        cloud_provider="",
        region="",
        zone="",
        machine_type="",
        processor_family="",
        architecture="",
    )


def map_workflow_run_status(
    status: str | None,
    conclusion: str | None,
) -> BenchmarkRunStatus:
    """Compute map workflow run status.


    Args:
        status: status (str | None) used by this operation.
        conclusion: conclusion (str | None) used by this operation.

    Returns:
        BenchmarkRunStatus value produced by map workflow run status.
    """
    if status in {"queued", "requested", "waiting", "pending"}:
        return BenchmarkRunStatus.QUEUED
    if status == "in_progress":
        return BenchmarkRunStatus.RUNNING
    if status == "completed":
        if conclusion == "success":
            return BenchmarkRunStatus.COMPLETED
        if conclusion:
            return BenchmarkRunStatus.FAILED
        return BenchmarkRunStatus.UNKNOWN
    return BenchmarkRunStatus.UNKNOWN


def canonical_benchmark_run_id(workflow_run_id: object, attempt: int) -> str:
    """Compute canonical benchmark run ID.


    Args:
        workflow_run_id: workflow run ID (object) used by this operation.
        attempt: attempt (int) used by this operation.

    Returns:
        str value produced by canonical benchmark run ID.
    """
    return f"gha-{workflow_run_id}-{attempt}"


def parse_json_object(body: bytes, label: str) -> dict[str, object]:
    """Parse jSON object.


    Args:
        body: body (bytes) used by this operation.
        label: label (str) used by this operation.

    Returns:
        dict[str, object] value produced by parse JSON object.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except json.JSONDecodeError as exc:
        raise GitHubActionsAdapterError(f"GitHub {label} was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise GitHubActionsAdapterError(f"GitHub {label} must be a JSON object")
    return payload


def created_at_or_none(value: object) -> datetime | None:
    """Compute created at or none.


    Args:
        value: value (object) used by this operation.

    Returns:
        datetime | None value produced by created at or none.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def int_or_none(value: object) -> int | None:
    """Compute integer or none.


    Args:
        value: value (object) used by this operation.

    Returns:
        int | None value produced by integer or none.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def string_or_default(value: object, default: str = "") -> str:
    """Compute string or default.


    Args:
        value: value (object) used by this operation.
        default: default (str) used by this operation.

    Returns:
        str value produced by string or default.
    """
    rendered = string_or_none(value)
    return rendered if rendered is not None else default


def string_or_none(value: object) -> str | None:
    """Compute string or none.


    Args:
        value: value (object) used by this operation.

    Returns:
        str | None value produced by string or none.
    """
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def error_from_response(response: HttpResponse, prefix: str) -> GitHubActionsAdapterError:
    """Compute error from response.


    Args:
        response: response (HttpResponse) used by this operation.
        prefix: prefix (str) used by this operation.

    Returns:
        GitHubActionsAdapterError value produced by error from response.
    """
    message = github_error_message(response.body)
    if is_rate_limited(response):
        detail = "GitHub API rate limit exceeded"
    elif response.status in {401, 403}:
        detail = "check GitHub token Actions permissions"
    elif response.status == 404:
        detail = "check GitHub repository and workflow configuration"
    elif response.status == 422:
        detail = "check workflow input validation"
    else:
        detail = "GitHub API returned an error"
    rendered = f"{prefix}: HTTP {response.status}; {detail}"
    if message:
        rendered = f"{rendered}; {message}"
    return GitHubActionsAdapterError(rendered)


def github_error_message(body: bytes) -> str | None:
    """Compute GitHub error message.


    Args:
        body: body (bytes) used by this operation.

    Returns:
        str | None value produced by GitHub error message.
    """
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return payload["message"]
    return None


def is_rate_limited(response: HttpResponse) -> bool:
    """Compute is rate limited.


    Args:
        response: response (HttpResponse) used by this operation.

    Returns:
        bool value produced by is rate limited.
    """
    headers = {key.lower(): value for key, value in (response.headers or {}).items()}
    return response.status == 403 and headers.get("x-ratelimit-remaining") == "0"
