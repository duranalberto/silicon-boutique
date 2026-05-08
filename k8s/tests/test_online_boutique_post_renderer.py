import re
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "k8s" / "charts" / "silicon-boutique-online-boutique"
POST_RENDERER = CHART / "post-renderer.py"


class OnlineBoutiquePostRendererTest(unittest.TestCase):
    def test_local_x86_render_injects_metadata_and_load_settings(self):
        documents = render_chart(
            run_id="local-render",
            environment="local",
            machine_type="local-dev",
            processor_family="local-dev",
            architecture="x86_64",
            concurrent_users="17",
            users_per_second="2.5",
            test_duration="3m",
        )

        assert_rendered_metadata(
            self,
            documents,
            expected_labels={
                "app.kubernetes.io/part-of": "silicon-boutique",
                "silicon-boutique/run-id": "local-render",
                "silicon-boutique/environment": "local",
                "silicon-boutique/machine-type": "local-dev",
                "silicon-boutique/processor-family": "local-dev",
                "silicon-boutique/architecture": "x86-64",
            },
        )
        assert_loadgenerator_env(
            self,
            documents,
            {
                "USERS": "17",
                "RATE": "2.5",
                "LOCUST_RUN_TIME": "3m",
                "CONCURRENT_USERS": "17",
                "USERS_PER_SECOND": "2.5",
                "TEST_DURATION": "3m",
            },
        )

    def test_gcp_arm_render_injects_metadata_and_load_settings(self):
        documents = render_chart(
            run_id="gcp-render",
            environment="gcp",
            machine_type="c4a-standard-4",
            processor_family="c4a",
            architecture="arm64",
            concurrent_users="23",
            users_per_second="4",
            test_duration="5m",
        )

        assert_rendered_metadata(
            self,
            documents,
            expected_labels={
                "app.kubernetes.io/part-of": "silicon-boutique",
                "silicon-boutique/run-id": "gcp-render",
                "silicon-boutique/environment": "gcp",
                "silicon-boutique/machine-type": "c4a-standard-4",
                "silicon-boutique/processor-family": "c4a",
                "silicon-boutique/architecture": "arm64",
            },
        )
        assert_loadgenerator_env(
            self,
            documents,
            {
                "USERS": "23",
                "RATE": "4",
                "LOCUST_RUN_TIME": "5m",
                "CONCURRENT_USERS": "23",
                "USERS_PER_SECOND": "4",
                "TEST_DURATION": "5m",
            },
        )

    def test_post_renderer_requires_metadata_configmap(self):
        result = subprocess.run(
            [sys.executable, str(POST_RENDERER)],
            input="apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: unrelated\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(
            "silicon-boutique post-renderer metadata ConfigMap was not rendered",
            result.stderr,
        )


def render_chart(
    *,
    run_id,
    environment,
    machine_type,
    processor_family,
    architecture,
    concurrent_users,
    users_per_second,
    test_duration,
):
    helm = subprocess.run(
        [
            "helm",
            "template",
            "silicon-boutique-online-boutique",
            str(CHART),
            "--namespace",
            f"sb-{run_id}",
            "--set-string",
            f"siliconBoutique.runId={run_id}",
            "--set-string",
            f"siliconBoutique.environment={environment}",
            "--set-string",
            f"siliconBoutique.machineType={machine_type}",
            "--set-string",
            f"siliconBoutique.processorFamily={processor_family}",
            "--set-string",
            f"siliconBoutique.architecture={architecture}",
            "--set",
            f"siliconBoutique.loadGenerator.concurrentUsers={concurrent_users}",
            "--set",
            f"siliconBoutique.loadGenerator.usersPerSecond={users_per_second}",
            "--set-string",
            f"siliconBoutique.loadGenerator.testDuration={test_duration}",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if helm.returncode != 0:
        raise AssertionError(f"helm template failed:\n{helm.stderr}")

    rendered = subprocess.run(
        [sys.executable, str(POST_RENDERER)],
        input=helm.stdout,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if rendered.returncode != 0:
        raise AssertionError(f"post-renderer failed:\n{rendered.stderr}")

    return split_documents(rendered.stdout)


def assert_rendered_metadata(testcase, documents, *, expected_labels):
    expected_annotations = {
        "silicon-boutique/teardown-owner": "helm",
        "silicon-boutique/teardown-rule": "uninstall-before-terraform-destroy",
        "silicon-boutique/teardown-scope": "workload",
    }
    documents_with_metadata = 0
    deployments = 0

    for document in documents:
        lines = document.splitlines()
        if find_section(lines, ("metadata",)) is None:
            continue

        documents_with_metadata += 1
        assert_mapping_contains(
            testcase,
            expected_labels,
            mapping_at_path(lines, ("metadata", "labels")),
            document_identity(lines),
        )
        assert_mapping_contains(
            testcase,
            expected_annotations,
            mapping_at_path(lines, ("metadata", "annotations")),
            document_identity(lines),
        )

        if scalar_at_top_level(lines, "kind") != "Deployment":
            continue

        deployments += 1
        assert_mapping_contains(
            testcase,
            expected_labels,
            mapping_at_path(lines, ("spec", "template", "metadata", "labels")),
            f"{document_identity(lines)} pod template",
        )
        assert_mapping_contains(
            testcase,
            expected_annotations,
            mapping_at_path(lines, ("spec", "template", "metadata", "annotations")),
            f"{document_identity(lines)} pod template",
        )

    testcase.assertGreater(documents_with_metadata, 0)
    testcase.assertGreater(deployments, 0)


def assert_loadgenerator_env(testcase, documents, expected_env):
    loadgenerator = find_document(documents, "Deployment", "loadgenerator")
    testcase.assertIsNotNone(loadgenerator)

    lines = loadgenerator.splitlines()
    main_container = named_list_item(lines, ("spec", "template", "spec", "containers"), "main")
    testcase.assertIsNotNone(main_container)

    env = env_mapping_for_item(lines, main_container)
    assert_mapping_contains(testcase, expected_env, env, "Deployment/loadgenerator env")


def assert_mapping_contains(testcase, expected, actual, label):
    for key, expected_value in expected.items():
        testcase.assertEqual(
            actual.get(key),
            expected_value,
            f"{label} expected {key}={expected_value!r}; got {actual!r}",
        )


def split_documents(text):
    documents = []
    current = []
    for line in text.splitlines():
        if re.match(r"^---\s*$", line):
            if current:
                documents.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        documents.append("\n".join(current))
    return [document for document in documents if document.strip()]


def find_document(documents, kind, name):
    for document in documents:
        lines = document.splitlines()
        if scalar_at_top_level(lines, "kind") == kind and metadata_name(lines) == name:
            return document
    return None


def document_identity(lines):
    kind = scalar_at_top_level(lines, "kind") or "Unknown"
    name = metadata_name(lines) or "unnamed"
    return f"{kind}/{name}"


def scalar_at_top_level(lines, key):
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.+?)\s*$")
    for line in lines:
        match = pattern.match(line)
        if match:
            return unquote(match.group(1))
    return None


def metadata_name(lines):
    return mapping_at_path(lines, ("metadata",)).get("name")


def mapping_at_path(lines, path):
    index = find_section(lines, path)
    if index is None:
        return {}

    indent = leading_spaces(lines[index])
    end = section_end(lines, index, indent)
    mapping = {}
    key_indent = indent + 2
    for line in lines[index + 1 : end]:
        if leading_spaces(line) != key_indent:
            continue
        match = re.match(r"^\s*([^:]+):\s*(.*?)\s*$", line)
        if match:
            mapping[match.group(1)] = unquote(match.group(2))
    return mapping


def find_section(lines, path):
    start = 0
    end = len(lines)
    expected_indent = 0
    found = None

    for key in path:
        found = None
        pattern = re.compile(rf"^ {{{expected_indent}}}{re.escape(key)}:\s*(?:#.*)?$")
        for index in range(start, end):
            if pattern.match(lines[index]):
                found = index
                break
        if found is None:
            return None
        start = found + 1
        end = section_end(lines, found, expected_indent)
        expected_indent += 2

    return found


def named_list_item(lines, path, name):
    index = find_section(lines, path)
    if index is None:
        return None

    indent = leading_spaces(lines[index])
    end = sequence_end(lines, index)
    pattern = re.compile(rf"^ {{{indent}}}-\s+name:\s*{re.escape(name)}\s*$")
    for line_index in range(index + 1, end):
        if pattern.match(lines[line_index]):
            return line_index, list_item_end(lines, line_index, end)
    return None


def env_mapping_for_item(lines, item_bounds):
    item_start, item_end = item_bounds
    env_index = None
    for index in range(item_start + 1, item_end):
        if re.match(r"^\s+env:\s*$", lines[index]):
            env_index = index
            break
    if env_index is None:
        return {}

    env_indent = leading_spaces(lines[env_index])
    env_end = sequence_end(lines, env_index)
    env = {}
    index = env_index + 1
    while index < env_end:
        match = re.match(rf"^ {{{env_indent}}}-\s+name:\s*(\S+)\s*$", lines[index])
        if not match:
            index += 1
            continue

        name = match.group(1)
        item_end = list_item_end(lines, index, env_end)
        value = None
        for next_index in range(index + 1, item_end):
            value_match = re.match(
                rf"^ {{{env_indent + 2}}}value:\s*(.*?)\s*$",
                lines[next_index],
            )
            if value_match:
                value = unquote(value_match.group(1))
                break
        env[name] = value
        index = item_end
    return env


def section_end(lines, start, indent):
    for index in range(start + 1, len(lines)):
        if lines[index].strip() and leading_spaces(lines[index]) <= indent:
            return index
    return len(lines)


def sequence_end(lines, start):
    indent = leading_spaces(lines[start])
    for index in range(start + 1, len(lines)):
        if not lines[index].strip():
            continue
        line_indent = leading_spaces(lines[index])
        if line_indent < indent:
            return index
        if line_indent == indent and not lines[index].lstrip().startswith("- "):
            return index
    return len(lines)


def list_item_end(lines, start, end):
    indent = leading_spaces(lines[start])
    for index in range(start + 1, end):
        if re.match(rf"^ {{{indent}}}-\s+", lines[index]):
            return index
    return end


def leading_spaces(line):
    return len(line) - len(line.lstrip(" "))


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


if __name__ == "__main__":
    unittest.main()
