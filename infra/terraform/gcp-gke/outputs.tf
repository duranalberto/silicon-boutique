output "run_id" {
  description = "Benchmark run identifier."
  value       = local.run_id
}

output "environment" {
  description = "Benchmark environment."
  value       = var.environment
}

output "machine_type" {
  description = "Machine type metadata for workflow parity."
  value       = var.machine_type
}

output "processor_family" {
  description = "Processor family metadata for workflow parity."
  value       = var.processor_family
}

output "architecture" {
  description = "Processor architecture metadata for workflow parity."
  value       = var.architecture
}

output "project_id" {
  description = "GCP project ID for the benchmark resources."
  value       = var.project_id
}

output "region" {
  description = "GCP region for the benchmark subnet."
  value       = var.region
}

output "zone" {
  description = "GCP zone for the benchmark GKE cluster."
  value       = var.zone
}

output "name_prefix" {
  description = "Standard name prefix for resources owned by this benchmark run."
  value       = local.name_prefix
}

output "cluster_name" {
  description = "GKE cluster name."
  value       = google_container_cluster.benchmark.name
}

output "network_name" {
  description = "VPC network name."
  value       = google_compute_network.benchmark.name
}

output "subnet_name" {
  description = "Subnet name."
  value       = google_compute_subnetwork.benchmark.name
}

output "get_credentials_command" {
  description = "Command to populate kubeconfig for the benchmark GKE cluster after apply."
  value       = "gcloud container clusters get-credentials ${google_container_cluster.benchmark.name} --zone ${var.zone} --project ${var.project_id}"
}

output "labels" {
  description = "Required GCP labels applied to label-capable resources managed by this Terraform root."
  value       = local.labels
}

output "node_labels" {
  description = "Required Kubernetes node labels applied to GKE nodes for workload scheduling and traceability."
  value       = local.node_labels
}

output "gcp_label_filter" {
  description = "GCP label filter for resources associated with this benchmark run."
  value       = "labels.run_id=${local.run_id}"
}

output "managed_resource_names" {
  description = "Deterministic names for primary resources managed by this Terraform root."
  value = {
    cluster = google_container_cluster.benchmark.name
    network = google_compute_network.benchmark.name
    subnet  = google_compute_subnetwork.benchmark.name
  }
}

output "teardown_check_commands" {
  description = "Commands to inspect managed GCP resources before and after terraform destroy."
  value = [
    "gcloud container clusters list --project ${var.project_id} --filter='name=${google_container_cluster.benchmark.name}'",
    "gcloud compute networks list --project ${var.project_id} --filter='name=${google_compute_network.benchmark.name}'",
    "gcloud compute networks subnets list --project ${var.project_id} --filter='name=${google_compute_subnetwork.benchmark.name} AND region=${var.region}'",
  ]
}
