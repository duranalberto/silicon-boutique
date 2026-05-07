# MCP Server

This directory contains the dependency-light Python boundary scaffold for the future Model Context Protocol service. P5.2 exposes fixture-testable status and historical query contracts without adding a real MCP SDK server or production cloud adapters.

## Package Layout

- `pyproject.toml`: installable package metadata and the `silicon-boutique-mcp` console script.
- `src/silicon_boutique_mcp/`: boundary models, abstract ports, tool contracts, fixture adapters, and the discoverable entry point.
- `tests/`: stdlib `unittest` coverage for importability, CLI discovery, tool contracts, fixture behavior, and boundary isolation.

## Entry Points

Run the module directly during local validation:

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --help
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --manifest
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp --tools
```

After package installation, the same scaffold is available as:

```bash
silicon-boutique-mcp --help
```

## Boundary Responsibilities

The package exposes abstract ports for:

- triggering benchmark runs
- checking run status
- querying historical benchmark results

The current manifest keeps `trigger_benchmark_run` planned and marks these P5.2 contracts as ready to exercise locally:

- `get_benchmark_status`
- `query_historical_metrics`

`get_benchmark_status` accepts a non-empty `run_id` and returns one of:

- `queued`
- `running`
- `completed`
- `failed`
- `unknown`

`query_historical_metrics` accepts optional `machine_type`, `processor_family`, and `architecture` filters plus a `limit` from `1` to `100`. The default limit is `10`.

## Fixture-Backed Local Commands

Status checks read local workflow trace JSON. The fixture can be a single trace object, an array, or an object with a `runs` array. It may use the `workflow-trace.json` shape emitted by the GitHub Actions workflow.

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp status \
  --run-id gha-123-1 \
  --trace-fixture artifacts/workflow-trace.json
```

Historical queries read the P3.2 benchmark summary NDJSON store.

```bash
PYTHONPATH=mcp-server/src python3 -m silicon_boutique_mcp history \
  --summary-store artifacts/benchmark-summaries.ndjson \
  --machine-type c3-standard-4 \
  --limit 10
```

## Out of Scope for P5.2

P5.2 does not implement a real MCP SDK server, GitHub Actions REST calls, BigQuery queries, Terraform access, Helm access, or direct imports from the existing pipeline internals. GitHub Actions and stored benchmark summaries remain behind adapter interfaces so the MCP layer stays a clean boundary over run control and historical data.
