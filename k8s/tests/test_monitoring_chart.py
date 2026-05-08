import json
import subprocess
import unittest
from pathlib import Path


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
    helm = subprocess.run(
        [
            "helm",
            "template",
            "sb-monitoring",
            str(CHART),
            "--namespace",
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
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if helm.returncode != 0:
        raise AssertionError(f"helm template failed:\n{helm.stderr}")
    return split_documents(helm.stdout)


def split_documents(rendered):
    return [
        document.strip("\n")
        for document in rendered.split("\n---\n")
        if document.strip()
    ]


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


def top_level_value(document, key):
    prefix = f"{key}:"
    for line in document.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip('"')
    return None


def metadata_name(document):
    lines = document.splitlines()
    for index, line in enumerate(lines):
        if line == "metadata:":
            for metadata_line in lines[index + 1 :]:
                if not metadata_line.startswith("  "):
                    return None
                if metadata_line.startswith("  name:"):
                    return metadata_line.split(":", 1)[1].strip().strip('"')
    return None


def label_value(document, key):
    lines = document.splitlines()
    in_metadata = False
    in_labels = False
    for line in lines:
        if line == "metadata:":
            in_metadata = True
            in_labels = False
            continue
        if in_metadata and not line.startswith("  "):
            break
        if in_metadata and line == "  labels:":
            in_labels = True
            continue
        if in_labels:
            if not line.startswith("    "):
                break
            label_key, _, value = line.strip().partition(":")
            if label_key == key:
                return value.strip().strip('"')
    return None


def literal_data_value(document, key):
    lines = document.splitlines()
    marker = f"  {key}: |-"
    for index, line in enumerate(lines):
        if line != marker:
            continue
        value_lines = []
        for value_line in lines[index + 1 :]:
            if value_line.startswith("    "):
                value_lines.append(value_line[4:])
                continue
            break
        return "\n".join(value_lines)
    raise AssertionError(f"missing literal data key {key!r}")


if __name__ == "__main__":
    unittest.main()
