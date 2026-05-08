output "project_id" {
  description = "GCP project ID for durable benchmark summary history."
  value       = var.project_id
}

output "dataset_id" {
  description = "BigQuery dataset ID for durable benchmark summary history."
  value       = google_bigquery_dataset.benchmark_history.dataset_id
}

output "table_id" {
  description = "BigQuery table ID for canonical BenchmarkSummary rows."
  value       = google_bigquery_table.benchmark_summaries.table_id
}

output "dataset_location" {
  description = "BigQuery dataset location."
  value       = google_bigquery_dataset.benchmark_history.location
}

output "summary_table" {
  description = "Fully-qualified BigQuery summary table."
  value       = "${var.project_id}.${google_bigquery_dataset.benchmark_history.dataset_id}.${google_bigquery_table.benchmark_summaries.table_id}"
}

output "labels" {
  description = "Labels applied to durable BigQuery resources."
  value       = local.labels
}
