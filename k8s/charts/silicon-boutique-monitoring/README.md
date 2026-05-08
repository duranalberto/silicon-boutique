# SiliconBoutique Monitoring Helm Chart

This chart installs the local benchmark monitoring stack without modifying the Online Boutique workload chart. It combines `kube-prometheus-stack` with `prometheus-blackbox-exporter`, then adds SiliconBoutique-owned metric contracts, recording rules, a frontend HTTP probe, Grafana, and a run-scoped Online Boutique benchmark dashboard.

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

The rendered output should include Prometheus stack resources, Grafana resources, blackbox exporter resources, a `Probe` for the workload frontend service, a metric contract `ConfigMap`, optional benchmark `PrometheusRule` records, and a dashboard `ConfigMap` labeled `grafana_dashboard: "1"`. The benchmark recording rules include `silicon_boutique:workload_cpu_utilization_pct`, calculated from workload CPU usage divided by allocatable CPU cores on nodes running workload pods, with capacity as a fallback.

## Grafana Dashboard

Grafana is enabled by default and remains private inside the cluster. The chart provisions the built-in Prometheus datasource as `Prometheus` with UID `prometheus`, and the benchmark dashboard is loaded by the Grafana sidecar from a chart-owned `ConfigMap`. Automation updates `siliconBoutique.benchmarkStart` and `siliconBoutique.benchmarkEnd` after the measured window so the dashboard records the exact run window.

For local inspection, port-forward Grafana after installing the monitoring chart:

```bash
kubectl port-forward service/sb-monitoring-grafana \
  3000:80 \
  --namespace "$namespace" \
  --context siliconboutique
```

Read the generated admin password from the kube-prometheus-stack secret:

```bash
kubectl get secret sb-monitoring-grafana \
  --namespace "$namespace" \
  --context siliconboutique \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

Log in at `http://127.0.0.1:3000` with user `admin`, then open the `SiliconBoutique Online Boutique Benchmark` dashboard. If you need to inspect the dashboard after an automated local run, run `automation/scripts/run_local_benchmark.py --skip-destroy` and manually clean up the Helm releases and Terraform namespace when finished.
