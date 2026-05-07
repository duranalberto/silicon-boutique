# Contributing

## Principles

- Keep changes focused and easy to review.
- Update documentation when behavior changes.
- Prefer explicit configuration over hidden defaults.

## Before You Start

- Review [`README.md`](README.md).
- Review [`AGENTS.md`](AGENTS.md).
- Review the current planning docs in [`docs/`](docs/).

## Workflow

1. Work inside the devcontainer when possible.
2. Make the smallest useful change.
3. Validate the relevant subsystem.
4. Update documentation and runbooks if the change affects usage.

## Code and File Conventions

- Use ASCII unless a file already contains non-ASCII content.
- Keep Markdown direct and actionable.
- Favor clear filenames that describe intent.

## Infrastructure Changes

- Be careful with anything under `infra/`, `k8s/`, or `.github/workflows/`.
- Make teardown and cleanup behavior explicit.
- Never introduce secrets into tracked files.
