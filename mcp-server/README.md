# MCP Server

This directory contains the Python MCP boundary package. P9.4 exposes production GitHub Actions adapters for `trigger_benchmark_run` and `get_benchmark_status`, a production BigQuery adapter for `query_historical_metrics`, and a real stdio MCP SDK server around those tools.

## Package Layout

- `pyproject.toml`: installable package metadata plus `silicon-boutique-mcp` and `silicon-boutique-mcp-stdio` console scripts.
- `src/silicon_boutique_mcp/`: boundary models, abstract ports, tool contracts, fixture adapters, production adapters, CLI, and MCP stdio server entry point.
- `tests/`: stdlib `unittest` coverage for importability, CLI discovery, tool contracts, fixture behavior, and boundary isolation.

## Entry Points

Run the module directly during local validation:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --help
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --manifest
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --tools
```

After package installation, the same CLI is available as:

```bash
silicon-boutique-mcp --help
```

The MCP stdio server is available after installing the package with its runtime dependencies:

```bash
silicon-boutique-mcp-stdio
```

## Boundary Responsibilities

The package exposes abstract ports for:

- triggering benchmark runs
- checking run status
- querying historical benchmark results

The current manifest marks `trigger_benchmark_run`, `get_benchmark_status`, and `query_historical_metrics` as production-adapter ready. Local fixture-backed status and history checks remain available for development.

`trigger_benchmark_run` accepts the GCP benchmark metadata represented by `BenchmarkRunRequest`, validates the request, dispatches the `benchmark.yml` workflow with `workflow_dispatch`, and returns the derived benchmark identity as `gha-<github-run-id>-1`.

Configure the production adapter with environment variables:

- `SILICON_BOUTIQUE_GITHUB_TOKEN`, falling back to `GITHUB_TOKEN`
- `SILICON_BOUTIQUE_GITHUB_REPOSITORY`, falling back to `GITHUB_REPOSITORY`, in `owner/repo` format
- `SILICON_BOUTIQUE_GITHUB_REF`, defaulting to `main`
- `SILICON_BOUTIQUE_GITHUB_WORKFLOW_ID`, defaulting to `benchmark.yml`
- `SILICON_BOUTIQUE_BIGQUERY_PROJECT_ID`, falling back to `GOOGLE_CLOUD_PROJECT`
- `SILICON_BOUTIQUE_BIGQUERY_DATASET`, `SILICON_BOUTIQUE_BIGQUERY_TABLE`, and `SILICON_BOUTIQUE_BIGQUERY_LOCATION`, defaulting to `silicon_boutique`, `benchmark_summaries`, and `US`

`get_benchmark_status` accepts a non-empty `run_id` and returns one of:

- `queued`
- `running`
- `completed`
- `failed`
- `unknown`

Production status lookup accepts `gha-<github-run-id>-<attempt>` or a bare numeric GitHub workflow run ID. It maps GitHub run states to the boundary status enum and returns non-secret trace metadata such as external run URL, benchmark start/end timestamps, and the expected benchmark artifact name. Local fixture-backed status checks remain available with `--trace-fixture`.

`query_historical_metrics` accepts optional `machine_type`, `processor_family`, and `architecture` filters plus a `limit` from `1` to `100`. Production history lookup runs a read-only Standard SQL query through the `bq` CLI and returns normalized provider, processor, quality, latency, throughput, and cost fields. The default limit is `10`.

## Fixture-Backed Local Commands

Status checks read local workflow trace JSON. The fixture can be a single trace object, an array, or an object with a `runs` array. It may use the `workflow-trace.json` shape emitted by the GitHub Actions workflow.

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp status \
  --run-id gha-123-1 \
  --trace-fixture artifacts/workflow-trace.json
```

Without `--trace-fixture`, status uses the production GitHub Actions adapter:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp status \
  --run-id gha-123-1
```

Historical queries read the P3.2 benchmark summary NDJSON store.

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp history \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --machine-type c3-standard-4 \
  --limit 10
```

Without `--summary-store`, history uses the production BigQuery adapter:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp history \
  --machine-type c3-standard-4 \
  --limit 10
```

## Production Trigger Command

Dispatch the GCP benchmark workflow with a JSON request file:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp trigger \
  --request-json request.json
```

The token needs GitHub Actions write permission for workflow dispatch and Actions read permission for fallback run lookup and live status checks. The command prints a JSON `RunIdentity` containing `run_id`, `external_run_id`, and `external_run_url`.

## MCP Stdio Server

Run the real MCP transport with production adapters:

```bash
silicon-boutique-mcp-stdio
```

For local fixture-backed MCP validation, set:

```bash
export SILICON_BOUTIQUE_MCP_ADAPTER_MODE=fixture
export SILICON_BOUTIQUE_TRACE_FIXTURE=artifacts/workflow-trace.json
export SILICON_BOUTIQUE_SUMMARY_STORE=artifacts/benchmark-summaries.ndjson
silicon-boutique-mcp-stdio
```

Fixture mode supports `get_benchmark_status` and `query_historical_metrics`. It intentionally returns a tool error for `trigger_benchmark_run`.

## Out of Scope

P9.4 does not implement Streamable HTTP, remote hosting, MCP auth, prompts, resources, artifact-derived trace enrichment, Terraform access, Helm access, or direct imports from the existing pipeline internals. GitHub Actions and stored benchmark summaries remain behind adapter interfaces so the MCP layer stays a clean boundary over run control and historical data.
