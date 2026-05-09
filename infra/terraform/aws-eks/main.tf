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
  subnet_zones       = [var.zone, var.secondary_zone]

  tags = {
    App             = "silicon-boutique"
    Environment     = var.environment
    RunId           = local.run_id
    MachineType     = var.machine_type
    ProcessorFamily = var.processor_family
    Architecture    = local.architecture_label
    ManagedBy       = "terraform"
    TeardownRule    = "destroy-after-run"
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

data "aws_iam_policy_document" "eks_cluster_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "eks_node_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_vpc" "benchmark" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.tags, {
    Name = "${local.name_prefix}-vpc"
  })
}

resource "aws_subnet" "benchmark" {
  count = 2

  vpc_id                  = aws_vpc.benchmark.id
  cidr_block              = cidrsubnet(aws_vpc.benchmark.cidr_block, 8, count.index)
  availability_zone       = local.subnet_zones[count.index]
  map_public_ip_on_launch = true

  tags = merge(local.tags, {
    Name                                          = "${local.name_prefix}-subnet-${count.index + 1}"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  })
}

resource "aws_internet_gateway" "benchmark" {
  vpc_id = aws_vpc.benchmark.id

  tags = merge(local.tags, {
    Name = "${local.name_prefix}-igw"
  })
}

resource "aws_route_table" "benchmark" {
  vpc_id = aws_vpc.benchmark.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.benchmark.id
  }

  tags = merge(local.tags, {
    Name = "${local.name_prefix}-rt"
  })
}

resource "aws_route_table_association" "benchmark" {
  count = length(aws_subnet.benchmark)

  subnet_id      = aws_subnet.benchmark[count.index].id
  route_table_id = aws_route_table.benchmark.id
}

resource "aws_iam_role" "eks_cluster" {
  name               = "${local.name_prefix}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.eks_cluster_assume_role.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "eks_cluster" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role" "eks_node" {
  name               = "${local.name_prefix}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.eks_node_assume_role.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "eks_worker_node" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "eks_cni" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "eks_container_registry" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_eks_cluster" "benchmark" {
  name     = local.cluster_name
  role_arn = aws_iam_role.eks_cluster.arn
  version  = var.cluster_version

  vpc_config {
    subnet_ids              = aws_subnet.benchmark[*].id
    endpoint_private_access = false
    endpoint_public_access  = true
  }

  tags = local.tags

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster,
  ]
}

resource "aws_eks_node_group" "benchmark" {
  cluster_name    = aws_eks_cluster.benchmark.name
  node_group_name = "benchmark"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = aws_subnet.benchmark[*].id
  instance_types  = [var.machine_type]
  capacity_type   = var.enable_spot_nodes ? "SPOT" : "ON_DEMAND"
  disk_size       = var.disk_size_gb

  scaling_config {
    desired_size = var.node_count
    max_size     = var.node_count
    min_size     = var.node_count
  }

  labels = local.node_labels
  tags   = local.tags

  depends_on = [
    aws_iam_role_policy_attachment.eks_worker_node,
    aws_iam_role_policy_attachment.eks_cni,
    aws_iam_role_policy_attachment.eks_container_registry,
  ]
}
