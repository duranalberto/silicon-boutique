# Local Kubernetes Terraform

This Terraform root creates the local benchmark namespace inside the devcontainer-managed `siliconboutique` minikube profile. It assumes the cluster already exists and does not start or destroy minikube.

## Usage

```bash
cd infra/terraform/local-kubernetes
terraform init
terraform validate
terraform plan
terraform apply -auto-approve
terraform output namespace
terraform destroy -auto-approve
```

Use variables to align local validation metadata with the future GCP workflow shape:

```bash
terraform plan \
  -var='run_id=run-local-001' \
  -var='machine_type=local' \
  -var='processor_family=local' \
  -var='architecture=x86_64'
```

The default `run_id` is generated once and remains stable in Terraform state until the state is replaced or the `random_id.run` resource is tainted.

## Naming, Labels, and Teardown

The default namespace name is `silicon-boutique-${run_id}`. All resources managed by this root must carry the rendered `silicon-boutique/*` labels and teardown annotations exposed by:

```bash
terraform output labels
terraform output annotations
terraform output kubernetes_label_selector
terraform output teardown_check_commands
```

Terraform owns only the benchmark namespace. Teardown must destroy that namespace and must not delete the underlying minikube profile or unrelated namespaces.
