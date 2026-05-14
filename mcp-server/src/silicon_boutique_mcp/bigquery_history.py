"""BigQuery-backed historical benchmark summary queries."""

from __future__ import annotations

import os
from dataclasses import dataclass

from silicon_boutique_mcp.fixtures import summary_reference_from_row
from silicon_boutique_mcp.models import BenchmarkSummaryReference
from silicon_boutique_shared import bigquery as bq_helpers
from silicon_boutique_shared.automation import first_env


DEFAULT_BIGQUERY_DATASET = "silicon_boutique"
DEFAULT_BIGQUERY_TABLE = "benchmark_summaries"
DEFAULT_BIGQUERY_LOCATION = "US"
HISTORY_FIELDS = (
    "run_id",
    "machine_type",
    "processor_family",
    "architecture",
    "cloud_provider",
    "region",
    "zone",
    "node_count",
    "pricing_model",
    "summary_status",
    "cpu_platform",
    "benchmark_start",
    "benchmark_end",
    "avg_cpu_usage_cores",
    "max_cpu_usage_cores",
    "avg_cpu_utilization_pct",
    "max_cpu_utilization_pct",
    "max_memory_used_gb",
    "frontend_latency_p50_ms",
    "frontend_latency_p95_ms",
    "frontend_latency_p99_ms",
    "frontend_latency_max_ms",
    "request_count_total",
    "request_success_count",
    "request_failure_count",
    "avg_requests_per_second",
    "load_concurrent_users",
    "load_users_per_second",
    "load_profile_source",
    "node_hourly_price_usd",
    "benchmark_compute_cost_usd",
    "cost_per_1m_requests_usd",
    "metrics_coverage_ratio",
    "missing_metrics",
    "empty_metrics",
)


class BigQueryHistoryError(ValueError):
    """Raised when historical BigQuery queries cannot be completed safely."""


CommandResult = bq_helpers.CommandResult
Runner = bq_helpers.Runner


@dataclass(frozen=True, slots=True)
class BigQueryHistoryConfig:
    """BigQuery destination for benchmark summary history."""

    project_id: str
    dataset_id: str = DEFAULT_BIGQUERY_DATASET
    table_id: str = DEFAULT_BIGQUERY_TABLE
    location: str = DEFAULT_BIGQUERY_LOCATION
    bq_command: str = "bq"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> BigQueryHistoryConfig:
        """Compute from environment.


        Args:
            env: environment (dict[str, str] | None) used by this operation.

        Returns:
            BigQueryHistoryConfig value produced by from environment.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        values = env if env is not None else os.environ
        project_id = first_env(
            values,
            "SILICON_BOUTIQUE_BIGQUERY_PROJECT_ID",
            "GOOGLE_CLOUD_PROJECT",
        )
        if not project_id:
            raise BigQueryHistoryError(
                "SILICON_BOUTIQUE_BIGQUERY_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required"
            )
        config = cls(
            project_id=project_id,
            dataset_id=values.get(
                "SILICON_BOUTIQUE_BIGQUERY_DATASET",
                DEFAULT_BIGQUERY_DATASET,
            ).strip()
            or DEFAULT_BIGQUERY_DATASET,
            table_id=values.get(
                "SILICON_BOUTIQUE_BIGQUERY_TABLE",
                DEFAULT_BIGQUERY_TABLE,
            ).strip()
            or DEFAULT_BIGQUERY_TABLE,
            location=values.get(
                "SILICON_BOUTIQUE_BIGQUERY_LOCATION",
                DEFAULT_BIGQUERY_LOCATION,
            ).strip()
            or DEFAULT_BIGQUERY_LOCATION,
            bq_command=values.get("SILICON_BOUTIQUE_BQ_COMMAND", "bq").strip()
            or "bq",
        )
        validate_destination(config)
        return config

    @property
    def table_sql_name(self) -> str:
        """Compute table SQL name.


        Returns:
            str value produced by table SQL name.
        """
        return f"{self.project_id}.{self.dataset_id}.{self.table_id}"


class BigQueryHistoryStore:
    """Container for big Query History Store state and behavior.
    """

    def __init__(
        self,
        config: BigQueryHistoryConfig,
        runner: Runner | None = None,
    ):
        """Initialize the object with the provided configuration.


        Args:
            config: config (BigQueryHistoryConfig) used by this operation.
            runner: runner (Runner | None) used by this operation.

        Returns:
            None.
        """
        validate_destination(config)
        self.config = config
        self.runner = runner or run_bq

    @classmethod
    def from_env(cls) -> BigQueryHistoryStore:
        """Compute from environment.


        Returns:
            BigQueryHistoryStore value produced by from environment.
        """
        return cls(BigQueryHistoryConfig.from_env())

    def query_historical_metrics(
        self,
        *,
        machine_type: str | None = None,
        processor_family: str | None = None,
        architecture: str | None = None,
        limit: int = 10,
    ) -> list[BenchmarkSummaryReference]:
        """Query historical metrics.


        Args:
            machine_type: machine type (str | None) used by this operation.
            processor_family: processor family (str | None) used by this operation.
            architecture: architecture (str | None) used by this operation.
            limit: limit (int) used by this operation.

        Returns:
            list[BenchmarkSummaryReference] value produced by query historical metrics.

        Raises:
            SystemExit or ValueError when input validation fails.
        """
        query = build_history_query(
            config=self.config,
            filters={
                "machine_type": machine_type,
                "processor_family": processor_family,
                "architecture": architecture,
            },
            limit=limit,
        )
        command = bq_helpers.query_command(
            self.config.project_id,
            self.config.location,
            query,
            bq_command=self.config.bq_command,
        )
        result = self.runner(command)
        if result.returncode != 0:
            raise BigQueryHistoryError(
                "failed to query BigQuery benchmark history: " + result.stderr.strip()
            )
        return summary_references_from_json(result.stdout)


def build_history_query(
    *,
    config: BigQueryHistoryConfig,
    filters: dict[str, str | None],
    limit: int,
) -> str:
    """Build history query.


    Args:
        config: config (BigQueryHistoryConfig) used by this operation.
        filters: filters (dict[str, str | None]) used by this operation.
        limit: limit (int) used by this operation.

    Returns:
        str value produced by build history query.
    """
    validate_destination(config)
    where_parts = [
        f"{field} = {bq_helpers.sql_string(value)}"
        for field, value in filters.items()
        if value is not None
    ]
    query = (
        "SELECT "
        + ", ".join(HISTORY_FIELDS)
        + " FROM "
        + f"`{config.table_sql_name}`"
    )
    if where_parts:
        query += " WHERE " + " AND ".join(where_parts)
    query += " ORDER BY benchmark_start DESC"
    query += f" LIMIT {limit}"
    return query


def summary_references_from_json(payload: str) -> list[BenchmarkSummaryReference]:
    """Compute summary references from JSON.


    Args:
        payload: payload (str) used by this operation.

    Returns:
        list[BenchmarkSummaryReference] value produced by summary references from JSON.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        rows = bq_helpers.parse_bq_json_array(payload)
    except bq_helpers.BigQueryHelperError as exc:
        raise BigQueryHistoryError(str(exc)) from exc
    return [
        summary_reference_from_row(row)
        for row in rows
    ]


def validate_destination(config: BigQueryHistoryConfig) -> None:
    """Validate destination.


    Args:
        config: config (BigQueryHistoryConfig) used by this operation.

    Returns:
        None.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        bq_helpers.validate_destination(
            config.project_id,
            config.dataset_id,
            config.table_id,
            config.location,
        )
    except bq_helpers.BigQueryHelperError as exc:
        raise BigQueryHistoryError(str(exc)) from exc


def run_bq(command: list[str]) -> CommandResult:
    """Run bigQuery.


    Args:
        command: command (list[str]) used by this operation.

    Returns:
        CommandResult value produced by run bigquery.

    Raises:
        SystemExit or ValueError when input validation fails.
    """
    try:
        return bq_helpers.run_bq(command)
    except bq_helpers.BigQueryHelperError as exc:
        raise BigQueryHistoryError(str(exc)) from exc
