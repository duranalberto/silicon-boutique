import json
import unittest
from pathlib import Path

from chart_test_utils import (
    label_value,
    literal_data_value,
    metadata_name,
    render_helm_template,
    split_documents,
    top_level_value,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "k8s" / "charts" / "silicon-boutique-monitoring"
DASHBOARD_KEY = "online-boutique-benchmark.json"


class MonitoringChartTest(unittest.TestCase):
    def test_default_render_delivers_grafana_and_benchmark_dashboard(self):
        documents = render_chart()

        self.assertIsNotNone(find_document(documents, "Deployment", "sb-monitoring-grafana"))
        self.assertIsNotNone(find_document(documents, "Service", "sb-monitoring-grafana"))

        dashboard_configmap = find_dashboard_configmap(documents)
        self.assertIsNotNone(dashboard_configmap)
        self.assertEqual(label_value(dashboard_configmap, "grafana_dashboard"), "1")

        dashboard = json.loads(literal_data_value(dashboard_configmap, DASHBOARD_KEY))
        self.assertEqual(dashboard["title"], "SiliconBoutique Online Boutique Benchmark")
        self.assertEqual(dashboard["uid"], "silicon-boutique-online-boutique")
        self.assertEqual(dashboard["time"], {"from": "now-30m", "to": "now"})

        dashboard_json = json.dumps(dashboard, sort_keys=True)
        for expression in (
            "silicon_boutique:workload_cpu_usage_cores:rate5m",
            "silicon_boutique:workload_cpu_utilization_pct",
            "silicon_boutique:workload_memory_working_set_bytes",
            "silicon_boutique:workload_cpu_throttling_ratio:rate5m",
            "silicon_boutique:frontend_probe_latency_seconds",
            "silicon_boutique:workload_ready_pods",
            "silicon_boutique:workload_restarts_total",
        ):
            self.assertIn(expression, dashboard_json)

        for metadata in (
            "run_id",
            "render-test",
            "environment",
            "local",
            "machine_type",
            "render-machine",
            "processor_family",
            "render-family",
            "architecture",
            "arm64",
            "workload_namespace",
            "sb-render",
            "benchmark_start",
            "2026-05-07T12:00:00Z",
            "benchmark_end",
            "2026-05-07T12:20:00Z",
        ):
            self.assertIn(metadata, dashboard_json)

        for panel in dashboard["panels"]:
            for target in panel.get("targets", []):
                self.assertEqual(target["datasource"]["uid"], "prometheus")

    def test_recording_rules_compute_workload_cpu_utilization(self):
        documents = render_chart()
        rules = find_document(
            documents,
            "PrometheusRule",
            "sb-monitoring-silicon-boutique-monitoring-benchmark",
        )

        self.assertIsNotNone(rules)
        self.assertIn("record: silicon_boutique:workload_node_cpu_cores", rules)
        self.assertIn("kube_node_status_allocatable{resource=\"cpu\", unit=\"core\"}", rules)
        self.assertIn("kube_node_status_capacity{resource=\"cpu\", unit=\"core\"}", rules)
        self.assertIn("max by (node) (kube_pod_info{namespace=\"sb-render\", node!=\"\"})", rules)
        self.assertIn("record: silicon_boutique:workload_cpu_utilization_pct", rules)
        self.assertIn("silicon_boutique:workload_cpu_usage_cores:rate5m", rules)
        self.assertIn("silicon_boutique:workload_node_cpu_cores", rules)

    def test_dashboard_configmap_is_not_rendered_when_grafana_is_disabled(self):
        documents = render_chart("--set", "kube-prometheus-stack.grafana.enabled=false")

        self.assertIsNone(find_dashboard_configmap(documents))


def render_chart(*extra_args):
    return split_documents(
        render_helm_template(
            REPO_ROOT,
            CHART,
            "sb-monitoring",
            "sb-render",
            "--set-string",
            "siliconBoutique.runId=render-test",
            "--set-string",
            "siliconBoutique.environment=local",
            "--set-string",
            "siliconBoutique.machineType=render-machine",
            "--set-string",
            "siliconBoutique.processorFamily=render-family",
            "--set-string",
            "siliconBoutique.architecture=arm64",
            "--set-string",
            "siliconBoutique.workloadNamespace=sb-render",
            "--set-string",
            "siliconBoutique.benchmarkStart=2026-05-07T12:00:00Z",
            "--set-string",
            "siliconBoutique.benchmarkEnd=2026-05-07T12:20:00Z",
            *extra_args,
        )
    )


def find_document(documents, kind, name):
    for document in documents:
        if top_level_value(document, "kind") == kind and metadata_name(document) == name:
            return document
    return None


def find_dashboard_configmap(documents):
    for document in documents:
        if top_level_value(document, "kind") != "ConfigMap":
            continue
        if label_value(document, "grafana_dashboard") != "1":
            continue
        if f"  {DASHBOARD_KEY}: |-" in document:
            return document
    return None


if __name__ == "__main__":
    unittest.main()
