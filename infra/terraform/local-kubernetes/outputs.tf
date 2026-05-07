output "run_id" {
  description = "Benchmark run identifier."
  value       = local.run_id
}

output "namespace" {
  description = "Kubernetes namespace created for the benchmark run."
  value       = kubernetes_namespace_v1.benchmark.metadata[0].name
}

output "name_prefix" {
  description = "Standard name prefix for resources owned by this benchmark run."
  value       = local.name_prefix
}

output "kube_context" {
  description = "Kubeconfig context used by the local Kubernetes Terraform path."
  value       = var.kube_context
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

output "labels" {
  description = "Required labels applied to local resources managed by this Terraform root."
  value       = local.common_labels
}

output "annotations" {
  description = "Required teardown annotations applied to local resources managed by this Terraform root."
  value       = local.common_annotations
}

output "kubernetes_label_selector" {
  description = "Selector for resources associated with this benchmark run."
  value       = "silicon-boutique/run-id=${local.run_id}"
}

output "teardown_check_commands" {
  description = "Commands to verify local Kubernetes resources before and after terraform destroy."
  value = [
    "kubectl get namespace ${local.namespace} --context ${var.kube_context} --show-labels",
    "kubectl get all -n ${local.namespace} --context ${var.kube_context}",
    "kubectl get namespace ${local.namespace} --context ${var.kube_context}",
  ]
}
