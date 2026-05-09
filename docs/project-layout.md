# Project Layout

This document captures the intended repository structure and the purpose of each major area.

```text
silicon-boutique/
├── .devcontainer/           # Devcontainer build and feature setup
├── .github/
│   └── workflows/           # GitHub Actions benchmark orchestration
├── automation/              # Metric extraction and reporting helpers
├── docs/                    # Living documentation and planning
├── infra/                   # Infrastructure as code
├── k8s/                     # Kubernetes manifests and Helm assets
├── mcp-server/              # MCP boundary package and fixture-backed contracts
├── AGENTS.md                # Agent operating instructions
├── README.md                # Top-level project overview
├── CONTRIBUTING.md          # Contribution workflow and expectations
└── SECURITY.md              # Security and credential handling guidance
```

## Notes

- The `docs/` folder is the source of truth for planning and architecture notes.
- The terminology in `README.md`, `docs/spec-driven-development.md`, `docs/architecture.md`, `docs/runbook.md`, and `docs/roadmap.md` should describe the same benchmark pipeline stages.
- The `automation/`, `infra/`, and `k8s/` folders contain the implemented local and GCP benchmark pipeline assets plus the AWS EKS scaffold.
- The `mcp-server/` folder contains dependency-light MCP boundary contracts and fixture-backed local adapters; production adapters are tracked in the roadmap.
