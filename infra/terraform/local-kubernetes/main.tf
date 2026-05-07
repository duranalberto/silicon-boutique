resource "random_id" "run" {
  count = var.run_id == null ? 1 : 0

  byte_length = 4
  prefix      = "run-"
}

locals {
  run_id             = var.run_id == null ? random_id.run[0].hex : var.run_id
  name_prefix        = "silicon-boutique-${local.run_id}"
  namespace          = var.namespace == null ? local.name_prefix : var.namespace
  architecture_label = replace(var.architecture, "_", "-")

  common_labels = {
    "app.kubernetes.io/name"            = "silicon-boutique"
    "app.kubernetes.io/managed-by"      = "terraform"
    "app.kubernetes.io/part-of"         = "silicon-boutique"
    "silicon-boutique/environment"      = var.environment
    "silicon-boutique/run-id"           = local.run_id
    "silicon-boutique/machine-type"     = var.machine_type
    "silicon-boutique/processor-family" = var.processor_family
    "silicon-boutique/architecture"     = local.architecture_label
    "silicon-boutique/local-region"     = var.region
    "silicon-boutique/local-node-count" = tostring(var.node_count)
  }

  common_annotations = {
    "silicon-boutique/teardown-owner" = "terraform"
    "silicon-boutique/teardown-scope" = "namespace"
    "silicon-boutique/teardown-rule"  = "destroy-after-run"
  }
}

resource "kubernetes_namespace_v1" "benchmark" {
  metadata {
    name        = local.namespace
    labels      = local.common_labels
    annotations = local.common_annotations
  }
}
