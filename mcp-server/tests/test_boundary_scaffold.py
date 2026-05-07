import ast
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = REPO_ROOT / "mcp-server" / "src"
PACKAGE_ROOT = MCP_SRC / "silicon_boutique_mcp"
FORBIDDEN_ROOT_IMPORTS = {"automation", "infra", "k8s", "github", "google"}
FORBIDDEN_IMPORT_TEXT = (
    ".github/workflows",
    "benchmark.yml",
    "google.cloud",
)


class McpBoundaryScaffoldTest(unittest.TestCase):
    def env(self):
        return {**os.environ, "PYTHONPATH": str(MCP_SRC)}

    def test_package_imports_cleanly(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import silicon_boutique_mcp; print(silicon_boutique_mcp.__name__)",
            ],
            cwd=REPO_ROOT,
            env=self.env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "silicon_boutique_mcp")

    def test_module_help_is_discoverable(self):
        result = subprocess.run(
            [sys.executable, "-m", "silicon_boutique_mcp", "--help"],
            cwd=REPO_ROOT,
            env=self.env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("silicon-boutique-mcp", result.stdout)
        self.assertIn("--manifest", result.stdout)

    def test_manifest_lists_planned_capability_names(self):
        result = subprocess.run(
            [sys.executable, "-m", "silicon_boutique_mcp", "--manifest"],
            cwd=REPO_ROOT,
            env=self.env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        capability_names = {
            capability["name"] for capability in manifest["capabilities"]
        }
        self.assertEqual(
            capability_names,
            {
                "trigger_benchmark_run",
                "get_benchmark_status",
                "query_historical_metrics",
            },
        )

    def test_boundary_modules_do_not_import_pipeline_internals(self):
        for path in PACKAGE_ROOT.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for forbidden_text in FORBIDDEN_IMPORT_TEXT:
                self.assertNotIn(forbidden_text, source, path)

            parsed = ast.parse(source, filename=str(path))
            for node in ast.walk(parsed):
                if isinstance(node, ast.Import):
                    imported_roots = {
                        alias.name.split(".", maxsplit=1)[0] for alias in node.names
                    }
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots = {node.module.split(".", maxsplit=1)[0]}
                else:
                    continue

                self.assertTrue(
                    FORBIDDEN_ROOT_IMPORTS.isdisjoint(imported_roots),
                    f"{path} imports repo-internal layer {imported_roots}",
                )


if __name__ == "__main__":
    unittest.main()
