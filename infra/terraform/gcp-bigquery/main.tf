locals {
  labels = {
    app        = "silicon-boutique"
    managed_by = "terraform"
    purpose    = "benchmark_history"
  }

  summary_writer_service_accounts = toset(var.summary_writer_service_accounts)
}

resource "google_bigquery_dataset" "benchmark_history" {
  dataset_id                 = var.dataset_id
  friendly_name              = "SiliconBoutique benchmark history"
  description                = "Durable SiliconBoutique benchmark summary history for cross-run processor comparison."
  location                   = var.dataset_location
  labels                     = local.labels
  delete_contents_on_destroy = false
}

resource "google_bigquery_table" "benchmark_summaries" {
  dataset_id          = google_bigquery_dataset.benchmark_history.dataset_id
  table_id            = var.table_id
  description         = "Canonical SiliconBoutique BenchmarkSummary rows."
  deletion_protection = true
  labels              = local.labels

  schema = file("${path.module}/../../../automation/templates/benchmark-summary.bigquery-schema.json")

  time_partitioning {
    type  = "DAY"
    field = "benchmark_start"
  }

  clustering = [
    "machine_type",
    "processor_family",
    "architecture",
    "run_id",
  ]
}

resource "google_project_iam_member" "summary_writer_job_user" {
  for_each = local.summary_writer_service_accounts

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${each.value}"
}

resource "google_bigquery_dataset_iam_member" "summary_writer_data_editor" {
  for_each = local.summary_writer_service_accounts

  dataset_id = google_bigquery_dataset.benchmark_history.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${each.value}"
}
