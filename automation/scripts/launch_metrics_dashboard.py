#!/usr/bin/env python3
"""Generate and serve a local benchmark metrics dashboard."""

from __future__ import annotations

import argparse
import functools
import sys
import webbrowser
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import generate_comparison_report as comparison

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SRC = REPO_ROOT / "mcp-server" / "src"
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from silicon_boutique_shared import automation


DEFAULT_SUMMARY_STORE = Path("artifacts/benchmark-summaries.ndjson")
DEFAULT_OUTPUT_DIR = Path("artifacts/dashboard")
DEFAULT_SCHEMA = comparison.DEFAULT_SCHEMA
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DATA_FILENAME = "dashboard-data.json"
INDEX_FILENAME = "index.html"

LATEST_FIELDS = (
    "run_id",
    "benchmark_start",
    "benchmark_end",
    "summary_status",
    "environment",
    "cloud_provider",
    "region",
    "zone",
    "machine_type",
    "processor_family",
    "cpu_platform",
    "architecture",
    "node_count",
    "pricing_model",
    "load_profile_source",
    "load_concurrent_users",
    "load_users_per_second",
)
LATEST_METRIC_FIELDS = (
    "avg_requests_per_second",
    "frontend_latency_p99_ms",
    "avg_cpu_utilization_pct",
    "max_cpu_utilization_pct",
    "max_memory_used_gb",
    "cost_per_1m_requests_usd",
    "metrics_coverage_ratio",
    "request_count_total",
    "request_failure_count",
)


class DashboardLaunchError(RuntimeError):
    """Raised when the portable dashboard cannot be generated or served."""


class QuietDashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler that avoids noisy per-request logs during local inspection."""

    def log_message(self, format: str, *args: Any) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and serve a local SiliconBoutique metrics dashboard."
    )
    parser.add_argument("--summary-store", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--dataset-id")
    parser.add_argument("--table-id")
    parser.add_argument("--location")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--machine-type")
    parser.add_argument("--processor-family")
    parser.add_argument("--architecture")
    parser.add_argument("--cloud-provider")
    parser.add_argument("--pricing-model", choices=("local", "spot", "on_demand"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-duration-seconds", type=int, default=1200)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.95)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Generate and serve the dashboard without opening a browser.",
    )
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Generate dashboard files and exit without starting the local server.",
    )
    args = parser.parse_args()
    if args.project_id and args.summary_store is not None:
        parser.error("--summary-store cannot be used with --project-id")
    if args.project_id and not (args.dataset_id and args.table_id and args.location):
        parser.error("--dataset-id, --table-id, and --location are required with --project-id")
    if not args.project_id and args.summary_store is None:
        args.summary_store = DEFAULT_SUMMARY_STORE
    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.min_duration_seconds < 1:
        parser.error("--min-duration-seconds must be at least 1")
    if not 0 <= args.min_coverage_ratio <= 1:
        parser.error("--min-coverage-ratio must be between 0 and 1")
    return args


def main() -> int:
    try:
        args = parse_args()
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        dashboard = build_dashboard(
            args=args,
            output_dir=args.output_dir,
            schema_path=args.schema,
            min_duration_seconds=args.min_duration_seconds,
            min_coverage_ratio=args.min_coverage_ratio,
        )
        if args.no_serve:
            print(f"Dashboard files written to {dashboard['outputs']['output_dir']}")
            print(f"Dashboard HTML: {dashboard['outputs']['index_html']}")
            return 0

        server, url = create_server(args.output_dir, host=args.host, port=args.port)
        print(f"Dashboard files written to {dashboard['outputs']['output_dir']}")
        print(f"Dashboard URL: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard server stopped.")
        finally:
            server.server_close()
    except (
        DashboardLaunchError,
        comparison.ComparisonReportError,
        comparison.comparability.ComparabilityError,
        comparison.bigquery.BigQueryLoadError,
        OSError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def build_dashboard(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    schema_path: Path,
    min_duration_seconds: int,
    min_coverage_ratio: float,
    runner: comparison.Runner = comparison.run_bq,
) -> dict[str, Any]:
    filters = filter_values(args)
    rows, source = load_dashboard_rows(args, filters=filters, runner=runner)
    filtered_rows = comparison.apply_filters(rows, filters)
    if args.limit is not None and source["type"] == "ndjson":
        filtered_rows = comparison.sort_rows(filtered_rows)[: args.limit]
    schema = comparison.comparability.load_json(schema_path, "schema")
    report = comparison.build_comparison_report(
        rows=filtered_rows,
        source=source,
        schema=schema,
        schema_path=schema_path,
        min_duration_seconds=min_duration_seconds,
        min_coverage_ratio=min_coverage_ratio,
    )
    payload = build_dashboard_payload(
        rows=rows,
        filtered_rows=filtered_rows,
        report=report,
        filters=filters,
        limit=args.limit,
        min_duration_seconds=min_duration_seconds,
        min_coverage_ratio=min_coverage_ratio,
    )
    write_dashboard_files(output_dir, payload)
    return {
        "payload": payload,
        "outputs": {
            "output_dir": str(output_dir),
            "index_html": str(output_dir / INDEX_FILENAME),
            "dashboard_data": str(output_dir / DATA_FILENAME),
        },
    }


def load_dashboard_rows(
    args: argparse.Namespace,
    *,
    filters: dict[str, str],
    runner: comparison.Runner = comparison.run_bq,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if args.project_id:
        rows = comparison.query_bigquery_rows(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            location=args.location,
            filters=filters,
            limit=args.limit,
            runner=runner,
        )
        return rows, {
            "type": "bigquery",
            "summary_table": comparison.bigquery.table_sql_name(
                args.project_id, args.dataset_id, args.table_id
            ),
            "location": args.location,
        }
    return comparison.read_summary_store(args.summary_store), {
        "type": "ndjson",
        "summary_store": str(args.summary_store),
    }


def build_dashboard_payload(
    *,
    rows: list[dict[str, Any]],
    filtered_rows: list[dict[str, Any]],
    report: dict[str, Any],
    filters: dict[str, str],
    limit: int | None,
    min_duration_seconds: int,
    min_coverage_ratio: float,
) -> dict[str, Any]:
    return {
        "source": report["source"],
        "generated_at": report["generated_at"],
        "filters": filters,
        "limit": limit,
        "thresholds": {
            "min_duration_seconds": min_duration_seconds,
            "min_coverage_ratio": min_coverage_ratio,
        },
        "summary_store": {
            "row_count": len(rows),
            "filtered_row_count": len(filtered_rows),
            "duplicate_run_ids": duplicate_run_ids(filtered_rows),
        },
        "latest_run": latest_run_metadata(filtered_rows),
        "comparison": report,
    }


def write_dashboard_files(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    automation.write_json(output_dir / DATA_FILENAME, payload)
    write_text(output_dir / INDEX_FILENAME, render_html())


def render_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SiliconBoutique Metrics Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17202a;
      --muted: #667085;
      --line: #d7dee8;
      --panel: #ffffff;
      --page: #f5f7fa;
      --accent: #0f766e;
      --accent-2: #2563eb;
      --warn: #a8550d;
      --bad: #b42318;
      --soft: #e6f3f1;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--page);
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    header, main { width: min(1180px, calc(100% - 32px)); margin: 0 auto; }
    header { padding: 28px 0 18px; }
    h1 { margin: 0; font-size: 1.85rem; font-weight: 740; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 1.05rem; letter-spacing: 0; }
    h3 { margin: 0 0 8px; font-size: 0.95rem; letter-spacing: 0; }
    section { margin: 16px 0; }
    .subtle { color: var(--muted); font-size: 0.92rem; }
    .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
    .wide-grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }
    .metric-card { min-height: 128px; display: flex; flex-direction: column; justify-content: space-between; }
    .metric-label { color: var(--muted); font-size: 0.8rem; text-transform: uppercase; }
    .metric-value { margin-top: 4px; font-size: 1.38rem; font-weight: 740; overflow-wrap: anywhere; }
    .meta-line { color: var(--muted); font-size: 0.86rem; overflow-wrap: anywhere; }
    .bar-track { height: 8px; width: 100%; border-radius: 999px; background: #e8edf3; overflow: hidden; margin-top: 12px; }
    .bar-fill { height: 100%; width: 0%; border-radius: inherit; background: var(--accent); }
    .bar-fill.blue { background: var(--accent-2); }
    .bar-fill.warn { background: var(--warn); }
    .status { display: inline-flex; align-items: center; border-radius: 999px; padding: 2px 8px; font-size: 0.8rem; font-weight: 650; }
    .status-pass { color: #075841; background: #dff5ed; }
    .status-warn { color: #774500; background: #fff1d1; }
    .status-fail { color: #8f1d1d; background: #ffe2e2; }
    .status-complete { color: #075841; background: #dff5ed; }
    .status-partial { color: #774500; background: #fff1d1; }
    .table-wrap { overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 0.78rem; text-transform: uppercase; background: #fbfcfe; }
    tr:last-child td { border-bottom: 0; }
    .rank { color: var(--accent); font-weight: 760; }
    .warn-text { color: var(--warn); }
    .bad-text { color: var(--bad); }
    .empty { background: var(--soft); border: 1px solid var(--line); border-radius: 8px; padding: 14px; color: var(--muted); }
    .group-card { display: grid; gap: 10px; }
    .group-title { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
    .group-title strong { overflow-wrap: anywhere; }
    .mini-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .mini { background: #f8fafc; border: 1px solid #e5eaf1; border-radius: 8px; padding: 8px; }
    .mini span { display: block; color: var(--muted); font-size: 0.76rem; text-transform: uppercase; }
    .mini strong { display: block; margin-top: 2px; overflow-wrap: anywhere; }
    .ranking-row { display: grid; grid-template-columns: 32px minmax(0, 1fr) 88px; gap: 8px; align-items: center; margin: 8px 0; }
    .ranking-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ranking-value { text-align: right; font-variant-numeric: tabular-nums; }
    .ranking-bar { grid-column: 2 / 4; height: 7px; border-radius: 999px; background: #e8edf3; overflow: hidden; }
    .ranking-bar div { height: 100%; background: var(--accent-2); border-radius: inherit; }
    @media (max-width: 640px) {
      header, main { width: min(100% - 20px, 1180px); }
      table { min-width: 620px; }
      .mini-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>SiliconBoutique Metrics Dashboard</h1>
    <div id="generated" class="subtle"></div>
  </header>
  <main>
    <section>
      <div id="overview" class="grid"></div>
    </section>
    <section>
      <h2>Latest Run</h2>
      <div id="latest" class="grid"></div>
    </section>
    <section>
      <h2>Run Metrics</h2>
      <div id="metric-cards" class="grid"></div>
    </section>
    <section>
      <h2>Comparison Groups</h2>
      <div id="groups"></div>
    </section>
    <section>
      <h2>Rankings</h2>
      <div id="rankings" class="wide-grid"></div>
    </section>
    <section>
      <h2>Warnings</h2>
      <div id="warnings"></div>
    </section>
    <section>
      <h2>Rejected Runs</h2>
      <div id="rejected"></div>
    </section>
  </main>
  <script>
    const metricLabels = {
      avg_requests_per_second: "Avg RPS",
      requests_per_cpu_core: "Requests / CPU Core",
      metrics_coverage_ratio: "Coverage",
      frontend_latency_p99_ms: "P99 Latency ms",
      max_memory_used_gb: "Max Memory GB",
      cost_per_1m_requests_usd: "Cost / 1M Requests",
      request_failure_ratio: "Failure Ratio"
    };
    const latestMetrics = [
      ["Throughput", "avg_requests_per_second", "req/s", "blue"],
      ["Frontend P99 Latency", "frontend_latency_p99_ms", "ms", "warn"],
      ["Avg CPU Utilization", "avg_cpu_utilization_pct", "%", ""],
      ["Max CPU Utilization", "max_cpu_utilization_pct", "%", ""],
      ["Max Memory", "max_memory_used_gb", "GB", "blue"],
      ["Cost / 1M Requests", "cost_per_1m_requests_usd", "USD", "warn"],
      ["Coverage", "metrics_coverage_ratio", "", ""],
      ["Request Failures", "request_failure_count", "", "warn"]
    ];

    const fields = {
      overview: [
        ["Status", data => statusBadge(data.comparison.status)],
        ["Source", data => escapeHtml(data.source.type)],
        ["Rows", data => `${data.summary_store.filtered_row_count} / ${data.summary_store.row_count}`],
        ["Groups", data => data.comparison.comparison_group_count],
        ["Comparable Runs", data => data.comparison.comparable_run_count],
        ["Rejected Runs", data => data.comparison.rejected_runs.length]
      ],
      latest: [
        ["Run ID", run => run?.run_id],
        ["Provider", run => run?.cloud_provider],
        ["Machine", run => run?.machine_type],
        ["Processor", run => run?.processor_family],
        ["Architecture", run => run?.architecture],
        ["Summary", run => statusBadge(run?.summary_status, "summary")],
        ["Avg RPS", run => formatNumber(run?.metrics?.avg_requests_per_second)],
        ["P99 Latency", run => formatNumber(run?.metrics?.frontend_latency_p99_ms)]
      ]
    };

    fetch("dashboard-data.json")
      .then(response => response.json())
      .then(render)
      .catch(error => {
        document.querySelector("main").innerHTML = `<div class="empty">Unable to load dashboard data: ${escapeHtml(error.message)}</div>`;
      });

    function render(data) {
      document.getElementById("generated").textContent = `Generated ${data.generated_at} from ${sourceLabel(data.source)}`;
      renderCards("overview", fields.overview.map(([label, getter]) => [label, getter(data)]));
      renderCards("latest", fields.latest.map(([label, getter]) => [label, getter(data.latest_run)]));
      renderMetricCards(data.latest_run);
      renderGroups(data.comparison.comparison_groups);
      renderRankings(data.comparison.rankings);
      renderWarnings(data.comparison.warnings);
      renderRejected(data.comparison.rejected_runs, data.summary_store.duplicate_run_ids);
    }

    function renderCards(id, pairs) {
      document.getElementById(id).innerHTML = pairs.map(([label, value]) => `
        <article class="card">
          <div class="metric-label">${escapeHtml(label)}</div>
          <div class="metric-value">${value ?? ""}</div>
        </article>
      `).join("");
    }

    function renderMetricCards(run) {
      if (!run) {
        document.getElementById("metric-cards").innerHTML = `<div class="empty">No latest run metrics.</div>`;
        return;
      }
      const metrics = run.metrics || {};
      document.getElementById("metric-cards").innerHTML = latestMetrics.map(([label, field, suffix, color]) => {
        const raw = metrics[field];
        const value = formatMetric(raw, suffix);
        const percent = metricPercent(field, raw);
        return `<article class="card metric-card">
          <div>
            <div class="metric-label">${escapeHtml(label)}</div>
            <div class="metric-value">${escapeHtml(value || "n/a")}</div>
          </div>
          <div class="bar-track"><div class="bar-fill ${color}" style="width: ${percent}%"></div></div>
        </article>`;
      }).join("");
    }

    function renderGroups(groups) {
      if (!groups.length) {
        document.getElementById("groups").innerHTML = `<div class="empty">No comparable groups.</div>`;
        return;
      }
      const cards = groups.map(group => {
        const meta = group.metadata;
        const metrics = group.metrics;
        return `<article class="card group-card">
          <div class="group-title">
            <strong>${escapeHtml(meta.machine_type)} · ${escapeHtml(meta.processor_family)}</strong>
            <span class="status status-pass">${group.run_count} run${group.run_count === 1 ? "" : "s"}</span>
          </div>
          <div class="meta-line">${escapeHtml(meta.cloud_provider)} / ${escapeHtml(meta.region)} / ${escapeHtml(meta.architecture)} / ${escapeHtml(meta.pricing_model)}</div>
          <div class="mini-grid">
            ${mini("Throughput", formatMetric(metrics.avg_requests_per_second, "req/s"))}
            ${mini("P99 Latency", formatMetric(metrics.frontend_latency_p99_ms, "ms"))}
            ${mini("CPU Utilization", formatMetric(metrics.avg_cpu_utilization_pct, "%"))}
            ${mini("Memory", formatMetric(metrics.max_memory_used_gb, "GB"))}
            ${mini("Cost / 1M", formatMetric(metrics.cost_per_1m_requests_usd, "USD"))}
            ${mini("Coverage", formatMetric(metrics.metrics_coverage_ratio, ""))}
          </div>
        </article>`;
      }).join("");
      document.getElementById("groups").innerHTML = `<div class="wide-grid">${cards}</div>`;
    }

    function renderRankings(rankings) {
      const panels = Object.entries(rankings).map(([metric, entries]) => {
        if (!entries.length) {
          return "";
        }
        const values = entries.map(entry => Math.abs(Number(entry.value)) || 0);
        const max = Math.max(...values, 1);
        const items = entries.slice(0, 5).map(entry => {
          const width = Math.max(4, Math.round(((Math.abs(Number(entry.value)) || 0) / max) * 100));
          return `<div class="ranking-row">
            <div class="rank">${entry.rank}</div>
            <div class="ranking-name" title="${escapeHtml(entry.machine_type)}">${escapeHtml(entry.machine_type)}</div>
            <div class="ranking-value">${formatNumber(entry.value)}</div>
            <div class="ranking-bar"><div style="width: ${width}%"></div></div>
          </div>`;
        }).join("");
        return `<article class="card">
          <h2>${escapeHtml(metricLabels[metric] || metric)}</h2>
          ${items}
        </article>`;
      }).join("");
      document.getElementById("rankings").innerHTML = panels || `<div class="empty">No rankings available.</div>`;
    }

    function renderWarnings(warnings) {
      if (!warnings.length) {
        document.getElementById("warnings").innerHTML = `<div class="empty">No warnings.</div>`;
        return;
      }
      const rows = warnings.map(item => `<tr>
        <td>${escapeHtml(item.group_id || "")}</td>
        <td class="warn-text">${escapeHtml(item.reason || "")}</td>
        <td>${escapeHtml((item.run_ids || []).join(", "))}</td>
      </tr>`).join("");
      document.getElementById("warnings").innerHTML = table(["Group", "Reason", "Run IDs"], rows);
    }

    function renderRejected(rejected, duplicates) {
      const duplicateRows = duplicates.map(runId => `<tr><td>${escapeHtml(runId)}</td><td>duplicate_run_id</td></tr>`).join("");
      const rejectedRows = rejected.map(item => `<tr><td>${escapeHtml(item.run_id)}</td><td class="bad-text">${escapeHtml((item.reasons || []).join(", "))}</td></tr>`).join("");
      const rows = duplicateRows + rejectedRows;
      document.getElementById("rejected").innerHTML = rows ? table(["Run ID", "Reasons"], rows) : `<div class="empty">No rejected runs.</div>`;
    }

    function mini(label, value) {
      return `<div class="mini"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "n/a")}</strong></div>`;
    }

    function table(headers, rows) {
      return `<div class="table-wrap"><table><thead><tr>${headers.map(header => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
    }

    function statusBadge(status, kind = "report") {
      const value = status || "unknown";
      const className = kind === "summary" ? `status-${escapeHtml(value)}` : `status-${escapeHtml(value)}`;
      return `<span class="status ${className}">${escapeHtml(value)}</span>`;
    }

    function sourceLabel(source) {
      if (source.summary_store) return source.summary_store;
      if (source.summary_table) return source.summary_table;
      return source.type;
    }

    function formatMetric(value, suffix) {
      const formatted = formatNumber(value);
      if (!formatted) return "";
      if (suffix === "USD") return `$${formatted}`;
      return suffix ? `${formatted} ${suffix}` : formatted;
    }

    function formatNumber(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
      return Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 });
    }

    function metricPercent(field, value) {
      const number = Number(value);
      if (!Number.isFinite(number) || number <= 0) return 0;
      if (field.includes("utilization")) return clamp(number, 0, 100);
      if (field === "metrics_coverage_ratio") return clamp(number * 100, 0, 100);
      if (field === "request_failure_count") return clamp(number, 0, 100);
      return clamp(Math.log10(number + 1) * 25, 4, 100);
    }

    function clamp(value, min, max) {
      return Math.max(min, Math.min(max, value));
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[char]);
    }
  </script>
</body>
</html>
"""


def latest_run_metadata(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest = latest_row(rows)
    if latest is None:
        return None
    return {
        **{field: latest.get(field) for field in LATEST_FIELDS},
        "metrics": {field: latest.get(field) for field in LATEST_METRIC_FIELDS},
    }


def latest_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda row: str(row.get("benchmark_start") or ""))


def duplicate_run_ids(rows: list[dict[str, Any]]) -> list[str]:
    counts = Counter(str(row.get("run_id")) for row in rows if row.get("run_id"))
    return sorted(run_id for run_id, count in counts.items() if count > 1)


def filter_values(args: argparse.Namespace) -> dict[str, str]:
    return {
        field: value
        for field, value in (
            ("machine_type", args.machine_type),
            ("processor_family", args.processor_family),
            ("architecture", args.architecture),
            ("cloud_provider", args.cloud_provider),
            ("pricing_model", args.pricing_model),
        )
        if value is not None
    }


def create_server(
    output_dir: Path, *, host: str, port: int
) -> tuple[ThreadingHTTPServer, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(QuietDashboardHandler, directory=str(output_dir))
    last_error: OSError | None = None
    candidates = [port] if port == 0 else range(port, min(port + 50, 65536))
    for candidate in candidates:
        try:
            server = ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            last_error = exc
            continue
        actual_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
        actual_port = int(server.server_address[1])
        return server, f"http://{actual_host}:{actual_port}/{INDEX_FILENAME}"
    raise DashboardLaunchError(
        f"could not bind dashboard server on {host}:{port}"
        + (f" ({last_error})" if last_error else "")
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
