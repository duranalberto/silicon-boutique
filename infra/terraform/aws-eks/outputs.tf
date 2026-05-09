output "run_id" {
  description = "Benchmark run identifier."
  value       = local.run_id
}

output "environment" {
  description = "Benchmark environment."
  value       = var.environment
}

output "cloud_provider" {
  description = "Cloud provider metadata for benchmark summaries."
  value       = "aws"
}

output "machine_type" {
  description = "Machine type metadata for workflow parity."
  value       = var.machine_type
}

output "processor_family" {
  description = "Processor family metadata for workflow parity."
  value       = var.processor_family
}

output "cpu_platform" {
  description = "Optional provider-specific CPU platform metadata."
  value       = var.cpu_platform
}

output "architecture" {
  description = "Processor architecture metadata for workflow parity."
  value       = var.architecture
}

output "region" {
  description = "AWS region for the benchmark resources."
  value       = var.region
}

output "zone" {
  description = "Primary AWS availability zone metadata for benchmark comparison."
  value       = var.zone
}

output "node_count" {
  description = "Benchmark node count metadata for workflow parity."
  value       = var.node_count
}

output "pricing_model" {
  description = "Pricing model metadata for benchmark cost calculations."
  value       = var.pricing_model
}

output "enable_spot_nodes" {
  description = "Whether the benchmark EKS managed node group uses Spot capacity."
  value       = var.enable_spot_nodes
}

output "name_prefix" {
  description = "Standard name prefix for resources owned by this benchmark run."
  value       = local.name_prefix
}

output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.benchmark.name
}

output "get_credentials_command" {
  description = "Command to populate kubeconfig for the benchmark EKS cluster after apply."
  value       = "aws eks update-kubeconfig --name ${aws_eks_cluster.benchmark.name} --region ${var.region}"
}

output "tags" {
  description = "Required AWS tags applied to tag-capable resources managed by this Terraform root."
  value       = local.tags
}

output "node_labels" {
  description = "Required Kubernetes node labels applied to EKS nodes for workload scheduling and traceability."
  value       = local.node_labels
}

output "aws_tag_filter" {
  description = "AWS tag filter for resources associated with this benchmark run."
  value       = "tag:RunId=${local.run_id}"
}

output "managed_resource_names" {
  description = "Deterministic names for primary resources managed by this Terraform root."
  value = {
    cluster    = aws_eks_cluster.benchmark.name
    vpc        = "${local.name_prefix}-vpc"
    subnet_one = "${local.name_prefix}-subnet-1"
    subnet_two = "${local.name_prefix}-subnet-2"
    node_group = aws_eks_node_group.benchmark.node_group_name
  }
}

output "teardown_check_commands" {
  description = "Commands to inspect managed AWS resources before and after terraform destroy."
  value = [
    "aws eks describe-cluster --name ${aws_eks_cluster.benchmark.name} --region ${var.region}",
    "aws eks describe-nodegroup --cluster-name ${aws_eks_cluster.benchmark.name} --nodegroup-name ${aws_eks_node_group.benchmark.node_group_name} --region ${var.region}",
    "aws ec2 describe-vpcs --region ${var.region} --filters Name=tag:RunId,Values=${local.run_id}",
    "aws ec2 describe-subnets --region ${var.region} --filters Name=tag:RunId,Values=${local.run_id}",
  ]
}
