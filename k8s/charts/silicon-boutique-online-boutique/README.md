# SiliconBoutique Online Boutique Helm Chart

This chart wraps Google's experimental Online Boutique Helm chart so SiliconBoutique can pin the workload version while keeping run metadata in this repository.

The wrapper depends on:

- `onlineboutique` chart `0.10.5`
- OCI repository `oci://us-docker.pkg.dev/online-boutique-ci/charts`
- Online Boutique application image tag `v0.10.5`

The upstream project is GoogleCloudPlatform/microservices-demo, and its Helm chart is documented at <https://github.com/GoogleCloudPlatform/microservices-demo/blob/v0.10.5/helm-chart/README.md>.

## Load Profile

SiliconBoutique exposes load-generator settings through wrapper values:

- `siliconBoutique.loadGenerator.concurrentUsers`: peak concurrent Locust users
- `siliconBoutique.loadGenerator.usersPerSecond`: Locust spawn rate
- `siliconBoutique.loadGenerator.testDuration`: benchmark duration, such as `20m`

The post-renderer maps these values into the upstream `loadgenerator` deployment as `USERS`, `RATE`, and `LOCUST_RUN_TIME`, with friendly trace aliases also rendered as pod environment variables.

## Local Validation

Provision the local namespace first:

```bash
cd infra/terraform/local-kubernetes
terraform init
terraform validate
terraform apply -auto-approve
namespace="$(terraform output -raw namespace)"
run_id="$(terraform output -raw run_id)"
environment="$(terraform output -raw environment)"
machine_type="$(terraform output -raw machine_type)"
processor_family="$(terraform output -raw processor_family)"
architecture="$(terraform output -raw architecture)"
cd ../../..
```

Build and validate the chart dependency:

```bash
helm dependency update k8s/charts/silicon-boutique-online-boutique
helm lint k8s/charts/silicon-boutique-online-boutique
python3 -m unittest discover -s k8s/tests
```

Install the Helm 4 post-renderer plugin from the local chart directory:

```bash
helm plugin list | awk 'NR > 1 {print $1}' | grep -qx silicon-boutique-metadata \
  || helm plugin install k8s/charts/silicon-boutique-online-boutique/post-renderer
```

Install the workload with SiliconBoutique metadata labels and teardown annotations:

```bash
helm upgrade --install silicon-boutique-online-boutique \
  ./k8s/charts/silicon-boutique-online-boutique \
  --namespace "$namespace" \
  --kube-context siliconboutique \
  --set-string siliconBoutique.runId="$run_id" \
  --set-string siliconBoutique.environment="$environment" \
  --set-string siliconBoutique.machineType="$machine_type" \
  --set-string siliconBoutique.processorFamily="$processor_family" \
  --set-string siliconBoutique.architecture="$architecture" \
  --set siliconBoutique.loadGenerator.concurrentUsers=10 \
  --set siliconBoutique.loadGenerator.usersPerSecond=1 \
  --set-string siliconBoutique.loadGenerator.testDuration=20m \
  --post-renderer silicon-boutique-metadata
```

Check readiness:

```bash
kubectl wait deployment --all \
  --for=condition=Available \
  --timeout=10m \
  --namespace "$namespace" \
  --context siliconboutique
kubectl get pods,services --namespace "$namespace" --context siliconboutique
```

Clean up the workload before destroying the Terraform-owned namespace:

```bash
helm uninstall silicon-boutique-online-boutique \
  --namespace "$namespace" \
  --kube-context siliconboutique
cd infra/terraform/local-kubernetes
terraform destroy -auto-approve
```
