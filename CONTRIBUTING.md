# Contributing

Thanks for helping improve AgentSwitchboard. Keep changes focused, test the behavior you change, and preserve the public Claude Code and Codex workflows. The repository originated from Free Claude Code; retain that upstream attribution when touching derived code.

## Before Opening A Pull Request

- Read the [documentation catalogue](docs/README.md) and [documentation maintenance policy](docs/DOCUMENTATION.md) before adding or changing documentation.
- Open an issue before proposing README changes.
- Do not open Docker integration pull requests.
- For bugs, include every model mapping, the active model when the failure occurred, the complete error, and reproducible steps.
- Add focused tests for behavior changes and relevant edge cases.
- Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing package boundaries, providers, protocol conversion, launchers, or messaging.

## Development Setup

Install [uv](https://docs.astral.sh/uv/) and Python 3.14, then run directly from the checkout:

```bash
git clone https://github.com/tverma101/AgentSwitchboard.git
cd AgentSwitchboard
uv python install 3.14.0
uv run fcc-server
```

Use `uv run` for Python commands. Do not run the project with a global Python interpreter.

## Quality Checks

Run the complete local CI sequence before opening a pull request:

```bash
./scripts/ci.sh
```

```powershell
.\scripts\ci.ps1
```

Useful iteration flags are `--only`, `--skip`, and `--dry-run` on macOS/Linux, or `-Only`, `-Skip`, and `-DryRun` in PowerShell.

Individual repair and test commands:

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run pytest -v --tb=short
```

GitHub CI runs Ruff in check-only mode and also bans `# type: ignore`, `# ty: ignore`, and legacy annotation workarounds. Fix underlying typing and import-boundary problems instead of suppressing them.

### GitHub Actions checks and manual retrigger

Every pull request targeting `main` should receive the `CI` workflow on its exact head SHA. The required job names emitted by the workflow are:

- `Ban suppressions and legacy annotations`
- `ruff-format`
- `ruff-check`
- `ty`
- `pytest`

A normal push to the pull-request branch should trigger a fresh `pull_request` run automatically. Do not create a no-op production-code change just to make Actions run.

If a run exists but a job was cancelled or failed for an infrastructure reason, use **Actions -> CI -> Re-run jobs** in GitHub, or with GitHub CLI:

```bash
gh run rerun <run-id> --failed
```

If the pull request has no run at all, dispatch the same workflow against the existing PR head branch without changing repository content:

```bash
gh workflow run tests.yml --ref <pr-head-branch>
gh run list --workflow tests.yml --branch <pr-head-branch>
```

Before treating the result as merge evidence, verify the workflow run's head SHA is the pull request's current head SHA. A stale green run is not merge evidence. Repository branch protection should require the five check names above; changing or weakening the workflow to manufacture a green status is not an acceptable retrigger strategy.

## Project Standards

- Target Python 3.14 and rely on native lazy annotations; do not add `from __future__ import annotations`.
- Python 3.14 supports multiple exception types without parentheses, such as `except TypeError, ValueError:`.
- Keep shared Anthropic protocol behavior under `src/free_claude_code/core/anthropic/` rather than importing utilities from another provider.
- Keep provider-specific configuration in the provider that owns it.
- Remove dead compatibility code when completing migrations unless preserving a published interface is explicitly required.

## Versioning

Changes to runtime code, packaging, dependencies, or install/CI scripts require a semantic version bump in `pyproject.toml` and a matching `uv lock` update in the same commit. Documentation, tests, smoke coverage, and repository configuration do not require a version bump by themselves.

See [ARCHITECTURE.md](ARCHITECTURE.md) for extension checklists and the full system design.
