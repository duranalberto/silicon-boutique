"""Tests for test GitHub actions adapter."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = REPO_ROOT / "mcp-server" / "src"
sys.path.insert(0, str(MCP_SRC))

from silicon_boutique_mcp.github_actions import (  # noqa: E402
    GitHubActionsAdapterError,
    GitHubActionsBenchmarkRunController,
    GitHubActionsConfig,
    HttpResponse,
    map_workflow_run_status,
    parse_benchmark_run_id,
    workflow_inputs,
)
from silicon_boutique_mcp.models import BenchmarkRunRequest  # noqa: E402


class GitHubActionsAdapterTest(unittest.TestCase):
    """Unit tests covering git Hub Actions Adapter behavior.
    """
    def env(self):
        """Compute environment.


        Returns:
            Result produced by environment.
        """
        return {
            **os.environ,
            "PYTHONPATH": str(MCP_SRC),
            "SILICON_BOUTIQUE_GITHUB_TOKEN": "test-token",
            "SILICON_BOUTIQUE_GITHUB_REPOSITORY": "acme/silicon-boutique",
            "SILICON_BOUTIQUE_GITHUB_API_URL": "https://github.test",
        }

    def config(self):
        """Compute config.


        Returns:
            Result produced by config.
        """
        return GitHubActionsConfig(
            token="test-token",
            owner="acme",
            repo="silicon-boutique",
            ref="main",
            api_url="https://github.test",
        )

    def request(self):
        """Compute request.


        Returns:
            Result produced by request.
        """
        return BenchmarkRunRequest(
            cloud_provider="gcp",
            project_id="test-project",
            region="us-central1",
            zone="us-central1-a",
            machine_type="c3-standard-4",
            node_count=1,
            processor_family="c3",
            architecture="x86_64",
            concurrent_users=10,
            users_per_second=1,
            test_duration="20m",
            pricing_model="spot",
            cpu_platform="intel-sapphire-rapids",
        )

    def test_env_config_uses_expected_defaults_and_fallbacks(self):
        """Verify environment config uses expected defaults and fallbacks.


        Returns:
            None.
        """
        config = GitHubActionsConfig.from_env(
            {
                "GITHUB_TOKEN": "token",
                "GITHUB_REPOSITORY": "owner/repo",
            }
        )

        self.assertEqual(config.token, "token")
        self.assertEqual(config.owner, "owner")
        self.assertEqual(config.repo, "repo")
        self.assertEqual(config.ref, "main")
        self.assertEqual(config.workflow_id, "benchmark.yml")
        self.assertEqual(config.bigquery_dataset, "silicon_boutique")

    def test_env_config_requires_token_and_repository(self):
        """Verify environment config requires token and repository.


        Returns:
            None.
        """
        with self.assertRaises(GitHubActionsAdapterError):
            GitHubActionsConfig.from_env({})
        with self.assertRaises(GitHubActionsAdapterError):
            GitHubActionsConfig.from_env(
                {
                    "GITHUB_TOKEN": "token",
                    "GITHUB_REPOSITORY": "not-owner-slash-repo",
                }
            )

    def test_workflow_inputs_match_benchmark_workflow(self):
        """Verify workflow inputs match benchmark workflow.


        Returns:
            None.
        """
        inputs = workflow_inputs(self.request(), self.config())

        self.assertEqual(inputs["project_id"], "test-project")
        self.assertEqual(inputs["node_count"], "1")
        self.assertEqual(inputs["concurrent_users"], "10")
        self.assertEqual(inputs["users_per_second"], "1")
        self.assertEqual(inputs["load_profile_source"], "manual")
        self.assertEqual(inputs["failure_stage"], "none")
        self.assertIs(inputs["acceptance_demo"], False)

    def test_dispatch_200_returns_run_details(self):
        """Verify dispatch 200 returns run details.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(
                    status=200,
                    body=json.dumps(
                        {
                            "workflow_run_id": 123,
                            "html_url": "https://github.test/acme/repo/actions/runs/123",
                        }
                    ).encode("utf-8"),
                )
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        identity = controller.trigger_benchmark_run(self.request())

        self.assertEqual(identity.run_id, "gha-123-1")
        self.assertEqual(identity.external_run_id, "123")
        self.assertEqual(
            identity.external_run_url,
            "https://github.test/acme/repo/actions/runs/123",
        )
        self.assertEqual(transport.calls[0]["method"], "POST")
        self.assertIn("/actions/workflows/benchmark.yml/dispatches", transport.calls[0]["url"])
        body = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertIs(body["return_run_details"], True)
        self.assertEqual(body["ref"], "main")

    def test_dispatch_204_falls_back_to_recent_workflow_run_lookup(self):
        """Verify dispatch 204 falls back to recent workflow run lookup.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(status=204),
                HttpResponse(
                    status=200,
                    body=json.dumps(
                        {
                            "workflow_runs": [
                                {
                                    "id": 456,
                                    "event": "workflow_dispatch",
                                    "created_at": "2999-01-01T00:00:00Z",
                                    "html_url": "https://github.test/runs/456",
                                }
                            ]
                        }
                    ).encode("utf-8"),
                ),
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        identity = controller.trigger_benchmark_run(self.request())

        self.assertEqual(identity.run_id, "gha-456-1")
        self.assertEqual(transport.calls[1]["method"], "GET")
        self.assertIn("event=workflow_dispatch", transport.calls[1]["url"])

    def test_dispatch_200_without_run_details_uses_lookup(self):
        """Verify dispatch 200 without run details uses lookup.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(status=200, body=b"{}"),
                HttpResponse(
                    status=200,
                    body=json.dumps(
                        {
                            "workflow_runs": [
                                {
                                    "id": 789,
                                    "event": "workflow_dispatch",
                                    "created_at": "2999-01-01T00:00:00Z",
                                }
                            ]
                        }
                    ).encode("utf-8"),
                ),
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        identity = controller.trigger_benchmark_run(self.request())

        self.assertEqual(identity.run_id, "gha-789-1")

    def test_dispatch_http_errors_are_non_secret(self):
        """Verify dispatch HTTP errors are non secret.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(
                    status=403,
                    body=json.dumps({"message": "Resource not accessible by token"}).encode(
                        "utf-8"
                    ),
                )
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        with self.assertRaises(GitHubActionsAdapterError) as context:
            controller.trigger_benchmark_run(self.request())

        message = str(context.exception)
        self.assertIn("HTTP 403", message)
        self.assertIn("Actions permissions", message)
        self.assertNotIn("test-token", message)

    def test_missing_workflow_error_points_to_configuration(self):
        """Verify missing workflow error points to configuration.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(
                    status=404,
                    body=json.dumps({"message": "Not Found"}).encode("utf-8"),
                )
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        with self.assertRaises(GitHubActionsAdapterError) as context:
            controller.trigger_benchmark_run(self.request())

        self.assertIn("repository and workflow configuration", str(context.exception))

    def test_malformed_dispatch_response_fails_clearly(self):
        """Verify malformed dispatch response fails clearly.


        Returns:
            None.
        """
        transport = FakeTransport([HttpResponse(status=200, body=b"not-json")])
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        with self.assertRaises(GitHubActionsAdapterError) as context:
            controller.trigger_benchmark_run(self.request())

        self.assertIn("not valid JSON", str(context.exception))

    def test_lookup_fails_when_no_matching_run_exists(self):
        """Verify lookup fails when no matching run exists.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(status=204),
                HttpResponse(
                    status=200,
                    body=json.dumps({"workflow_runs": []}).encode("utf-8"),
                ),
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        with self.assertRaises(GitHubActionsAdapterError) as context:
            controller.trigger_benchmark_run(self.request())

        self.assertIn("no matching workflow run", str(context.exception))

    def test_lookup_fails_on_ambiguous_newest_runs(self):
        """Verify lookup fails on ambiguous newest runs.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(status=204),
                HttpResponse(
                    status=200,
                    body=json.dumps(
                        {
                            "workflow_runs": [
                                {
                                    "id": 1,
                                    "event": "workflow_dispatch",
                                    "created_at": "2999-01-01T00:00:00Z",
                                },
                                {
                                    "id": 2,
                                    "event": "workflow_dispatch",
                                    "created_at": "2999-01-01T00:00:00Z",
                                },
                            ]
                        }
                    ).encode("utf-8"),
                ),
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        with self.assertRaises(GitHubActionsAdapterError) as context:
            controller.trigger_benchmark_run(self.request())

        self.assertIn("multiple workflow runs", str(context.exception))

    def test_lookup_http_rate_limit_error_is_reported(self):
        """Verify lookup HTTP rate limit error is reported.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(status=204),
                HttpResponse(
                    status=403,
                    body=json.dumps({"message": "API rate limit exceeded"}).encode(
                        "utf-8"
                    ),
                    headers={"x-ratelimit-remaining": "0"},
                ),
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        with self.assertRaises(GitHubActionsAdapterError) as context:
            controller.trigger_benchmark_run(self.request())

        self.assertIn("rate limit", str(context.exception))

    def test_status_mapping_covers_github_run_states(self):
        """Verify status mapping covers GitHub run states.


        Returns:
            None.
        """
        expected = {
            ("queued", None): "queued",
            ("requested", None): "queued",
            ("waiting", None): "queued",
            ("pending", None): "queued",
            ("in_progress", None): "running",
            ("completed", "success"): "completed",
            ("completed", "failure"): "failed",
            ("completed", "cancelled"): "failed",
            ("completed", "timed_out"): "failed",
            ("completed", "skipped"): "failed",
            ("completed", None): "unknown",
            ("mystery", None): "unknown",
        }
        for (status, conclusion), mapped in expected.items():
            with self.subTest(status=status, conclusion=conclusion):
                self.assertEqual(map_workflow_run_status(status, conclusion), mapped)

    def test_parse_benchmark_run_id_accepts_canonical_and_numeric_ids(self):
        """Verify parse benchmark run ID accepts canonical and numeric IDs.


        Returns:
            None.
        """
        canonical = parse_benchmark_run_id("gha-123-2")
        numeric = parse_benchmark_run_id("123")

        self.assertEqual(canonical.workflow_run_id, "123")
        self.assertEqual(canonical.attempt, 2)
        self.assertIs(canonical.explicit_attempt, True)
        self.assertEqual(canonical.canonical_run_id, "gha-123-2")
        self.assertEqual(numeric.workflow_run_id, "123")
        self.assertEqual(numeric.attempt, 1)
        self.assertIs(numeric.explicit_attempt, False)
        self.assertEqual(numeric.canonical_run_id, "gha-123-1")

    def test_parse_benchmark_run_id_rejects_invalid_ids(self):
        """Verify parse benchmark run ID rejects invalid IDs.


        Returns:
            None.
        """
        for run_id in ("", "gha-123", "gha-abc-1", "local-run"):
            with self.subTest(run_id=run_id):
                with self.assertRaises(GitHubActionsAdapterError):
                    parse_benchmark_run_id(run_id)

    def test_get_status_returns_workflow_trace_for_latest_attempt(self):
        """Verify get status returns workflow trace for latest attempt.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(
                    status=200,
                    body=json.dumps(
                        workflow_run_payload(
                            status="in_progress",
                            conclusion=None,
                        )
                    ).encode("utf-8"),
                )
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        trace = controller.get_benchmark_status("gha-123-1")

        self.assertEqual(trace.status, "running")
        self.assertEqual(trace.identity.run_id, "gha-123-1")
        self.assertEqual(trace.identity.external_run_id, "123")
        self.assertEqual(trace.identity.external_run_url, "https://github.test/runs/123")
        self.assertEqual(trace.environment, "gcp")
        self.assertEqual(trace.cloud_provider, "gcp")
        self.assertEqual(trace.benchmark_start, "2026-05-09T12:00:00Z")
        self.assertIsNone(trace.benchmark_end)
        self.assertEqual(trace.summary_artifact_name, "benchmark-gha-123-1")
        self.assertEqual(transport.calls[0]["method"], "GET")
        self.assertIn("/actions/runs/123", transport.calls[0]["url"])

    def test_get_status_normalizes_bare_numeric_run_id(self):
        """Verify get status normalizes bare numeric run ID.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(
                    status=200,
                    body=json.dumps(workflow_run_payload(run_attempt=3)).encode("utf-8"),
                )
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        trace = controller.get_benchmark_status("123")

        self.assertEqual(trace.identity.run_id, "gha-123-3")
        self.assertEqual(len(transport.calls), 1)

    def test_get_status_uses_attempt_endpoint_for_older_attempt(self):
        """Verify get status uses attempt endpoint for older attempt.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(
                    status=200,
                    body=json.dumps(workflow_run_payload(run_attempt=3)).encode("utf-8"),
                ),
                HttpResponse(
                    status=200,
                    body=json.dumps(
                        workflow_run_payload(
                            run_attempt=2,
                            status="completed",
                            conclusion="failure",
                        )
                    ).encode("utf-8"),
                ),
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        trace = controller.get_benchmark_status("gha-123-2")

        self.assertEqual(trace.status, "failed")
        self.assertEqual(trace.identity.run_id, "gha-123-2")
        self.assertIn("/actions/runs/123/attempts/2", transport.calls[1]["url"])

    def test_get_status_returns_unknown_for_missing_run(self):
        """Verify get status returns unknown for missing run.


        Returns:
            None.
        """
        transport = FakeTransport([HttpResponse(status=404, body=b'{"message":"Not Found"}')])
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        trace = controller.get_benchmark_status("gha-999-1")

        self.assertEqual(trace.status, "unknown")
        self.assertEqual(trace.identity.run_id, "gha-999-1")

    def test_get_status_errors_are_non_secret(self):
        """Verify get status errors are non secret.


        Returns:
            None.
        """
        transport = FakeTransport(
            [
                HttpResponse(
                    status=401,
                    body=json.dumps({"message": "Bad credentials"}).encode("utf-8"),
                )
            ]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        with self.assertRaises(GitHubActionsAdapterError) as context:
            controller.get_benchmark_status("gha-123-1")

        message = str(context.exception)
        self.assertIn("HTTP 401", message)
        self.assertNotIn("test-token", message)

    def test_get_status_malformed_json_fails_clearly(self):
        """Verify get status malformed JSON fails clearly.


        Returns:
            None.
        """
        transport = FakeTransport([HttpResponse(status=200, body=b"not-json")])
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        with self.assertRaises(GitHubActionsAdapterError) as context:
            controller.get_benchmark_status("gha-123-1")

        self.assertIn("not valid JSON", str(context.exception))

    def test_get_status_trace_omits_unneeded_github_payload_fields(self):
        """Verify get status trace omits unneeded GitHub payload fields.


        Returns:
            None.
        """
        payload = workflow_run_payload(
            actor={"login": "octocat", "email": "octocat@example.com"},
            repository={"full_name": "acme/silicon-boutique"},
        )
        transport = FakeTransport(
            [HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))]
        )
        controller = GitHubActionsBenchmarkRunController(self.config(), transport)

        trace = controller.get_benchmark_status("gha-123-1")
        rendered = json.dumps(asdict(trace), sort_keys=True)

        self.assertNotIn("test-token", rendered)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("octocat@example.com", rendered)
        self.assertNotIn("repository", rendered)

    def test_cli_trigger_emits_identity_json(self):
        """Verify cLI trigger emits identity JSON.


        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            request_path = Path(tmpdir) / "request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "cloud_provider": "gcp",
                        "project_id": "test-project",
                        "region": "us-central1",
                        "zone": "us-central1-a",
                        "machine_type": "c3-standard-4",
                        "node_count": 1,
                        "processor_family": "c3",
                        "architecture": "x86_64",
                        "concurrent_users": 10,
                        "users_per_second": 1,
                        "test_duration": "20m",
                    }
                ),
                encoding="utf-8",
            )
            with GitHubApiStub() as stub:
                env = {
                    **self.env(),
                    "SILICON_BOUTIQUE_GITHUB_API_URL": stub.url,
                }
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "silicon_boutique_mcp",
                        "trigger",
                        "--request-json",
                        str(request_path),
                    ],
                    cwd=REPO_ROOT,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["run_id"], "gha-321-1")
        self.assertEqual(payload["external_run_id"], "321")

    def test_cli_live_status_emits_identity_json(self):
        """Verify cLI live status emits identity JSON.


        Returns:
            None.
        """
        with GitHubApiStub() as stub:
            env = {
                **self.env(),
                "SILICON_BOUTIQUE_GITHUB_API_URL": stub.url,
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "silicon_boutique_mcp",
                    "status",
                    "--run-id",
                    "gha-321-1",
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["run_id"], "gha-321-1")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["trace"]["identity"]["external_run_id"], "321")

    @unittest.skipUnless(
        os.environ.get("SILICON_BOUTIQUE_ENABLE_GITHUB_INTEGRATION") == "1",
        "guarded GitHub integration test is disabled by default",
    )
    def test_guarded_integration_dispatches_branch_workflow(self):
        """Verify guarded integration dispatches branch workflow.


        Returns:
            None.
        """
        controller = GitHubActionsBenchmarkRunController.from_env()

        identity = controller.trigger_benchmark_run(self.request())

        self.assertRegex(identity.run_id, r"^gha-[0-9]+-1$")
        self.assertIsNotNone(identity.external_run_id)

    @unittest.skipUnless(
        os.environ.get("SILICON_BOUTIQUE_ENABLE_GITHUB_INTEGRATION") == "1"
        and os.environ.get("SILICON_BOUTIQUE_GITHUB_STATUS_RUN_ID"),
        "guarded GitHub status integration test is disabled by default",
    )
    def test_guarded_integration_queries_workflow_status(self):
        """Verify guarded integration queries workflow status.


        Returns:
            None.
        """
        controller = GitHubActionsBenchmarkRunController.from_env()

        trace = controller.get_benchmark_status(
            os.environ["SILICON_BOUTIQUE_GITHUB_STATUS_RUN_ID"]
        )

        self.assertRegex(trace.identity.run_id, r"^gha-[0-9]+-[0-9]+$")
        self.assertIsNotNone(trace.identity.external_run_url)


class FakeTransport:
    """Test double that records transport interactions.
    """
    def __init__(self, responses):
        """Initialize the object with the provided configuration.


        Args:
            responses: responses used by this operation.

        Returns:
            None.
        """
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers, body=None):
        """Compute request.


        Args:
            method: method used by this operation.
            url: uRL used by this operation.
            headers: headers used by this operation.
            body: body used by this operation.

        Returns:
            Result produced by request.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


class GitHubApiStub:
    """Unit tests covering git Hub API Stub behavior.
    """
    def __enter__(self):
        """Enter the context manager and return the active resource.


        Returns:
            Result produced by enter.
        """
        class Handler(BaseHTTPRequestHandler):
            """Unit tests covering handler behavior.
            """
            def do_POST(handler):
                """Compute do POST.


                Args:
                    handler: handler used by this operation.

                Returns:
                    None.
                """
                length = int(handler.headers.get("content-length", "0"))
                handler.rfile.read(length)
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.end_headers()
                handler.wfile.write(
                    json.dumps(
                        {
                            "workflow_run_id": 321,
                            "html_url": "https://github.test/runs/321",
                        }
                    ).encode("utf-8")
                )

            def do_GET(handler):
                """Compute do GET.


                Args:
                    handler: handler used by this operation.

                Returns:
                    None.
                """
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.end_headers()
                handler.wfile.write(
                    json.dumps(
                        workflow_run_payload(
                            workflow_run_id=321,
                            status="completed",
                            conclusion="success",
                            html_url="https://github.test/runs/321",
                        )
                    ).encode("utf-8")
                )

            def log_message(self, format, *args):
                """Compute log message.


                Args:
                    format: format used by this operation.
                    args: arguments used by this operation.

                Returns:
                    None.
                """
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type, exc, traceback):
        """Exit the context manager and release owned resources.


        Args:
            exc_type: exc type used by this operation.
            exc: exc used by this operation.
            traceback: traceback used by this operation.

        Returns:
            None.
        """
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def workflow_run_payload(
    *,
    workflow_run_id=123,
    run_attempt=1,
    status="completed",
    conclusion="success",
    html_url="https://github.test/runs/123",
    actor=None,
    repository=None,
):
    """Compute workflow run payload.


    Args:
        workflow_run_id: workflow run ID used by this operation.
        run_attempt: run attempt used by this operation.
        status: status used by this operation.
        conclusion: conclusion used by this operation.
        html_url: hTML URL used by this operation.
        actor: actor used by this operation.
        repository: repository used by this operation.

    Returns:
        Result produced by workflow run payload.
    """
    return {
        "id": workflow_run_id,
        "run_attempt": run_attempt,
        "status": status,
        "conclusion": conclusion,
        "html_url": html_url,
        "created_at": "2026-05-09T11:59:00Z",
        "run_started_at": "2026-05-09T12:00:00Z",
        "updated_at": "2026-05-09T12:20:00Z",
        "actor": actor or {"login": "octocat"},
        "repository": repository or {"full_name": "acme/silicon-boutique"},
    }


if __name__ == "__main__":
    unittest.main()
