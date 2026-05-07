resource "random_id" "run" {
  count = var.run_id == null ? 1 : 0

  byte_length = 4
  prefix      = "run-"
}

locals {
  run_id             = var.run_id == null ? random_id.run[0].hex : var.run_id
  architecture_label = replace(var.architecture, "_", "-")
  name_prefix        = "sb-${local.run_id}"
  cluster_name       = var.cluster_name == null ? local.name_prefix : var.cluster_name
  network_name       = var.network_name == null ? "${local.name_prefix}-vpc" : var.network_name
  subnet_name        = var.subnet_name == null ? "${local.name_prefix}-subnet" : var.subnet_name

  labels = {
    app              = "silicon-boutique"
    environment      = var.environment
    run_id           = local.run_id
    machine_type     = var.machine_type
    processor_family = var.processor_family
    architecture     = local.architecture_label
    managed_by       = "terraform"
    teardown_rule    = "destroy_after_run"
  }

  node_labels = {
    "silicon-boutique/environment"      = var.environment
    "silicon-boutique/run-id"           = local.run_id
    "silicon-boutique/machine-type"     = var.machine_type
    "silicon-boutique/processor-family" = var.processor_family
    "silicon-boutique/architecture"     = local.architecture_label
    "silicon-boutique/teardown-rule"    = "destroy-after-run"
  }
}

resource "google_compute_network" "benchmark" {
  name                    = local.network_name
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Ephemeral SiliconBoutique benchmark network for ${local.run_id}."
}

resource "google_compute_subnetwork" "benchmark" {
  name          = local.subnet_name
  ip_cidr_range = "10.10.0.0/20"
  network       = google_compute_network.benchmark.id
  region        = var.region
  description   = "Ephemeral SiliconBoutique benchmark subnet for ${local.run_id}."

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/16"
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20"
  }
}

resource "google_container_cluster" "benchmark" {
  name                     = local.cluster_name
  location                 = var.zone
  network                  = google_compute_network.benchmark.id
  subnetwork               = google_compute_subnetwork.benchmark.id
  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = false
  networking_mode          = "VPC_NATIVE"
  resource_labels          = local.labels

  release_channel {
    channel = var.release_channel
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "benchmark" {
  name       = "benchmark"
  location   = var.zone
  cluster    = google_container_cluster.benchmark.name
  node_count = var.node_count

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = var.machine_type
    disk_size_gb    = var.disk_size_gb
    disk_type       = "pd-balanced"
    spot            = var.enable_spot_nodes
    labels          = local.node_labels
    resource_labels = local.labels
    tags = [
      "silicon-boutique",
      local.run_id,
    ]

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}
