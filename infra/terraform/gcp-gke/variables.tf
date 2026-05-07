variable "project_id" {
  description = "GCP project ID where the ephemeral GKE benchmark resources will be created."
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
  description = "Use a fake provider access token so terraform plan -refresh=false can run without GCP credentials. Set false for real cloud plan/apply/destroy."
  type        = bool
  default     = true
}

variable "run_id" {
  description = "Optional benchmark run identifier. When omitted, Terraform generates a stable GCP run ID."
  type        = string
  default     = null

  validation {
    condition = var.run_id == null || (
      length(trimspace(var.run_id)) > 0 &&
      length(var.run_id) <= 30 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.run_id))
    )
    error_message = "run_id must be null or a non-empty lowercase DNS-safe value up to 30 characters using only letters, numbers, and dashes."
  }
}

variable "environment" {
  description = "Benchmark environment. The GCP rollout path only supports gcp."
  type        = string
  default     = "gcp"

  validation {
    condition     = var.environment == "gcp"
    error_message = "environment must be gcp for the GCP GKE Terraform path."
  }
}

variable "region" {
  description = "GCP region for regional resources such as the subnet."
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

variable "zone" {
  description = "GCP zone for the initial GKE cluster path."
  type        = string
  default     = "us-central1-a"

  validation {
    condition = (
      length(trimspace(var.zone)) > 0 &&
      length(var.zone) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.zone))
    )
    error_message = "zone must be a non-empty lowercase DNS-safe value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "cluster_name" {
  description = "Optional GKE cluster name. When omitted, it is derived from run_id."
  type        = string
  default     = null

  validation {
    condition = var.cluster_name == null || (
      length(trimspace(var.cluster_name)) > 0 &&
      length(var.cluster_name) <= 40 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.cluster_name))
    )
    error_message = "cluster_name must be null or a non-empty lowercase DNS-safe name up to 40 characters using only letters, numbers, and dashes."
  }
}

variable "network_name" {
  description = "Optional VPC network name. When omitted, it is derived from run_id."
  type        = string
  default     = null

  validation {
    condition = var.network_name == null || (
      length(trimspace(var.network_name)) > 0 &&
      length(var.network_name) <= 40 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.network_name))
    )
    error_message = "network_name must be null or a non-empty lowercase DNS-safe name up to 40 characters using only letters, numbers, and dashes."
  }
}

variable "subnet_name" {
  description = "Optional subnet name. When omitted, it is derived from run_id."
  type        = string
  default     = null

  validation {
    condition = var.subnet_name == null || (
      length(trimspace(var.subnet_name)) > 0 &&
      length(var.subnet_name) <= 40 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.subnet_name))
    )
    error_message = "subnet_name must be null or a non-empty lowercase DNS-safe name up to 40 characters using only letters, numbers, and dashes."
  }
}

variable "machine_type" {
  description = "GCE machine type for the benchmark GKE node pool."
  type        = string
  default     = "e2-standard-4"

  validation {
    condition = (
      length(trimspace(var.machine_type)) > 0 &&
      length(var.machine_type) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.machine_type))
    )
    error_message = "machine_type must be a non-empty lowercase DNS-safe label value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "node_count" {
  description = "Number of nodes in the benchmark GKE node pool."
  type        = number
  default     = 1

  validation {
    condition     = var.node_count >= 1
    error_message = "node_count must be at least 1."
  }
}

variable "processor_family" {
  description = "Processor family metadata for benchmark comparison."
  type        = string
  default     = "e2"

  validation {
    condition = (
      length(trimspace(var.processor_family)) > 0 &&
      length(var.processor_family) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.processor_family))
    )
    error_message = "processor_family must be a non-empty lowercase DNS-safe label value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "architecture" {
  description = "Processor architecture metadata for benchmark comparison."
  type        = string
  default     = "x86_64"

  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be either x86_64 or arm64."
  }
}

variable "enable_spot_nodes" {
  description = "Whether the benchmark node pool should use GKE Spot VMs."
  type        = bool
  default     = true
}

variable "disk_size_gb" {
  description = "Boot disk size in GB for each GKE node."
  type        = number
  default     = 50

  validation {
    condition     = var.disk_size_gb >= 20
    error_message = "disk_size_gb must be at least 20."
  }
}

variable "release_channel" {
  description = "GKE release channel for the ephemeral benchmark cluster."
  type        = string
  default     = "REGULAR"

  validation {
    condition     = contains(["RAPID", "REGULAR", "STABLE"], var.release_channel)
    error_message = "release_channel must be RAPID, REGULAR, or STABLE."
  }
}
