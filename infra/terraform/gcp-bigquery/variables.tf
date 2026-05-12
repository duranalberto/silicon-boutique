variable "project_id" {
  description = "GCP project ID where durable benchmark summary history will be stored."
  type        = string

  validation {
    condition = (
      length(trimspace(var.project_id)) >= 6 &&
      length(var.project_id) <= 30 &&
      can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.project_id))
    )
    error_message = "project_id must be a non-empty GCP project ID: 6-30 lowercase letters, numbers, and dashes, starting with a letter and ending with a letter or number."
  }
}

variable "static_validation_mode" {
  description = "Use a fake provider access token so terraform plan -refresh=false can run without GCP credentials. Set false for real cloud plan/apply."
  type        = bool
  default     = true
}

variable "region" {
  description = "Default provider region used for validation. BigQuery dataset placement is controlled by dataset_location."
  type        = string
  default     = "us-central1"

  validation {
    condition = (
      length(trimspace(var.region)) > 0 &&
      length(var.region) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.region))
    )
    error_message = "region must be a non-empty lowercase DNS-safe value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "dataset_id" {
  description = "Durable BigQuery dataset ID for benchmark summary history."
  type        = string
  default     = "silicon_boutique"

  validation {
    condition = (
      length(trimspace(var.dataset_id)) > 0 &&
      length(var.dataset_id) <= 1024 &&
      can(regex("^[A-Za-z_][A-Za-z0-9_]*$", var.dataset_id))
    )
    error_message = "dataset_id must be a valid BigQuery dataset ID using letters, numbers, and underscores, and must not start with a number."
  }
}

variable "table_id" {
  description = "Durable BigQuery table ID for canonical BenchmarkSummary rows."
  type        = string
  default     = "benchmark_summaries"

  validation {
    condition = (
      length(trimspace(var.table_id)) > 0 &&
      length(var.table_id) <= 1024 &&
      can(regex("^[A-Za-z_][A-Za-z0-9_]*$", var.table_id))
    )
    error_message = "table_id must be a valid BigQuery table ID using letters, numbers, and underscores, and must not start with a number."
  }
}

variable "dataset_location" {
  description = "BigQuery dataset location. Keep this aligned with workflow bigquery_location inputs."
  type        = string
  default     = "US"

  validation {
    condition = (
      length(trimspace(var.dataset_location)) > 0 &&
      length(var.dataset_location) <= 32 &&
      can(regex("^[A-Za-z0-9-]+$", var.dataset_location))
    )
    error_message = "dataset_location must be a non-empty BigQuery location value."
  }
}

variable "summary_writer_service_accounts" {
  description = "Service account emails allowed to run benchmark summary load jobs against the durable BigQuery dataset."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for service_account in var.summary_writer_service_accounts :
      can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.iam\\.gserviceaccount\\.com$", service_account))
    ])
    error_message = "summary_writer_service_accounts must contain service account email addresses, without the serviceAccount: prefix."
  }
}
