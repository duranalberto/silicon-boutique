#!/usr/bin/env python3
"""Inject SiliconBoutique metadata into Helm-rendered Kubernetes resources."""

import json
import re
import sys


def leading_spaces(line):
    """Compute leading spaces.


    Args:
        line: line used by this operation.

    Returns:
        Result produced by leading spaces.
    """
    return len(line) - len(line.lstrip(" "))


def split_documents(text):
    """Compute split documents.


    Args:
        text: text used by this operation.

    Returns:
        Result produced by split documents.
    """
    docs = []
    current = []
    for line in text.splitlines():
        if re.match(r"^---\s*$", line):
            docs.append("\n".join(current))
            current = []
        else:
            current.append(line)
    docs.append("\n".join(current))
    return docs


def read_block_json(lines, key):
    """Read block JSON.


    Args:
        lines: lines used by this operation.
        key: key used by this operation.

    Returns:
        Result produced by read block JSON.
    """
    for index, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(key)}:\s*\|-\s*$", line):
            base_indent = leading_spaces(line)
            block = []
            for next_line in lines[index + 1 :]:
                if next_line.strip() and leading_spaces(next_line) <= base_indent:
                    break
                block.append(next_line[base_indent + 2 :])
            return json.loads("\n".join(block))
    return None


def find_metadata(lines):
    """Find metadata.


    Args:
        lines: lines used by this operation.

    Returns:
        Result produced by find metadata.
    """
    for index, line in enumerate(lines):
        if line == "metadata:":
            return index
    return None


def document_kind(lines):
    """Compute document kind.


    Args:
        lines: lines used by this operation.

    Returns:
        Result produced by document kind.
    """
    for line in lines:
        match = re.match(r"^kind:\s*(\S+)\s*$", line)
        if match:
            return match.group(1)
    return None


def metadata_name(lines):
    """Compute metadata name.


    Args:
        lines: lines used by this operation.

    Returns:
        Result produced by metadata name.
    """
    metadata_index = find_metadata(lines)
    if metadata_index is None:
        return None

    metadata_indent = leading_spaces(lines[metadata_index])
    metadata_end = section_end(lines, metadata_index, metadata_indent)
    name_indent = metadata_indent + 2
    for index in range(metadata_index + 1, metadata_end):
        match = re.match(rf"^ {{{name_indent}}}name:\s*(\S+)\s*$", lines[index])
        if match:
            return match.group(1).strip('"')
    return None


def section_end(lines, start, indent):
    """Compute section end.


    Args:
        lines: lines used by this operation.
        start: start used by this operation.
        indent: indent used by this operation.

    Returns:
        Result produced by section end.
    """
    for index in range(start + 1, len(lines)):
        if lines[index].strip() and leading_spaces(lines[index]) <= indent:
            return index
    return len(lines)


def sequence_end(lines, start):
    """Compute sequence end.


    Args:
        lines: lines used by this operation.
        start: start used by this operation.

    Returns:
        Result produced by sequence end.
    """
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


def ensure_mapping(lines, parent_index, child_name, values):
    """Ensure mapping.


    Args:
        lines: lines used by this operation.
        parent_index: parent index used by this operation.
        child_name: child name used by this operation.
        values: values used by this operation.

    Returns:
        None.
    """
    parent_indent = leading_spaces(lines[parent_index])
    parent_end = section_end(lines, parent_index, parent_indent)
    child_indent = parent_indent + 2
    child_index = None

    for index in range(parent_index + 1, parent_end):
        if re.match(rf"^ {{{child_indent}}}{re.escape(child_name)}:\s*$", lines[index]):
            child_index = index
            break

    if child_index is None:
        insert_at = parent_end
        lines[insert_at:insert_at] = [" " * child_indent + f"{child_name}:"]
        child_index = insert_at

    child_end = section_end(lines, child_index, child_indent)
    key_indent = child_indent + 2
    existing = {}
    for index in range(child_index + 1, child_end):
        match = re.match(rf"^ {{{key_indent}}}([^:]+):", lines[index])
        if match:
            existing[match.group(1).strip()] = index

    for key, value in values.items():
        rendered = " " * key_indent + f"{key}: {json.dumps(str(value))}"
        if key in existing:
            lines[existing[key]] = rendered
        else:
            lines.insert(child_end, rendered)
            child_end += 1


def patch_template_metadata(lines, child_name, values):
    """Compute patch template metadata.


    Args:
        lines: lines used by this operation.
        child_name: child name used by this operation.
        values: values used by this operation.

    Returns:
        None.
    """
    template_indexes = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^\s+template:\s*$", line)
    ]

    for template_index in reversed(template_indexes):
        template_indent = leading_spaces(lines[template_index])
        template_end = section_end(lines, template_index, template_indent)
        metadata_indent = template_indent + 2
        metadata_index = None

        for index in range(template_index + 1, template_end):
            if re.match(rf"^ {{{metadata_indent}}}metadata:\s*$", lines[index]):
                metadata_index = index
                break

        if metadata_index is None:
            metadata_index = template_index + 1
            lines.insert(metadata_index, " " * metadata_indent + "metadata:")

        ensure_mapping(lines, metadata_index, child_name, values)


def find_line(lines, start, end, pattern):
    """Find line.


    Args:
        lines: lines used by this operation.
        start: start used by this operation.
        end: end used by this operation.
        pattern: pattern used by this operation.

    Returns:
        Result produced by find line.
    """
    for index in range(start, end):
        if re.match(pattern, lines[index]):
            return index
    return None


def find_named_list_item(lines, start, end, item_indent, name):
    """Find named list item.


    Args:
        lines: lines used by this operation.
        start: start used by this operation.
        end: end used by this operation.
        item_indent: item indent used by this operation.
        name: name used by this operation.

    Returns:
        Result produced by find named list item.
    """
    for index in range(start, end):
        if not re.match(rf"^ {{{item_indent}}}-\s+name:\s*{re.escape(name)}\s*$", lines[index]):
            continue

        item_end = end
        for next_index in range(index + 1, end):
            if re.match(rf"^ {{{item_indent}}}-\s+", lines[next_index]):
                item_end = next_index
                break
        return index, item_end

    return None, None


def ensure_env_var(lines, env_index, env_end, name, value):
    """Ensure environment var.


    Args:
        lines: lines used by this operation.
        env_index: environment index used by this operation.
        env_end: environment end used by this operation.
        name: name used by this operation.
        value: value used by this operation.

    Returns:
        Result produced by ensure environment var.
    """
    env_indent = leading_spaces(lines[env_index])
    item_indent = env_indent
    name_index, item_end = find_named_list_item(lines, env_index + 1, env_end, item_indent, name)

    rendered_name = " " * item_indent + f"- name: {name}"
    rendered_value = " " * (item_indent + 2) + f"value: {json.dumps(str(value))}"

    if name_index is None:
        lines[env_end:env_end] = [rendered_name, rendered_value]
        return env_end + 2

    value_index = find_line(
        lines,
        name_index + 1,
        item_end,
        rf"^ {{{item_indent + 2}}}value:\s*",
    )
    if value_index is None:
        lines.insert(name_index + 1, rendered_value)
        return env_end + 1

    lines[value_index] = rendered_value
    return env_end


def patch_loadgenerator_env(lines, load_generator):
    """Compute patch loadgenerator environment.


    Args:
        lines: lines used by this operation.
        load_generator: load generator used by this operation.

    Returns:
        None.
    """
    if document_kind(lines) != "Deployment" or metadata_name(lines) != "loadgenerator":
        return

    spec_index = find_line(lines, 0, len(lines), r"^spec:\s*$")
    if spec_index is None:
        return

    containers_index = find_line(lines, spec_index, len(lines), r"^ {6}containers:\s*$")
    if containers_index is None:
        return

    containers_end = sequence_end(lines, containers_index)
    container_index, container_end = find_named_list_item(
        lines,
        containers_index + 1,
        containers_end,
        leading_spaces(lines[containers_index]),
        "main",
    )
    if container_index is None:
        return

    env_index = find_line(lines, container_index + 1, container_end, r"^ {8}env:\s*$")
    if env_index is None:
        env_index = container_end
        lines.insert(env_index, "        env:")
        container_end += 1

    env_end = sequence_end(lines, env_index)
    for key in (
        "USERS",
        "RATE",
        "LOCUST_RUN_TIME",
        "CONCURRENT_USERS",
        "USERS_PER_SECOND",
        "TEST_DURATION",
    ):
        env_end = ensure_env_var(lines, env_index, env_end, key, load_generator[key])


def patch_document(document, labels, annotations, load_generator):
    """Compute patch document.


    Args:
        document: document used by this operation.
        labels: labels used by this operation.
        annotations: annotations used by this operation.
        load_generator: load generator used by this operation.

    Returns:
        Result produced by patch document.
    """
    if not document.strip():
        return document

    lines = document.splitlines()
    metadata_index = find_metadata(lines)
    if metadata_index is None:
        return document

    ensure_mapping(lines, metadata_index, "labels", labels)
    ensure_mapping(lines, metadata_index, "annotations", annotations)
    patch_template_metadata(lines, "labels", labels)
    patch_template_metadata(lines, "annotations", annotations)
    patch_loadgenerator_env(lines, load_generator)
    return "\n".join(lines)


def main():
    """Run the command-line entrypoint.


    Returns:
        Process exit code for the command.
    """
    rendered = sys.stdin.read()
    docs = split_documents(rendered)
    labels = None
    annotations = None
    load_generator = None

    for doc in docs:
        lines = doc.splitlines()
        labels = labels or read_block_json(lines, "labels.json")
        annotations = annotations or read_block_json(lines, "annotations.json")
        load_generator = load_generator or read_block_json(lines, "load-generator.json")

    if labels is None or annotations is None or load_generator is None:
        sys.stderr.write("silicon-boutique post-renderer metadata ConfigMap was not rendered\n")
        return 1

    patched = [patch_document(doc, labels, annotations, load_generator) for doc in docs]
    sys.stdout.write("\n---\n".join(patched).strip() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
