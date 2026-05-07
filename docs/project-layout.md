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
├── mcp-server/              # Future MCP service boundary
├── AGENTS.md                # Agent operating instructions
├── README.md                # Top-level project overview
├── CONTRIBUTING.md          # Contribution workflow and expectations
└── SECURITY.md              # Security and credential handling guidance
```

## Notes

- The `docs/` folder is the source of truth for planning and architecture notes.
- The `automation/`, `infra/`, and `k8s/` folders are expected to grow as the implementation lands.
- The `mcp-server/` folder is reserved for the future API boundary described in the spec.
