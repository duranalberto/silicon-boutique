variable "static_validation_mode" {
  description = "Use fake AWS credentials and skip provider account checks so static plan validation can run without AWS access. Set false for real cloud plan/apply/destroy."
  type        = bool
  default     = true
}

variable "run_id" {
  description = "Optional benchmark run identifier. When omitted, Terraform generates a stable AWS run ID."
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
  description = "Benchmark environment. The AWS EKS scaffold only supports aws."
  type        = string
  default     = "aws"

  validation {
    condition     = var.environment == "aws"
    error_message = "environment must be aws for the AWS EKS Terraform path."
  }
}

variable "region" {
  description = "AWS region for the benchmark EKS scaffold."
  type        = string
  default     = "us-east-1"

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
  description = "Primary AWS availability zone metadata for benchmark comparison."
  type        = string
  default     = "us-east-1a"

  validation {
    condition = (
      length(trimspace(var.zone)) > 0 &&
      length(var.zone) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.zone))
    )
    error_message = "zone must be a non-empty lowercase DNS-safe value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "secondary_zone" {
  description = "Secondary AWS availability zone used by the scaffolded EKS subnet set."
  type        = string
  default     = "us-east-1b"

  validation {
    condition = (
      length(trimspace(var.secondary_zone)) > 0 &&
      length(var.secondary_zone) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.secondary_zone))
    )
    error_message = "secondary_zone must be a non-empty lowercase DNS-safe value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "cluster_name" {
  description = "Optional EKS cluster name. When omitted, it is derived from run_id."
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

variable "machine_type" {
  description = "EC2 instance type for the scaffolded benchmark EKS node group."
  type        = string
  default     = "m7i.xlarge"

  validation {
    condition = (
      length(trimspace(var.machine_type)) > 0 &&
      length(var.machine_type) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.machine_type))
    )
    error_message = "machine_type must be a non-empty EC2 instance type value up to 63 characters using lowercase letters, numbers, dots, and dashes."
  }
}

variable "node_count" {
  description = "Number of nodes in the benchmark EKS managed node group."
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
  default     = "m7i"

  validation {
    condition = (
      length(trimspace(var.processor_family)) > 0 &&
      length(var.processor_family) <= 63 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.processor_family))
    )
    error_message = "processor_family must be a non-empty lowercase DNS-safe label value up to 63 characters using only letters, numbers, and dashes."
  }
}

variable "cpu_platform" {
  description = "Optional provider-specific CPU platform metadata for benchmark comparison."
  type        = string
  default     = null

  validation {
    condition = var.cpu_platform == null || (
      length(trimspace(var.cpu_platform)) > 0 &&
      length(var.cpu_platform) <= 63
    )
    error_message = "cpu_platform must be null or a non-empty value up to 63 characters."
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

variable "pricing_model" {
  description = "Pricing model metadata used by benchmark cost calculations."
  type        = string
  default     = "spot"

  validation {
    condition     = contains(["spot", "on_demand"], var.pricing_model)
    error_message = "pricing_model must be spot or on_demand for the AWS EKS scaffold."
  }
}

variable "enable_spot_nodes" {
  description = "Whether the benchmark managed node group should request Spot capacity."
  type        = bool
  default     = true
}

variable "cluster_version" {
  description = "EKS control plane Kubernetes version for the scaffolded cluster."
  type        = string
  default     = "1.31"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+$", var.cluster_version))
    error_message = "cluster_version must use major.minor format, such as 1.31."
  }
}

variable "disk_size_gb" {
  description = "EBS root volume size in GB for each scaffolded worker node."
  type        = number
  default     = 50

  validation {
    condition     = var.disk_size_gb >= 20
    error_message = "disk_size_gb must be at least 20."
  }
}
