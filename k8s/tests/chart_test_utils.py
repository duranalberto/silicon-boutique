import subprocess
from pathlib import Path


def render_helm_template(repo_root: Path, chart: Path, release: str, namespace: str, *extra_args):
    helm = subprocess.run(
        [
            "helm",
            "template",
            release,
            str(chart),
            "--namespace",
            namespace,
            *extra_args,
        ],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if helm.returncode != 0:
        raise AssertionError(f"helm template failed:\n{helm.stderr}")
    return helm.stdout


def split_documents(rendered):
    return [
        document.strip("\n")
        for document in rendered.split("\n---\n")
        if document.strip()
    ]


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


def leading_spaces(line):
    return len(line) - len(line.lstrip(" "))


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
