# Contributing

Thanks for helping improve Free Claude Code. Keep changes focused, test the behavior you change, and preserve the public Claude Code and Codex workflows.

## Before Opening A Pull Request

- Open an issue before proposing README changes.
- Do not open Docker integration pull requests.
- For bugs, include every model mapping, the active model when the failure occurred, the complete error, and reproducible steps.
- Add focused tests for behavior changes and relevant edge cases.
- Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing package boundaries, providers, protocol conversion, launchers, or messaging.

## Development Setup

Install [uv](https://docs.astral.sh/uv/) and Python 3.14, then run directly from the checkout:

```bash
git clone https://github.com/Alishahryar1/free-claude-code.git
cd free-claude-code
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

## GitHub CI And Missing Checks

The read-only [CI workflow](.github/workflows/tests.yml) runs for pull requests
targeting `main` or `master` and reports these required job names:

- `Ban suppressions and legacy annotations`
- `ruff-format`
- `ruff-check`
- `ty`
- `pytest`

Repository Actions must be enabled before a pull-request event can create these
checks. If a pull request has no check suite, first verify **Settings > Actions
> General** for the repository. For a run that already exists, use **Re-run
all jobs** in the Actions UI. For a missing run, use the manual trigger and
select the exact head branch:

```bash
gh workflow run CI --ref <pull-request-head-branch>
gh run list --workflow tests.yml --branch <pull-request-head-branch> --limit 1 \
  --json headSha,status,conclusion,url
```

The reported `headSha` must equal the pull request head SHA. A subsequent push
to the same pull-request branch should create a normal `synchronize` run; no
production-code change or fake status is needed to retrigger CI. Keep branch
protection configured by a repository administrator to require the five job
names above after the first successful run. Do not add self-mutating verifier
workflows or grant CI write access to source branches.

## Project Standards

- Target Python 3.14 and rely on native lazy annotations; do not add `from __future__ import annotations`.
- Python 3.14 supports multiple exception types without parentheses, such as `except TypeError, ValueError:`.
- Keep shared Anthropic protocol behavior under `src/free_claude_code/core/anthropic/` rather than importing utilities from another provider.
- Keep provider-specific configuration in the provider that owns it.
- Remove dead compatibility code when completing migrations unless preserving a published interface is explicitly required.

## Versioning

Changes to runtime code, packaging, dependencies, or install/CI scripts require a semantic version bump in `pyproject.toml` and a matching `uv lock` update in the same commit. Documentation, tests, smoke coverage, and repository configuration do not require a version bump by themselves.

See [ARCHITECTURE.md](ARCHITECTURE.md) for extension checklists and the full system design.
