# Project Layout

This document captures the intended repository structure and the purpose of each major area.

```text
silicon-boutique/
├── .devcontainer/           # Devcontainer build and feature setup
├── .github/
│   └── workflows/           # GitHub Actions benchmark orchestration
├── automation/              # Metric extraction and reporting helpers
├── docs/                    # Living documentation and planning
├── artifacts/               # Generated benchmark artifacts; ignored for source-of-truth docs
├── infra/                   # Infrastructure as code
├── k8s/                     # Kubernetes manifests and Helm assets
├── mcp-server/              # MCP boundary package, adapters, CLI, and stdio server
├── AGENTS.md                # Agent operating instructions
├── README.md                # Top-level project overview
├── CONTRIBUTING.md          # Contribution workflow and expectations
└── SECURITY.md              # Security and credential handling guidance
```

## Notes

- The `docs/` folder is the source of truth for planning and architecture notes.
- The terminology in `README.md`, `docs/spec-driven-development.md`, `docs/architecture.md`, `docs/runbook.md`, and `docs/roadmap.md` should describe the same benchmark pipeline stages.
- The `.github/workflows/` folder contains the guarded GCP and AWS benchmark workflows.
- The `automation/`, `infra/`, and `k8s/` folders contain the implemented local, GCP, and AWS benchmark pipeline assets.
- The `mcp-server/` folder contains dependency-light MCP contracts, fixture adapters, production GitHub Actions and BigQuery adapters, CLI entrypoints, and the stdio MCP server.
- Generated benchmark evidence belongs under `artifacts/`; do not treat generated reports as canonical project documentation.
