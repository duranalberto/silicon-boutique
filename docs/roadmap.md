# Roadmap

## Phase 0: Repo Bootstrap

### P0.1 - Normalize repository documentation
- Description: Reconcile terminology across `README.md`, `docs/spec-driven-development.md`, `docs/project-layout.md`, `docs/runbook.md`, `docs/architecture.md`, and this roadmap so the local Kubernetes validation path, GCP rollout path, metrics pipeline, automation flow, and future MCP boundary all use the same language.
- Why it matters: The roadmap is the clearest entry point for implementation work, and inconsistent naming across the core docs creates avoidable ambiguity before the first scaffold lands.
- How to test: Verify every internal link in the core docs resolves, confirm the phase names and workflow order match across the spec, runbook, architecture notes, and roadmap, and check that repeated terms use the same meanings everywhere.
- Edge cases: Stale links, duplicate phase names, mismatched workflow order, and duplicated wording between the roadmap and the spec.
- Dependencies: None.

### P0.2 - Establish base folder structure
- Description: Confirm the top-level folders expected by the spec exist in the repository layout and are documented with the right purpose.
- Why it matters: The project layout is part of the contract for future implementation work, especially for `infra/`, `k8s/`, `automation/`, and `mcp-server/`.
- How to test: Compare the actual tree to `docs/project-layout.md` and verify reserved directories are explained by local placeholder READMEs where needed.
- Edge cases: Empty directories not being tracked, creating folders before the team is ready, and naming drift between docs and paths.
- Dependencies: `P0.1`.

### P0.3 - Stabilize the devcontainer
- Description: Make the devcontainer the reliable local entrypoint for Terraform, kubectl, Helm, Python, Docker, and minikube.
- Why it matters: The local benchmark path depends on a reproducible development environment before any infrastructure or workload work can be trusted.
- How to test: Open the devcontainer, confirm the required toolchain is available, and verify a local Kubernetes profile starts cleanly.
- Edge cases: Missing Docker socket access, minikube profile conflicts, and tool version drift from the documented baseline.
- Dependencies: `P0.2`.

## Phase 1: Infrastructure

### P1.1 - Build the local Kubernetes Terraform path
- Description: Create the Terraform path for local Kubernetes validation first, with the variables needed to parameterize the run environment.
- Why it matters: Local validation should exercise the same shape as the future cloud workflow before GCP resources are introduced.
- How to test: Run `terraform fmt`, `terraform validate`, and a local plan/apply cycle for the Kubernetes path.
- Edge cases: Invalid variable values, repeated applies, and state drift after partial failures.
- Dependencies: `P0.3`.

### P1.2 - Add the GCP rollout path
- Description: Extend the infrastructure layer so the same workflow can target GCP and GKE after local validation succeeds.
- Why it matters: GCP is the first cloud target and must follow the same benchmark flow without introducing a separate implementation path.
- How to test: Validate the GCP module inputs, confirm a plan renders expected resources, and verify destroy is safe and complete.
- Edge cases: Missing cloud auth, project mismatch, and cloud-only resources that block teardown.
- Dependencies: `P1.1`.

### P1.3 - Define naming, labels, and teardown rules
- Description: Standardize `run_id`, processor labels, and cleanup expectations across all managed resources.
- Why it matters: Stable naming and labels are required for traceability, teardown safety, and later metric comparison.
- How to test: Inspect rendered resources for labels and annotations, then verify teardown leaves no managed resources behind.
- Edge cases: Label propagation gaps, conflicting naming conventions, and resources that outlive the benchmark run.
- Dependencies: `P1.1`, `P1.2`.

## Phase 2: Workload Deployment

### P2.1 - Package Online Boutique as a Helm deployment
- Description: Turn the workload into a repeatable Helm-based deployment that matches the standard Online Boutique service set.
- Why it matters: The benchmark needs a deterministic workload package that can be deployed the same way in local and cloud environments.
- How to test: Run `helm lint`, install into the local cluster, and confirm the expected services and pods become ready.
- Edge cases: Image pull failures, readiness probe delays, and partial service startup.
- Dependencies: `P1.1`.

### P2.2 - Parameterize the load generator
- Description: Make load settings configurable through environment variables such as `USERS_PER_SECOND` and `TEST_DURATION`.
- Why it matters: Benchmark intensity and duration must be configurable without changing the workload manifest itself.
- How to test: Deploy with multiple input combinations and confirm the benchmark window and load intensity change as expected.
- Edge cases: Zero or negative values, extremely high load settings, and timeouts shorter than pod startup time.
- Dependencies: `P2.1`.

### P2.3 - Add benchmark and monitoring manifests
- Description: Add the monitoring manifests needed to capture CPU, memory, throttling, and latency signals during the run.
- Why it matters: The metrics pipeline depends on consistent observability data before summary generation can be trusted.
- How to test: Apply the manifests cleanly and confirm the expected metrics appear in the observability stack.
- Edge cases: Missing scrape targets, namespace mismatches, and metrics that only appear after warmup.
- Dependencies: `P2.1`, `P2.2`.

## Phase 3: Metrics Pipeline

### P3.1 - Implement Prometheus metric extraction
- Description: Build the script that collects benchmark metrics from Prometheus and turns them into structured run data.
- Why it matters: The project needs a repeatable extraction step before any benchmark summary can be persisted or queried.
- How to test: Run the extractor against a live or fixture-backed Prometheus endpoint and confirm deterministic output.
- Edge cases: Incomplete scrape windows, missing series, and inconsistent timestamps.
- Dependencies: `P2.3`.

### P3.2 - Generate and persist benchmark summaries
- Description: Format the extracted data into a queryable benchmark summary and store it in the expected destination format.
- Why it matters: The benchmark results must be durable and structured so later automation and MCP queries can use them.
- How to test: Validate the output schema against a known sample and confirm summaries can be loaded or queried without manual cleanup.
- Edge cases: Schema drift, partial benchmark runs, and duplicate run IDs.
- Dependencies: `P3.1`.

### P3.3 - Protect metric quality and comparability
- Description: Add checks so summaries remain comparable across machine types and benchmark runs.
- Why it matters: Cross-machine comparison only works if units, labels, and summary fields stay stable.
- How to test: Compare two fixture runs and confirm the same summary fields are produced with stable units.
- Edge cases: Unit conversion errors, missing baseline labels, and data skew from short or aborted runs.
- Dependencies: `P3.1`, `P3.2`.

## Phase 4: Automation

### P4.1 - Wire up the GitHub Actions benchmark workflow
- Description: Add the workflow that sequences provisioning, deployment, benchmark execution, extraction, and summary persistence.
- Why it matters: The project goal is fully automated benchmark execution with no manual orchestration step.
- How to test: Run the workflow in a dry-run or branch context and confirm the step order matches the roadmap.
- Edge cases: Skipped steps, failed deploys, and secrets unavailable in the workflow context.
- Dependencies: `P1.2`, `P2.3`, `P3.2`.

### P4.2 - Guarantee teardown runs every time
- Description: Make teardown execute even when the benchmark or extraction fails.
- Why it matters: Ephemeral infrastructure is a safety requirement, not an optional cleanup task.
- How to test: Force a failure in an earlier step and verify cleanup still runs and the environment is removed.
- Edge cases: Destroy failures, interrupted jobs, and resources that become unreachable before cleanup.
- Dependencies: `P4.1`.

### P4.3 - Capture workflow outputs for traceability
- Description: Ensure the workflow exposes run metadata such as `run_id`, machine type, and summary location for downstream use.
- Why it matters: Traceable outputs are required for debugging, historical comparison, and future MCP integration.
- How to test: Verify the workflow outputs and logs contain the expected identifiers.
- Edge cases: Missing outputs after retries, log redaction of important identifiers, and concurrent runs overwriting shared names.
- Dependencies: `P4.1`, `P4.2`.

## Phase 5: MCP Readiness

### P5.1 - Define the MCP server boundary
- Description: Create the reserved service boundary for future benchmark control and history queries without coupling it to pipeline internals.
- Why it matters: The MCP layer should remain a clean interface over benchmark operations and stored results.
- How to test: Confirm the server package layout exists and the documented entry points are discoverable.
- Edge cases: Credentials leaking into the wrong layer, overexposed internal APIs, and premature coupling to workflow details.
- Dependencies: `P4.3`.

### P5.2 - Expose status and historical query operations
- Description: Add the future-facing tool definitions for benchmark status and historical metric lookup.
- Why it matters: These are the first user-facing MCP capabilities needed for agents to inspect and compare runs.
- How to test: Exercise the tool contracts against fixtures or mocks and confirm the responses match the documented schema.
- Edge cases: Queued vs running status ambiguity, empty history, and malformed query parameters.
- Dependencies: `P5.1`, `P3.2`.

## Phase 6: Implementation Audit Fixes

### P6.1 - Fix the single-run comparability gate
- Description: Split per-run summary validation from cross-run comparability validation so `.github/workflows/benchmark.yml` can succeed for a fresh benchmark artifact containing one summary row.
- Why it matters: The current workflow writes a new local `artifacts/benchmark-summaries.ndjson` store for each run, then calls `validate_benchmark_comparability.py --strict`, whose pass criteria require at least two comparable rows. That makes the end-to-end benchmark workflow fail after summary generation even when extraction succeeded.
- How to test: Run the validator against a one-row store and confirm the workflow-level gate passes when the row is schema-valid and complete; run a separate two-row comparison gate and confirm it still fails on incompatible rows.
- Edge cases: First run for a new machine type, partial summaries, duplicate run IDs, and intentionally short branch-validation runs.
- Dependencies: `P3.3`, `P4.1`.

### P6.2 - Add workflow-local dependency installation or switch documented test commands
- Description: Make the Python test path consistent by either installing `pytest` in the devcontainer and CI setup or changing documented commands to the supported `unittest` commands.
- Why it matters: `python3 -m unittest discover -s automation/tests` and `PYTHONPATH=mcp-server/src python3 -m unittest discover -s mcp-server/tests` pass, but `python -m pytest` fails when `pytest` is not installed. The repository should not document a default command that the baseline environment cannot run.
- How to test: Rebuild the devcontainer and run the documented Python test command from `AGENTS.md`, `README.md`, and package docs without manual package installation.
- Edge cases: Systems where `python` is absent but `python3` exists, future pytest-only tests, and local virtual environments masking missing devcontainer dependencies.
- Dependencies: `P0.3`.

### P6.3 - Add chart render tests for the post-renderer
- Description: Add automated tests that render the workload chart with the `silicon-boutique-metadata` post-renderer and assert that run labels, teardown annotations, and load-generator environment variables appear on the expected resources.
- Why it matters: The post-renderer mutates rendered YAML with line-oriented logic. Helm lint verifies chart syntax, but it does not prove that metadata injection still works after upstream Online Boutique chart changes.
- How to test: Render the chart with representative local and GCP values, parse the YAML documents, and assert `deployment/loadgenerator` has `USERS`, `RATE`, `LOCUST_RUN_TIME`, `CONCURRENT_USERS`, `USERS_PER_SECOND`, and `TEST_DURATION`; assert workload resources carry the required labels and annotations.
- Edge cases: Upstream container name changes, YAML indentation changes, multiple containers, existing env vars, and resources without pod templates.
- Dependencies: `P2.1`, `P2.2`, `P1.3`.

### P6.4 - Close the local/cloud workflow parity gap
- Description: Add a local automation entrypoint that runs the same provision, deploy, benchmark, extract, summarize, validate, and cleanup sequence as the GCP workflow without requiring GitHub Actions.
- Why it matters: The roadmap promises local validation of the same workflow shape, but the only complete orchestrator is the GCP-only GitHub workflow. Local users still follow a manual runbook sequence.
- How to test: Run the local entrypoint against the devcontainer minikube profile and confirm it produces the same artifact names and schema shape as the GitHub workflow, then tears down the Terraform-owned namespace.
- Edge cases: Existing namespace state, interrupted local runs, port-forward collisions on `9090`, and local runs shorter than the production comparability threshold.
- Dependencies: `P1.1`, `P2.3`, `P3.2`, `P4.3`.

### P6.5 - Remove or implement stale scaffold claims
- Description: Review documentation and placeholder code that still describes implemented areas as future or reserved, then either update the language or add implementation tickets where the claim is still true.
- Why it matters: `README.md`, `docs/project-layout.md`, and `mcp-server` docs still mix "future" language with implemented P5.2 contracts. Stale wording makes it harder to know which gaps are intentional.
- How to test: Search for `future`, `reserved`, `deferred`, and `planned` and verify each occurrence points to an active ticket or accurately describes the current implementation.
- Edge cases: Legitimate future MCP adapters, intentionally deferred BigQuery loading, and docs that should remain high-level.
- Dependencies: `P5.2`.

## Phase 7: Durable Results and Benchmark Economics

### P7.1 - Persist benchmark summaries to BigQuery
- Description: Add the BigQuery dataset/table configuration, schema management, and load step that persists the canonical `BenchmarkSummary` beyond per-run artifacts.
- Why it matters: The spec requires structured benchmark data in BigQuery for historical analysis and MCP queries, but current P3/P4 output only writes a local NDJSON artifact.
- How to test: Run a dry-run table validation, load fixture NDJSON into a test dataset, query by `run_id`, and confirm duplicate run handling is explicit.
- Edge cases: Missing GCP credentials, dataset location mismatch, schema evolution, duplicate run IDs, partial summaries, and failed loads after infrastructure teardown.
- Dependencies: `P3.2`, `P4.3`, `P6.1`.

### P7.2 - Compute CPU utilization from node capacity
- Description: Extend monitoring extraction and summary generation so `avg_cpu_utilization_pct` is populated from workload CPU usage divided by allocatable or capacity cores for the benchmark node pool.
- Why it matters: The spec calls for node utilization targets and the documented MCP output includes CPU utilization, but the summary generator currently sets `avg_cpu_utilization_pct` to `null`.
- How to test: Add Prometheus fixtures for node allocatable/capacity metrics, generate a summary, and verify utilization is non-null, unit-stable, and bounded to a sensible range.
- Edge cases: Multiple nodes, control-plane/system pods, missing kube-state-metrics node metrics, autoscaling node count changes, and local minikube capacity reporting.
- Dependencies: `P2.3`, `P3.1`, `P3.2`.

### P7.3 - Add cost and request-volume calculations
- Description: Capture enough billing and traffic data to calculate `cost_per_1m_requests_usd` and the request count denominator used for price/performance comparisons.
- Why it matters: Price-to-performance is a primary project objective, but `cost_per_1m_requests_usd` is currently a nullable future field and no request-volume summary field is persisted.
- How to test: Generate summaries from fixture data with known machine pricing and request counts, then verify cost-per-million calculations and comparability validation.
- Edge cases: Spot VM discounts and interruptions, regional price differences, GKE control-plane charges, load generator errors, retries, and runs with too few successful requests.
- Dependencies: `P7.1`, `P7.2`.

### P7.4 - Add load-profile calibration
- Description: Add a repeatable calibration workflow that finds load-generator settings that push target nodes toward the intended 80-90% utilization band without editing chart manifests.
- Why it matters: P2.2 parameterizes load, but there is no implementation that tunes resource requests/limits or load intensity to create a valid hardware bottleneck across machine families.
- How to test: Run calibration against local fixtures and one GCP machine type, then confirm the chosen settings are recorded with the summary and reused by benchmark runs.
- Edge cases: Arm vs x86 behavior differences, load-generator saturation before service saturation, node pressure evictions, and short warmup windows.
- Dependencies: `P7.2`, `P6.4`.

## Phase 8: Production MCP Integration

### P8.1 - Implement `trigger_benchmark_run`
- Description: Add the production adapter that validates a `BenchmarkRunRequest`, dispatches `.github/workflows/benchmark.yml` through the GitHub Actions API, and returns a stable external run identity.
- Why it matters: The spec lists benchmark triggering as a required MCP tool, but P5.2 only keeps it as a planned capability in the boundary manifest.
- How to test: Exercise the adapter against a mocked GitHub API and, in a guarded integration test, dispatch a branch workflow with safe inputs and verify the returned identity maps to the workflow run.
- Edge cases: GitHub token scope errors, duplicate dispatches, input validation mismatches, branch/ref selection, workflow concurrency, and rate limits.
- Dependencies: `P4.3`, `P5.1`, `P6.5`.

### P8.2 - Back status queries with GitHub Actions run state
- Description: Replace fixture-only status lookup with an adapter that maps GitHub Actions run and job state to `queued`, `running`, `completed`, `failed`, or `unknown`.
- Why it matters: The P5.2 contract can parse local trace fixtures, but real agents need live status for dispatched benchmark runs.
- How to test: Mock GitHub workflow-run responses for queued, in-progress, success, failure, cancelled, and missing runs; verify trace fields stay non-secret.
- Edge cases: Artifact upload after job completion, teardown failure after benchmark success, reruns, cancelled runs, force-cancelled cleanup, and missing workflow trace artifacts.
- Dependencies: `P8.1`.

### P8.3 - Back historical queries with BigQuery
- Description: Implement the production history store adapter using parameterized BigQuery SQL over the benchmark summary table.
- Why it matters: P5.2 reads local NDJSON fixtures, while the architecture expects durable BigQuery history for processor comparison queries.
- How to test: Run adapter tests against mocked BigQuery results and an integration test against a test dataset populated by P7.1 fixtures.
- Edge cases: Empty history, malformed filters, query cost controls, schema drift, nullable economics fields, and pagination or limit handling.
- Dependencies: `P7.1`, `P5.2`.

### P8.4 - Add a real MCP SDK server entrypoint
- Description: Add the MCP SDK transport and tool registration layer around the existing dependency-light service core.
- Why it matters: The boundary package exposes contracts and a CLI, but it is not yet an MCP server that agents can connect to directly.
- How to test: Start the server locally, list tools through an MCP client, call each tool with fixture and mocked production adapters, and verify JSON schemas match the existing contracts.
- Edge cases: Secret configuration, adapter selection, tool errors, long-running dispatch calls, and keeping Terraform/Helm internals out of the MCP process.
- Dependencies: `P8.1`, `P8.2`, `P8.3`.

## Phase 9: Infrastructure and Operations Hardening

### P9.1 - Add remote Terraform state and run locking for GCP
- Description: Configure a production-safe Terraform backend and locking strategy for GCP benchmark runs while preserving bounded static validation for pull requests.
- Why it matters: The GitHub workflow currently relies on same-job local Terraform state. That supports cleanup within one job, but it limits recovery after runner loss and makes force-cancel cleanup harder.
- How to test: Run static validation without backend credentials, then run a guarded cloud plan/apply/destroy with remote state and confirm cleanup can resume from a fresh runner.
- Edge cases: State bucket permissions, state leakage, concurrent workflow runs, partial applies, and emergency cleanup after job cancellation.
- Dependencies: `P4.2`, `P6.1`.

### P9.2 - Add run-scoped orphan detection
- Description: Add a bounded audit script that lists GCP and Kubernetes resources matching a `run_id` and reports anything that survived teardown.
- Why it matters: The workflow captures pre/post checks, but there is no reusable orphan detector for failed, cancelled, or force-cancelled runs.
- How to test: Run the detector against empty state, fixture outputs, and a controlled failed teardown; verify it refuses to inspect or delete resources without a run scope.
- Edge cases: Label propagation gaps, resources without labels, shared resources, API pagination, and missing cloud credentials.
- Dependencies: `P1.3`, `P4.2`, `P9.1`.

### P9.3 - Add CI validation for Terraform, Helm, Python, and docs
- Description: Add a pull-request validation workflow that runs bounded Terraform validation, Helm lint/template checks, Python unit tests, schema checks, and documentation link checks.
- Why it matters: Current validation is manual. The repo already has tests and lintable charts, but regressions can land without a CI gate.
- How to test: Open a branch with a known failing fixture, chart render issue, or Terraform format drift and confirm CI blocks it with a clear failure.
- Edge cases: Network-bound Helm dependency updates, Terraform provider downloads, hidden-file docs, Python path setup for `mcp-server`, and PRs without GCP credentials.
- Dependencies: `P6.2`, `P6.3`.

### P9.4 - Version and migrate benchmark schemas
- Description: Add explicit schema versioning for Prometheus metrics, benchmark summaries, workflow traces, and MCP result models, plus a migration policy for BigQuery table evolution.
- Why it matters: The summary schema already has nullable future fields and strict comparability checks. Durable BigQuery history and MCP adapters need controlled evolution.
- How to test: Validate old and new fixture rows, run a migration fixture, and confirm historical queries can filter or transform by schema version.
- Edge cases: Backfilled runs, partial summaries, deleted fields, renamed fields, and MCP clients pinned to older output contracts.
- Dependencies: `P7.1`, `P8.3`.
