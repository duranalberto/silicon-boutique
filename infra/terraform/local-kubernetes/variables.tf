variable "run_id" {
  description = "Optional benchmark run identifier. When omitted, Terraform generates a stable local run ID."
  type        = string
  default     = null

  validation {
    condition = var.run_id == null || (
      length(trimspace(var.run_id)) > 0 &&
      length(var.run_id) <= 46 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.run_id))
    )
    error_message = "run_id must be null or a non-empty lowercase DNS-safe value up to 46 characters using only letters, numbers, and dashes."
  }
}

variable "kubeconfig_path" {
  description = "Path to the kubeconfig file containing the local Kubernetes context."
  type        = string
  default     = "~/.kube/config"

  validation {
    condition     = length(trimspace(var.kubeconfig_path)) > 0
    error_message = "kubeconfig_path must not be empty."
  }
}

variable "kube_context" {
  description = "Existing kubeconfig context for the devcontainer-managed local Kubernetes cluster."
  type        = string
  default     = "siliconboutique"

  validation {
    condition     = length(trimspace(var.kube_context)) > 0
    error_message = "kube_context must not be empty."
  }
}

variable "namespace" {
  description = "Optional namespace for the local benchmark run. When omitted, it is derived from run_id."
  type        = string
  default     = null

  validation {
    condition = var.namespace == null || (
      length(trimspace(var.namespace)) > 0 &&
      length(var.namespace) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace))
    )
    error_message = "namespace must be null or a non-empty lowercase DNS-safe name up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "environment" {
  description = "Benchmark environment. The local Kubernetes path only supports local."
  type        = string
  default     = "local"

  validation {
    condition     = var.environment == "local"
    error_message = "environment must be local for the local Kubernetes Terraform path."
  }
}

variable "machine_type" {
  description = "Machine type metadata kept for parity with the future GCP rollout path."
  type        = string
  default     = "local"

  validation {
    condition = (
      length(trimspace(var.machine_type)) > 0 &&
      length(var.machine_type) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.machine_type))
    )
    error_message = "machine_type must be a non-empty lowercase DNS-safe label value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "region" {
  description = "Region metadata kept for parity with the future GCP rollout path."
  type        = string
  default     = "local"

  validation {
    condition = (
      length(trimspace(var.region)) > 0 &&
      length(var.region) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.region))
    )
    error_message = "region must be a non-empty lowercase DNS-safe value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "node_count" {
  description = "Node count metadata kept for parity with the future GCP rollout path."
  type        = number
  default     = 1

  validation {
    condition     = var.node_count >= 1
    error_message = "node_count must be at least 1."
  }
}

variable "processor_family" {
  description = "Processor family metadata kept for parity with the future GCP rollout path."
  type        = string
  default     = "local"

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
  description = "Processor architecture metadata kept for parity with the future GCP rollout path."
  type        = string
  default     = "x86_64"

  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be either x86_64 or arm64."
  }
}
