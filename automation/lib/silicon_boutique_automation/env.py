"""Environment and BigQuery configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BigQuerySettings:
    """Container for big Query Settings state and behavior.


    Attributes:
        project_id: project ID (str) stored on the object.
        dataset: dataset (str) stored on the object.
        table: table (str) stored on the object.
        location: location (str) stored on the object.
    """
    project_id: str
    dataset: str
    table: str
    location: str

    @property
    def configured(self) -> bool:
        """Compute configured.


        Returns:
            bool value produced by configured.
        """
        return bool(self.project_id and self.dataset and self.table and self.location)

    def missing_fields(self) -> list[str]:
        """Compute missing fields.


        Returns:
            list[str] value produced by missing fields.
        """
        fields = {
            "project_id": self.project_id,
            "dataset": self.dataset,
            "table": self.table,
            "location": self.location,
        }
        return [name for name, value in fields.items() if not value]


def read_env_file(path: Path | None) -> dict[str, str]:
    """Read environment file.


    Args:
        path: path (Path | None) used by this operation.

    Returns:
        dict[str, str] value produced by read environment file.
    """
    if path is None or not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = unquote_env_value(value.strip())
        if key:
            values[key] = value
    return values


def unquote_env_value(value: str) -> str:
    """Compute unquote environment value.


    Args:
        value: value (str) used by this operation.

    Returns:
        str value produced by unquote environment value.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def resolve_bigquery_settings(
    *,
    env_values: dict[str, str],
    environ: dict[str, str],
    project_id_override: str | None = None,
    dataset_override: str | None = None,
    table_override: str | None = None,
    location_override: str | None = None,
) -> BigQuerySettings:
    """Compute resolve BigQuery settings.


    Args:
        env_values: environment values (dict[str, str]) used by this operation.
        environ: environ (dict[str, str]) used by this operation.
        project_id_override: project ID override (str | None) used by this operation.
        dataset_override: dataset override (str | None) used by this operation.
        table_override: table override (str | None) used by this operation.
        location_override: location override (str | None) used by this operation.

    Returns:
        BigQuerySettings value produced by resolve BigQuery settings.
    """
    def value(override: str | None, *names: str) -> str:
        """Compute value.


        Args:
            override: override (str | None) used by this operation.
            names: names (str) used by this operation.

        Returns:
            str value produced by value.
        """
        if override:
            return override.strip()
        for name in names:
            existing = environ.get(name, "").strip()
            if existing:
                return existing
        for name in names:
            file_value = env_values.get(name, "").strip()
            if file_value:
                return file_value
        return ""

    return BigQuerySettings(
        project_id=value(project_id_override, "BIGQUERY_PROJECT_ID", "PROJECT_ID"),
        dataset=value(dataset_override, "BIGQUERY_DATASET"),
        table=value(table_override, "BIGQUERY_TABLE"),
        location=value(location_override, "BIGQUERY_LOCATION"),
    )


def env_presence(env_values: dict[str, str], environ: dict[str, str]) -> dict[str, bool]:
    """Compute environment presence.


    Args:
        env_values: environment values (dict[str, str]) used by this operation.
        environ: environ (dict[str, str]) used by this operation.

    Returns:
        dict[str, bool] value produced by environment presence.
    """
    keys = set(env_values) | {
        "PROJECT_ID",
        "BIGQUERY_PROJECT_ID",
        "BIGQUERY_DATASET",
        "BIGQUERY_TABLE",
        "BIGQUERY_LOCATION",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GITHUB_TOKEN",
    }
    return {key: bool(environ.get(key) or env_values.get(key)) for key in sorted(keys)}
