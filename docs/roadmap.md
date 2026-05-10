# Roadmap

This file is both implementation history and current planning record. Older completed phases may preserve the original wording that described work before it existed; active status lines state the current repository state.

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
- Status: Implemented; the validator supports `--run-id` for current-run summary validation while historical comparability remains an explicit unscoped mode.
- Description: Split per-run summary validation from cross-run comparability validation so `.github/workflows/benchmark.yml` can succeed for a fresh benchmark artifact containing one summary row.
- Why it matters: The workflow can append multiple local rows to `artifacts/benchmark-summaries.ndjson`, including short smoke runs. Current-run validation must not fail because unrelated historical rows are below the production duration threshold.
- How to test: Run the validator against a multi-row store with `--run-id` and confirm the selected schema-valid row passes; run a separate unscoped two-row comparison gate and confirm it still fails on incompatible rows.
- Edge cases: First run for a new machine type, partial summaries, duplicate run IDs, intentionally short branch-validation runs, and stale historical rows.
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

## Phase 7: Priority Completion - Dashboard and Durable Results

Status: Implemented baseline. Metrics are durable, comparable, and visible in a Grafana dashboard after Online Boutique benchmark runs.

### P7.1 - Enable Grafana dashboard delivery
- Status: Implemented; the monitoring chart enables private Grafana, provisions the Online Boutique benchmark dashboard, and acceptance checks verify the dashboard through the Grafana API.
- Description: Turn on Grafana in the monitoring chart and add a run-scoped dashboard for Online Boutique benchmark signals: CPU usage, CPU utilization percentage, memory working set, CPU throttling, frontend latency percentiles, pod readiness, restarts, benchmark metadata, and benchmark window.
- Why it matters: The original requirement asks for collected metrics to be presented in a dashboard. The current stack collects Prometheus metrics but does not present them in Grafana.
- How to test: Render and lint the monitoring chart, deploy locally, port-forward Grafana, and confirm the dashboard loads with panels populated from the SiliconBoutique recording rules. Add template or unit checks that the dashboard ConfigMap is rendered when Grafana is enabled.
- Edge cases: Empty Prometheus ranges, dashboard datasource naming drift, local runs shorter than panel range defaults, Grafana sidecar label mismatches, and multiple benchmark namespaces sharing one cluster.
- Dependencies: `P2.3`, `P3.1`, `P6.4`.

### P7.2 - Persist benchmark summaries to BigQuery
- Status: Implemented; the BigQuery Terraform root provisions durable summary history and workflows load canonical summary rows with duplicate-run checks.
- Description: Add BigQuery dataset/table configuration, schema management, and a workflow load step that persists the canonical `BenchmarkSummary` beyond per-run artifacts.
- Why it matters: Historical processor comparison requires durable structured storage. Current P3/P4 output writes local JSON and NDJSON artifacts only.
- How to test: Run a dry-run table validation, load fixture NDJSON into a test dataset, query by `run_id`, and confirm duplicate run handling is explicit.
- Edge cases: Missing GCP credentials, dataset location mismatch, schema evolution, duplicate run IDs, partial summaries, and failed loads after infrastructure teardown.
- Dependencies: `P3.2`, `P4.3`, `P6.1`.

### P7.3 - Compute CPU utilization from node capacity
- Status: Implemented; monitoring and extraction populate average and max workload CPU utilization from allocatable CPU with capacity fallback.
- Description: Extend monitoring extraction and summary generation so `avg_cpu_utilization_pct` is populated from workload CPU usage divided by allocatable or capacity cores for the benchmark node pool.
- Why it matters: CPU utilization is one of the requested benchmark metrics and is currently represented as a nullable placeholder.
- How to test: Add Prometheus fixtures for node allocatable/capacity metrics, generate a summary, and verify utilization is non-null, unit-stable, and bounded to a sensible range.
- Edge cases: Multiple nodes, control-plane/system pods, missing kube-state-metrics node metrics, autoscaling node count changes, and local minikube capacity reporting.
- Dependencies: `P2.3`, `P3.1`, `P3.2`.

### P7.4 - Add request-volume and cost calculations
- Status: Implemented; load-generator parsing and pricing fixtures populate request counts, compute cost, and cost per million requests for priced cloud runs.
- Description: Capture enough traffic and pricing data to calculate request volume and `cost_per_1m_requests_usd` for price/performance comparisons.
- Why it matters: Comparing new processors against previous generations needs both performance and economics; cost is currently a nullable placeholder and request volume is not persisted.
- How to test: Generate summaries from fixture data with known machine pricing and request counts, then verify cost-per-million calculations and comparability validation.
- Edge cases: Spot VM discounts and interruptions, regional price differences, GKE control-plane charges, load generator errors, retries, and runs with too few successful requests.
- Dependencies: `P7.2`, `P7.3`.

### P7.5 - Add load-profile calibration
- Status: Implemented; calibration automation can select reusable local or GCP load profiles and record calibration metadata in summaries.
- Description: Add a repeatable calibration workflow that finds load-generator settings that push target nodes toward the intended 80-90% utilization band without editing chart manifests.
- Why it matters: P2.2 parameterizes load, but there is no implementation that tunes load intensity to create a valid hardware bottleneck across machine families.
- How to test: Run calibration against local fixtures and one GCP machine type, then confirm the chosen settings are recorded with the summary and reused by benchmark runs.
- Edge cases: Arm vs x86 behavior differences, load-generator saturation before service saturation, node pressure evictions, and short warmup windows.
- Dependencies: `P7.3`, `P6.4`.

### P7.6 - Add an end-to-end acceptance demo path
- Status: Implemented; local and cloud acceptance paths verify benchmark, metrics, summary, dashboard, optional or required BigQuery evidence, and teardown artifacts for one `run_id`.
- Description: Document and automate a single command or workflow dispatch that proves the required use case: deploy Online Boutique, run a benchmark, collect metrics, persist the summary, and open or publish the dashboard location.
- Why it matters: The project needs a clear "this solves the use case" path instead of requiring readers to infer completion from separate Terraform, Helm, and Python pieces.
- How to test: Run `python3 automation/scripts/run_acceptance_demo.py --mode local` and verify `artifacts/acceptance-demo-report.json` reports the same `run_id` across trace, summary, summary store, comparability, dashboard, and optional BigQuery evidence. Dispatch `.github/workflows/benchmark.yml` with `acceptance_demo=true` and verify the uploaded artifact contains `acceptance-demo-report.json`, `bigquery-load-report.json`, and dashboard evidence for the workflow `run_id`.
- Edge cases: Missing optional BigQuery settings in local mode, dashboard credentials, short smoke runs that fail production thresholds, and benchmark teardown before dashboard inspection.
- Dependencies: `P7.1`, `P7.2`, `P7.3`.

## Phase 8: Cross-Environment Comparison

### P8.1 - Normalize provider and processor metadata
- Status: Implemented; canonical summaries, BigQuery rows, comparability validation, workflow traces, and MCP history references now carry normalized provider location, node, pricing, load profile, and optional CPU platform metadata.
- Description: Extend benchmark metadata so every run records cloud provider, region, zone, machine type, CPU platform or processor family, architecture, node count, spot/on-demand mode, and load profile.
- Why it matters: The original use case compares processors across previous generations and different cloud environments; metadata must be stable before comparisons are trustworthy.
- How to test: Validate summary rows from local and GCP fixtures against the schema and confirm comparison mode rejects rows with incompatible or missing metadata.
- Edge cases: Provider-specific naming, unavailable CPU platform labels, Arm vs x86 conventions, and local runs that lack cloud billing metadata.
- Dependencies: `P7.2`, `P7.4`.

### P8.2 - Add comparison reports over historical summaries
- Status: Implemented; the comparison generator reads local NDJSON or BigQuery summary history and writes JSON plus Markdown ranking reports while flagging rejected non-comparable runs.
- Description: Add a report generator that reads BigQuery or local NDJSON summaries and produces comparison tables for CPU, memory, latency, throughput, cost, and run quality across machine types.
- Why it matters: The benchmark is useful only when repeated runs can be compared without manual spreadsheet work.
- How to test: Use fixture rows for at least two machine types and confirm the report ranks results consistently and flags non-comparable runs.
- Edge cases: Partial runs, mixed benchmark durations, schema version drift, missing cost fields, and multiple runs per machine type.
- Dependencies: `P8.1`, `P7.4`.

### P8.3 - Add the next cloud-provider path
- Status: Implemented; AWS EKS now has Terraform, pricing fixtures, documentation, and a guarded live benchmark workflow while static validation remains available for safe local checks.
- Description: Add a second cloud-provider path, reusing the same Helm workload, monitoring chart, extraction scripts, and summary schema.
- Why it matters: GCP is implemented as the first rollout target, but the stated goal includes different cloud environments.
- How to test: Validate the new provider Terraform or Kubernetes access path in static mode, then run the workload deployment against a test cluster when credentials are available.
- Edge cases: Managed Kubernetes feature differences, node label differences, load balancer behavior, metrics availability, and provider-specific teardown semantics.
- Dependencies: `P8.1`, `P8.2`.

## Phase 9: Production MCP Integration

### P9.1 - Implement `trigger_benchmark_run`
- Status: Implemented; the MCP boundary now validates `BenchmarkRunRequest`, dispatches the GCP benchmark workflow through a stdlib GitHub Actions adapter, and returns the derived `gha-<github-run-id>-1` run identity with external GitHub run metadata.
- Description: Add the production adapter that validates a `BenchmarkRunRequest`, dispatches `.github/workflows/benchmark.yml` through the GitHub Actions API, and returns a stable external run identity.
- Why it matters: The spec lists benchmark triggering as a required MCP tool, but the implemented boundary is still fixture-backed.
- How to test: Exercise the adapter against a mocked GitHub API and, in a guarded integration test, dispatch a branch workflow with safe inputs and verify the returned identity maps to the workflow run.
- Edge cases: GitHub token scope errors, duplicate dispatches, input validation mismatches, branch/ref selection, workflow concurrency, and rate limits.
- Dependencies: `P4.3`, `P5.1`, `P6.5`, `P7.6`.

### P9.2 - Back status queries with GitHub Actions run state
- Status: Implemented; the MCP GitHub Actions adapter now resolves canonical benchmark run IDs to workflow runs, maps live GitHub run state to boundary status values, and returns non-secret trace metadata while preserving fixture-backed local status checks.
- Description: Replace fixture-only status lookup with an adapter that maps GitHub Actions run and job state to `queued`, `running`, `completed`, `failed`, or `unknown`.
- Why it matters: Real agents need live status for dispatched benchmark runs.
- How to test: Mock GitHub workflow-run responses for queued, in-progress, success, failure, cancelled, and missing runs; verify trace fields stay non-secret.
- Edge cases: Artifact upload after job completion, teardown failure after benchmark success, reruns, cancelled runs, force-cancelled cleanup, and missing workflow trace artifacts.
- Dependencies: `P9.1`.

### P9.3 - Back historical queries with BigQuery
- Status: Implemented; the MCP boundary now uses a stdlib `bq`-backed BigQuery history adapter for production `query_historical_metrics` calls while preserving NDJSON fixture-backed history queries.
- Description: Implement the production history store adapter using parameterized BigQuery SQL over the benchmark summary table.
- Why it matters: Agent and API consumers need durable history for processor comparison queries.
- How to test: Run adapter tests against mocked BigQuery results and an integration test against a test dataset populated by P7.2 fixtures.
- Edge cases: Empty history, malformed filters, query cost controls, schema drift, nullable economics fields, and pagination or limit handling.
- Dependencies: `P7.2`, `P5.2`.

### P9.4 - Add a real MCP SDK server entrypoint
- Status: Implemented; the MCP package now includes a FastMCP stdio server entrypoint that registers the production trigger, status, and history tools while retaining fixture-mode validation for local status and history calls.
- Description: Add the MCP SDK transport and tool registration layer around the existing dependency-light service core.
- Why it matters: The boundary package exposes contracts and a CLI, but it is not yet an MCP server that agents can connect to directly.
- How to test: Start the server locally, list tools through an MCP client, call each tool with fixture and mocked production adapters, and verify JSON schemas match the existing contracts.
- Edge cases: Secret configuration, adapter selection, tool errors, long-running dispatch calls, and keeping Terraform/Helm internals out of the MCP process.
- Dependencies: `P9.1`, `P9.2`, `P9.3`.

## Phase 10: Behavior-Preserving Code Refactor

Phase 10 is refactor-only. It keeps benchmark behavior, schemas, Terraform resources, Helm output, artifact contracts, and MCP contracts stable while reducing phase-coupled naming and repeated helper code.

### P10.1 - Rename phase-coupled local comparison validation
- Status: Implemented; the local comparison helper, tests, fixture IDs, report names, and documentation now use general comparison terminology instead of phase-coupled naming.
- Description: Cleanly rename the local comparison validation command and tests without a compatibility shim.
- Why it matters: Validation helpers should describe reusable behavior, not the implementation phase that introduced them.
- How to test: Run `python3 -m unittest discover -s automation/tests` and verify no old phase-coupled helper names remain outside historical roadmap entries.
- Edge cases: Preserve exit codes, fixture fallback behavior, report content, and no-cloud-command guarantees.
- Dependencies: None.

### P10.2 - Create shared automation utilities
- Status: Implemented; shared stdlib helpers now live in the MCP source package and cover JSON/NDJSON I/O, command results, shell/log helpers, duration/timestamp utilities, and BigQuery CLI safety helpers.
- Description: Consolidate repeated helper code used by automation scripts and MCP adapters.
- Why it matters: Shared utilities make future changes to command execution, file writing, and BigQuery validation easier to audit.
- How to test: Run `python3 -m unittest automation.tests.test_shared_utilities` plus the full automation and MCP suites.
- Edge cases: Keep CLI-facing error messages stable where scripts translate shared helper errors into domain-specific exceptions.
- Dependencies: `P10.1`.

### P10.3 - Split local benchmark orchestration boundaries
- Status: Implemented; `LocalBenchmark` now exposes an `execute()` workflow interface with a post-extraction hook, so callers no longer need to drive each lifecycle method manually.
- Description: Separate the public workflow boundary from provisioning, deployment, extraction, cleanup, and trace-writing internals.
- Why it matters: The local runner remains behavior-compatible while becoming safer for other automation to compose.
- How to test: Run `python3 -m unittest automation.tests.test_run_local_benchmark`.
- Edge cases: Teardown must still run after partial failures, controlled failure stages must preserve behavior, and `--skip-destroy` must remain explicit.
- Dependencies: `P10.2`.

### P10.4 - Decouple acceptance demo from local benchmark internals
- Status: Implemented; the acceptance demo uses the public local workflow interface and captures dashboard, BigQuery, and hold evidence through the post-extraction hook.
- Description: Stop manually invoking internal local benchmark lifecycle methods from acceptance automation.
- Why it matters: Acceptance verification can evolve without duplicating orchestration order.
- How to test: Run `python3 -m unittest automation.tests.test_run_acceptance_demo`.
- Edge cases: Preserve optional BigQuery behavior, dashboard hold behavior, cleanup behavior, and `verify` mode semantics.
- Dependencies: `P10.3`.

### P10.5 - Consolidate BigQuery and comparison helpers
- Status: Implemented; BigQuery validation, SQL escaping, command result shape, `bq` execution, and JSON row parsing are shared by loader, validation, comparison, and MCP history paths.
- Description: Move duplicated BigQuery helper logic behind one stdlib module while keeping domain-specific exceptions at script boundaries.
- Why it matters: Query safety and destination validation should not drift across automation and MCP code.
- How to test: Run BigQuery loader, validation, comparison, and MCP history unit tests.
- Edge cases: Preserve generated command shape, duplicate-run policy, mocked `bq` responses, and MCP response contracts.
- Dependencies: `P10.2`.

### P10.6 - Unify test naming, fixtures, and imports
- Status: Implemented; phase-specific test names were removed, importable modules replaced path-loaded tests for the local comparison helper, and shared utility tests cover common fixtures.
- Description: Generalize test names and reduce special-case import logic.
- Why it matters: Tests should stay readable as behavior moves between phases.
- How to test: Run the full automation, MCP, and k8s unit suites.
- Edge cases: Keep all tests stdlib-compatible.
- Dependencies: `P10.1`, `P10.2`.

### P10.7 - Refactor chart test helpers
- Status: Implemented; chart rendering and line-oriented YAML inspection helpers are shared across k8s tests, with an added post-renderer regression for existing env vars and sidecar preservation.
- Description: Reuse test helper code without changing the stdlib-only Helm post-renderer behavior.
- Why it matters: The post-renderer is safety-sensitive and should have focused tests around fragile YAML mutations.
- How to test: Run `python3 -m unittest discover -s k8s/tests`.
- Edge cases: Preserve rendered labels, annotations, load-generator env vars, and Helm plugin behavior.
- Dependencies: `P10.6`.

### P10.8 - Reduce workflow inline code duplication
- Status: Implemented; workflow trace writing and acceptance summary rendering now live in reusable Python scripts with unit tests.
- Description: Replace duplicated inline Python blocks in `.github/workflows/benchmark.yml`.
- Why it matters: Workflow artifact contracts are easier to test when Python lives in versioned scripts.
- How to test: Run `python3 -m unittest automation.tests.test_workflow_trace_helpers` and inspect `.github/workflows/benchmark.yml` for remaining inline Python blocks.
- Edge cases: Preserve GitHub output names, artifact names, teardown status handling, and acceptance-demo evidence.
- Dependencies: `P10.3`, `P10.4`.

### P10.9 - Dead-code and stale-reference cleanup gate
- Status: Implemented; phase-coupled validation references were removed from active code/docs, stale phase-flow wording was updated, and duplicate helper hotspots were reduced behind shared modules.
- Description: Run targeted cleanup for stale phase references, old future wording, and redundant helper definitions.
- Why it matters: Refactor work should leave the repository easier to navigate.
- How to test: Run targeted `rg` searches for phase-coupled names and duplicate helpers, then run the full documented validation commands.
- Edge cases: Keep legitimate historical roadmap entries and intentionally scaffolded AWS warnings.
- Dependencies: `P10.1` through `P10.8`.

## Phase 11: Use Case Completion Hardening

Status: Implemented. Phase 11 closed the remaining use-case gaps by promoting AWS to a guarded live workflow, tightening dashboard verification, normalizing multi-cloud comparison evidence, and documenting acceptance criteria.

### P11.1 - Promote AWS to live benchmark workflow
- Status: Implemented; `.github/workflows/benchmark-aws.yml` applies the AWS EKS root, deploys shared charts, extracts metrics, writes canonical artifacts, loads BigQuery history, records acceptance evidence, and destroys run-scoped resources.
- Description: Add a guarded AWS benchmark workflow that authenticates to AWS, applies the existing EKS Terraform root, configures kubeconfig, deploys the shared Online Boutique and monitoring Helm charts, runs the benchmark window, extracts metrics, generates the canonical summary, persists or exports results, and destroys run-scoped resources.
- Why it matters: The original request explicitly calls for analysis in different cloud environments. The current AWS path validates Terraform shape only, so the use case is still GCP-first rather than multi-cloud.
- How to test: Run static workflow tests and Terraform validation without credentials; run one guarded live AWS smoke benchmark in a sandbox account; verify uploaded artifacts include `benchmark-summary.json`, `prometheus-metrics.json`, `loadgenerator-stats.json`, `workflow-trace.json`, dashboard evidence, and teardown logs; confirm EKS, VPC, subnet, IAM, and node group resources are gone after teardown.
- Edge cases: Missing AWS credentials, IAM propagation delays, EKS node readiness delays, public endpoint restrictions, spot capacity failures, Kubernetes metric name differences, interrupted jobs, and failed destroys requiring manual state inspection.
- Dependencies: `P8.3`, `P7.6`, `P10.8`.

### P11.2 - Normalize multi-cloud summary persistence and comparison
- Status: Implemented; GCP and AWS produce the same summary and artifact contracts for BigQuery loading, acceptance verification, and comparison reports.
- Description: Ensure GCP and AWS runs produce the same `BenchmarkSummary` contract, can be loaded into the durable history destination or exported to an equivalent provider-neutral store, and can be compared by `generate_comparison_report.py` without manual field edits.
- Why it matters: Collecting metrics is not enough; the goal is repeated comparison across new processors, previous generations, and providers.
- How to test: Generate at least one GCP and one AWS summary with matching load profile and benchmark duration, load or combine them into a single summary store, run comparability validation, and produce JSON plus Markdown comparison reports that include CPU, memory, latency, throughput, cost, provider, region, zone, machine type, processor family, architecture, and pricing model.
- Edge cases: Provider-specific pricing models, unavailable CPU platform metadata, region naming differences, missing cost fixtures, partial summaries, duplicate run IDs, and incompatible load profiles.
- Dependencies: `P11.1`, `P8.1`, `P8.2`, `P9.3`.

### P11.3 - Make Grafana dashboard verification strict
- Status: Implemented; acceptance verification reads the generated Grafana admin secret and requires the expected dashboard to load through the Grafana API.
- Description: Update acceptance verification so dashboard success requires Grafana to load the expected dashboard through the API, not only that the dashboard ConfigMap exists. Fix dashboard credential handling so the verifier reads the generated Grafana admin secret or configures a deterministic test credential safely.
- Why it matters: The audit found that local acceptance can pass while Grafana API access is reported as `skipped_unavailable` because of authentication failure. The use case asks for metrics presented in a dashboard, so dashboard availability should be proven.
- How to test: Run `python3 automation/scripts/run_acceptance_demo.py --mode local --dashboard-hold-seconds 1` and require `checks.dashboard.grafana_load_status.status == "passed"`; dispatch the GCP acceptance workflow and require the uploaded acceptance report to prove the dashboard UID and title through Grafana or an equivalent live API check; add unit tests for secret lookup, authentication failure, and unavailable Grafana behavior.
- Edge cases: Random Grafana admin passwords, Helm chart credential changes, port-forward collisions, Grafana sidecar import delays, API readiness after pod readiness, and private dashboard services in cloud workflows.
- Dependencies: `P7.1`, `P7.6`, `P10.4`.

### P11.4 - Add a multi-cloud acceptance matrix
- Status: Implemented; `automation/scripts/run_acceptance_matrix.py` verifies local, GCP, AWS, dashboard, summary, comparison, storage, and teardown evidence in one report.
- Description: Add a documented acceptance matrix and automation entrypoint that runs or verifies the minimum proof set: local smoke, GCP live benchmark, AWS live benchmark, dashboard API proof, canonical summaries, durable or combined summary storage, comparison report, and teardown evidence.
- Why it matters: Reviewers should not need to infer completion by reading separate Terraform, Helm, workflow, and Python artifacts. There should be one explicit answer to "does this achieve the requested use case?"
- How to test: Run the local matrix without cloud credentials and confirm cloud checks are reported as `skipped_requires_credentials`; run the full matrix in configured cloud projects/accounts and require all checks to pass; verify the report links each accepted run ID to workload deployment, metrics, dashboard evidence, summary row, comparison output, and teardown status.
- Edge cases: Running only one cloud provider, reusing old artifacts by accident, failed optional BigQuery setup, cloud quota limits, short smoke durations, and comparing runs with mismatched load profiles.
- Dependencies: `P11.1`, `P11.2`, `P11.3`.

### P11.5 - Update use-case documentation and definition of done
- Status: Implemented; documentation now describes the supported local, GCP, AWS, acceptance, comparison, BigQuery, and MCP paths as the current state.
- Description: Update `README.md`, `docs/runbook.md`, `docs/architecture.md`, and workflow docs to state the current supported paths, the exact commands or dispatches for local/GCP/AWS runs, and the final acceptance criteria for the original use case.
- Why it matters: Once AWS is live and dashboard verification is strict, the documentation must describe repeatable processor comparisons safely and accurately.
- How to test: Follow the updated runbook from a clean devcontainer for local validation; dry-run or statically validate cloud setup steps without credentials; run `rg` for stale phrases such as `AWS scaffold`, `static validation only`, and `skipped_unavailable` and confirm any remaining occurrences are historical or troubleshooting notes.
- Edge cases: Keeping warning language for destructive cloud operations, avoiding secrets in examples, distinguishing local smoke evidence from live cloud acceptance, and keeping historical roadmap status entries intact.
- Dependencies: `P11.1`, `P11.2`, `P11.3`, `P11.4`.
