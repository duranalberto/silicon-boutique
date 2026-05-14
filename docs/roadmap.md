# Roadmap

This file serves as both the implementation history and the current planning record for the project.

## How to use this roadmap

This roadmap organizes work into **Epics** (level 2 heading, `##`) and **Tickets** (level 3 heading, `###`).

*   **Epics** represent major development phases or thematic areas.
*   **Tickets** are granular tasks within an epic. Each ticket should concisely describe the work done or to be done.

For completed work, tickets are compressed to a single line describing the outcome. For active or future work, tickets will contain more detail, including:

*   **Description:** What needs to be done.
*   **Why it matters:** The rationale behind the work.
*   **How to test:** Steps to verify completion.
*   **Edge cases:** Potential issues or considerations.
*   **Dependencies:** Other tickets or epics this work relies on.

## Current Version: Todo Actions

This section lists current and upcoming work.

## Phase 13: Unified Workflow Coordinator

### P13.1 - Add a source-agnostic workflow entrypoint
`automation/scripts/run_benchmark_workflow.py` now coordinates local, GCP, AWS, and all-target benchmark workflows from one command while preserving existing scripts as stable wrappers.

### P13.2 - Keep cloud execution guarded behind GitHub Actions
The unified coordinator preflights `gh`, dispatches GCP/AWS workflow files, waits by default, downloads artifacts, and verifies evidence without running cloud Terraform locally.

### P13.3 - Add reusable automation library modules
Shared command, environment, GitHub Actions, reporting, and unified workflow helpers were added under `automation/lib/silicon_boutique_automation/`.

### P13.4 - Document unified workflow usage
The README, automation docs, script index, and runbook now describe the unified CLI, BigQuery requirements, cloud safety behavior, and generated report location.

### P13.5 - Consolidate Markdown operator documentation
The local usage guide was removed and the runbook became the single global workflow document for local, GCP, AWS, BigQuery, dashboard, acceptance, teardown, and troubleshooting commands.

## Phase 12: Portable Metrics Dashboard

### P12.1 - Add a one-command dashboard launcher
*   **Description:** Add `automation/scripts/launch_metrics_dashboard.py` as the single command required to generate and serve a local HTML dashboard for benchmark results.
*   **Why it matters:** Users should be able to inspect collected local and cloud benchmark metrics visually without manually opening JSON, Markdown, BigQuery, or Grafana.
*   **How to test:** Run `python3 automation/scripts/launch_metrics_dashboard.py --no-browser` against an existing `artifacts/benchmark-summaries.ndjson` file and confirm it writes `artifacts/dashboard/index.html`, `artifacts/dashboard/dashboard-data.json`, and prints a localhost URL.
*   **Edge cases:** Missing artifacts directory, missing or empty summary store, port collisions, browser launch disabled in headless environments, and generated files being treated as non-canonical artifacts.
*   **Dependencies:** `P8.2`, `P10.2`.

### P12.2 - Support local artifact data by default
*   **Description:** Make the launcher default to `artifacts/benchmark-summaries.ndjson` and reuse the existing comparison report behavior for grouping, ranking, rejected-run handling, and summary quality status.
*   **Why it matters:** Local benchmark runs already produce the canonical summary store, so the dashboard should work immediately after local validation without credentials.
*   **How to test:** Use fixture or generated NDJSON rows to verify the launcher produces dashboard data with comparable groups, rankings, rejected runs, latest-run metadata, and source metadata of type `ndjson`.
*   **Edge cases:** Duplicate run IDs, short smoke runs rejected by comparability thresholds, partial summaries, nullable cost fields for local runs, and schema drift.
*   **Dependencies:** `P12.1`, `P8.2`.

### P12.3 - Add optional BigQuery history mode
*   **Description:** Add optional `--project-id`, `--dataset-id`, `--table-id`, and `--location` flags so the same dashboard can visualize durable cloud benchmark history from BigQuery.
*   **Why it matters:** GCP and AWS benchmark workflows persist canonical summaries to BigQuery, and cloud comparison should use the same visual surface as local runs.
*   **How to test:** Mock the BigQuery command runner in unit tests to verify valid arguments produce dashboard data with source type `bigquery`; verify incomplete BigQuery arguments fail with a clear error before querying.
*   **Edge cases:** Missing credentials, inaccessible datasets, empty query results, malformed BigQuery JSON output, query filters, and nullable provider-specific fields.
*   **Dependencies:** `P12.1`, `P12.2`, `P9.3`, `P11.2`.

### P12.4 - Render a self-contained visual dashboard
*   **Description:** Generate a self-contained HTML page that visualizes latest run status, throughput, frontend latency, CPU utilization, memory, cost per million requests, coverage, rankings, and rejected-run reasons.
*   **Why it matters:** The dashboard should make benchmark tradeoffs visible at a glance while preserving the existing JSON artifacts as source of truth.
*   **How to test:** Render the dashboard from deterministic fixture data and assert the HTML includes the expected sections, metric labels, embedded data reference, and rejected-run table.
*   **Edge cases:** No comparable groups, missing cost fields, one provider only, mixed local and cloud rows, long machine names, and null metric values.
*   **Dependencies:** `P12.2`, `P12.3`.

### P12.5 - Document dashboard usage and validation
*   **Description:** Update `automation/README.md`, `automation/scripts/README.md`, and `docs/runbook.md` with local artifact and BigQuery dashboard commands, expected outputs, and troubleshooting notes.
*   **Why it matters:** A one-command dashboard only helps if users can discover when to run it and understand which artifacts it reads and writes.
*   **How to test:** Follow the documented local command from a devcontainer with existing benchmark artifacts and confirm the dashboard opens; run the BigQuery example with missing credentials and confirm the documented failure mode matches the actual error.
*   **Edge cases:** Avoid documenting secrets, distinguish this portable results dashboard from the existing live Grafana dashboard, and keep generated dashboard output out of canonical docs.
*   **Dependencies:** `P12.1`, `P12.2`, `P12.3`, `P12.4`.

### P12.6 - Add dashboard launcher test coverage
*   **Description:** Add focused unit tests for CLI argument validation, local NDJSON loading, BigQuery source argument handling, generated file output, no-browser behavior, and error messages.
*   **Why it matters:** The launcher becomes a user-facing entrypoint, so its default path and failure modes should stay stable as the metrics pipeline evolves.
*   **How to test:** Run `python3 -m unittest discover -s automation/tests` and confirm the dashboard tests pass without cloud credentials or network access.
*   **Edge cases:** Temporary directories, port selection isolation, deterministic timestamps where needed, mocked browser opening, and keeping tests stdlib-only.
*   **Dependencies:** `P12.1`, `P12.2`, `P12.3`, `P12.4`.

## Phase 0: Repo Bootstrap (Completed)

### P0.1 - Normalize repository documentation
Repository documentation was normalized, ensuring consistent terminology and resolving internal links.

### P0.2 - Establish base folder structure
The base folder structure was established and documented according to the project layout.

### P0.3 - Stabilize the devcontainer
The devcontainer was stabilized as the reliable local entrypoint for development tools.

## Phase 1: Infrastructure (Completed)

### P1.1 - Build the local Kubernetes Terraform path
The Terraform path for local Kubernetes validation was built.

### P1.2 - Add the GCP rollout path
The GCP rollout path was added to the infrastructure layer.

### P1.3 - Define naming, labels, and teardown rules
Standardized `run_id`, processor labels, and cleanup expectations across managed resources.

## Phase 2: Workload Deployment (Completed)

### P2.1 - Package Online Boutique as a Helm deployment
Online Boutique was packaged as a repeatable Helm-based deployment.

### P2.2 - Parameterize the load generator
The load generator was parameterized for configurable intensity and duration.

### P2.3 - Add benchmark and monitoring manifests
Benchmark and monitoring manifests were added to capture key signals.

## Phase 3: Metrics Pipeline (Completed)

### P3.1 - Implement Prometheus metric extraction
A script was implemented to extract benchmark metrics from Prometheus into structured data.

### P3.2 - Generate and persist benchmark summaries
Benchmark summaries were generated and persisted in a queryable format.

### P3.3 - Protect metric quality and comparability
Checks were added to ensure metric quality and comparability across runs.

## Phase 4: Automation (Completed)

### P4.1 - Wire up the GitHub Actions benchmark workflow
The GitHub Actions benchmark workflow was implemented for automated execution.

### P4.2 - Guarantee teardown runs every time
Teardown was guaranteed to execute even after benchmark failures.

### P4.3 - Capture workflow outputs for traceability
Workflow outputs were captured for traceability and downstream use.

## Phase 5: MCP Readiness (Completed)

### P5.1 - Define the MCP server boundary
The MCP server boundary was defined as a clean interface.

### P5.2 - Expose status and historical query operations
Future-facing tool definitions for benchmark status and historical metric lookup were exposed.

## Phase 6: Implementation Audit Fixes (Completed)

### P6.1 - Fix the single-run comparability gate
Per-run summary validation was split from cross-run comparability validation.

### P6.2 - Add workflow-local dependency installation or switch documented test commands
Python test path was made consistent by using supported `unittest` commands.

### P6.3 - Add chart render tests for the post-renderer
Automated chart render tests were added for the `silicon-boutique-metadata` post-renderer.

### P6.4 - Close the local/cloud workflow parity gap
A local automation entrypoint was added to mirror the GCP workflow sequence.

### P6.5 - Remove or implement stale scaffold claims
Documentation and placeholder code were updated to reflect current implementation status.

## Phase 7: Priority Completion - Dashboard and Durable Results (Completed)

### P7.1 - Enable Grafana dashboard delivery
Grafana dashboard delivery was enabled, with acceptance checks verifying dashboard availability.

### P7.2 - Persist benchmark summaries to BigQuery
Benchmark summaries were persisted to BigQuery for durable storage.

### P7.3 - Compute CPU utilization from node capacity
CPU utilization was computed from workload CPU usage and node capacity.

### P7.4 - Add request-volume and cost calculations
Request volume and `cost_per_1m_requests_usd` calculations were added.

### P7.5 - Add load-profile calibration
A repeatable load-profile calibration workflow was added.

### P7.6 - Add an end-to-end acceptance demo path
An end-to-end acceptance demo path was documented and automated.

## Phase 8: Cross-Environment Comparison (Completed)

### P8.1 - Normalize provider and processor metadata
Provider and processor metadata were normalized across benchmark runs.

### P8.2 - Add comparison reports over historical summaries
A report generator was added for comparison tables over historical summaries.

### P8.3 - Add the next cloud-provider path
AWS EKS was added as a second cloud-provider path.

## Phase 9: Production MCP Integration (Completed)

### P9.1 - Implement `trigger_benchmark_run`
The `trigger_benchmark_run` operation was implemented using the GitHub Actions API.

### P9.2 - Back status queries with GitHub Actions run state
Status queries were backed by live GitHub Actions run state.

### P9.3 - Back historical queries with BigQuery
Historical queries were backed by BigQuery for durable history.

### P9.4 - Add a real MCP SDK server entrypoint
A real MCP SDK server entrypoint was added to the package.

## Phase 10: Behavior-Preserving Code Refactor (Completed)

### P10.1 - Rename phase-coupled local comparison validation
Phase-coupled local comparison validation was renamed to describe reusable behavior.

### P10.2 - Create shared automation utilities
Shared stdlib helpers were created for common automation tasks.

### P10.3 - Split local benchmark orchestration boundaries
Local benchmark orchestration boundaries were split for safer composition.

### P10.4 - Decouple acceptance demo from local benchmark internals
The acceptance demo was decoupled from internal local benchmark lifecycle methods.

### P10.5 - Consolidate BigQuery and comparison helpers
Duplicated BigQuery helper logic was consolidated into one stdlib module.

### P10.6 - Unify test naming, fixtures, and imports
Test names, fixtures, and imports were unified for better readability.

### P10.7 - Refactor chart test helpers
Chart rendering and YAML inspection helpers were refactored for reuse.

### P10.8 - Reduce workflow inline code duplication
Workflow inline code duplication was reduced by using reusable Python scripts.

### P10.9 - Dead-code and stale-reference cleanup gate
Targeted cleanup was performed for stale references and redundant helpers.

## Phase 11: Use Case Completion Hardening (Completed)

### P11.1 - Promote AWS to live benchmark workflow
AWS was promoted to a guarded live benchmark workflow.

### P11.2 - Normalize multi-cloud summary persistence and comparison
Multi-cloud summary persistence and comparison were normalized.

### P11.3 - Make Grafana dashboard verification strict
Grafana dashboard verification was made strict, requiring API-based proof.

### P11.4 - Add a multi-cloud acceptance matrix
A multi-cloud acceptance matrix and automation entrypoint were added.

### P11.5 - Update use-case documentation and definition of done
Use-case documentation and the definition of done were updated to reflect current capabilities.
