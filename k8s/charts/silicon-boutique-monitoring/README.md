# SiliconBoutique Monitoring Helm Chart

This chart installs the local benchmark monitoring stack without modifying the Online Boutique workload chart. It combines `kube-prometheus-stack` with `prometheus-blackbox-exporter`, then adds SiliconBoutique-owned metric contracts, recording rules, and a frontend HTTP probe.

The wrapper depends on:

- `kube-prometheus-stack` chart `84.5.0`
- `prometheus-blackbox-exporter` chart `11.9.1`
- Helm repository `https://prometheus-community.github.io/helm-charts`

## Local Validation

Build and validate dependencies:

```bash
helm dependency update k8s/charts/silicon-boutique-monitoring
helm lint k8s/charts/silicon-boutique-monitoring
```

Render the chart against a workload namespace:

```bash
helm template silicon-boutique-monitoring \
  ./k8s/charts/silicon-boutique-monitoring \
  --namespace monitoring \
  --set-string siliconBoutique.workloadNamespace="$namespace" \
  --set-string siliconBoutique.runId="$run_id"
```

The rendered output should include Prometheus stack resources, blackbox exporter resources, a `Probe` for the workload frontend service, a metric contract `ConfigMap`, and optional benchmark `PrometheusRule` records.
