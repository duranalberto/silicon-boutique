# Roadmap

## Phase 0: Repo Bootstrap

### P0.1 - Normalize repository documentation
- Description: Reconcile terminology across `docs/`, `README.md`, and layout notes so the local-first path, GCP rollout path, and MCP readiness path all use the same phase language.
- Why it matters: The roadmap should be the clearest entry point for implementation, and inconsistent naming makes later tickets harder to follow.
- How to test: Verify internal doc links resolve, confirm phase names match across the core docs, and ensure the roadmap descriptions agree with the spec and runbook.
- Edge cases: Stale links, mismatched phase numbering, and duplicated wording between the roadmap and spec.
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
