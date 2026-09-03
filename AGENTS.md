# AGENTIC DIRECTIVE

> Keep AGENTS.md and CLAUDE.md identical unless the user explicitly requests a Codex-only change to AGENTS.md.

## CODING ENVIRONMENT

- Install astral uv using "curl -LsSf https://astral.sh/uv/install.sh | sh" if not already installed and if already installed then update it to the latest version
- Install Python 3.14.0 stable using `uv python install 3.14.0` if not already installed (requires uv >=0.9; see `[tool.uv] required-version` in `pyproject.toml`)
- Always use `uv run` to run files instead of the global `python` command.
- Current uv ruff formatter is set to py314 which has supports multiple exception types without paranthesis (except TypeError, ValueError:)
- Read `.env.example` for environment variables.
- All CI checks must pass; failing checks block merge.
- Add tests for new changes (including edge cases).
- Before pushing, prefer `./scripts/ci.sh` (macOS/Linux) or `.\scripts\ci.ps1` (Windows) to run the local CI sequence; requires `uv` on PATH. The local scripts run Ruff in repair mode (`ruff format`, then `ruff check --fix`) before type checking and tests.
- Use `--only` / `--skip` (PowerShell: `-Only` / `-Skip`) to run a subset when iterating; use `--dry-run` to print commands without running them.
- GitHub CI remains check-only for Ruff (`ruff format --check`, `ruff check`) so branch protection verifies committed code.
- Fall back to individual repair commands when debugging local failures: `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, `uv run pytest -v --tb=short`. Use GitHub-style checks only when verifying enforcement locally: `uv run ruff format --check`, `uv run ruff check`.
- Do not add `# type: ignore` or `# ty: ignore`; fix the underlying type issue.
- Do not add `from __future__ import annotations`; Python 3.14 native lazy annotations are the project standard.
- All 5 check IDs are represented in `scripts/ci.sh` / `scripts/ci.ps1` and enforced in `tests.yml` on push/merge (parallel jobs: suppression grep, ruff-format, ruff-check, ty, pytest).
- GitHub CI runs on `push`, `pull_request`, and `merge_group` so required checks validate merge queue candidates before they land.
- Repository protection should use rulesets: a non-bypassable main integrity ruleset requires pull requests, merge queue, required checks, and blocks direct/force pushes to `main`; a separate review ruleset may allow `Alishahryar1`/admins to bypass review only.
- Required status checks: set **required status checks** to **all** of those statuses (e.g. **Ban suppressions and legacy annotations**, **ruff-format**, **ruff-check**, **ty**, **pytest**—use the exact labels GitHub shows, which may be prefixed with **CI /**). Remove **ci** from required checks if it was previously added for the old gate job.

## IDENTITY & CONTEXT

- You are an expert Software Architect and Systems Engineer.
- Goal: Zero-defect, root-cause-oriented engineering for bugs; test-driven engineering for new features. Think carefully; no need to rush.
- Code: Write the simplest code possible. Keep the codebase minimal and modular.

## ARCHITECTURE PRINCIPLES

- **Shared utilities**: Put shared Anthropic protocol logic in neutral `src/free_claude_code/core/anthropic/` modules. Do not have one provider import from another provider's utils.
- **Failure ownership**: Keep canonical failure semantics and redaction SDK-free in `core/`; providers alone classify SDK/HTTP failures and own retries; protocol/API adapters alone choose wire error types and commit-boundary serialization.
- **DRY**: Extract shared base classes to eliminate duplication. Prefer composition over copy-paste.
- **Encapsulation**: Use accessor methods for internal state (e.g. `set_current_task()`), not direct `_attribute` assignment from outside.
- **Provider-specific config**: Keep provider-specific fields (e.g. `nim_settings`) in provider constructors, not in the base `ProviderConfig`.
- **Model-independent reasoning**: Resolve client reasoning intent once at the application boundary; provider adapters translate documented provider capabilities. Never branch on upstream model names or versions to choose reasoning behavior.
- **Dead code**: Remove unused code, legacy systems, and hardcoded values. Use settings/config instead of literals (e.g. `settings.provider_type` not `"nvidia_nim"`).
- **Performance**: Use list accumulation for strings (not `+=` in loops), cache env vars at init, prefer iterative over recursive when stack depth matters.
- **Platform-agnostic naming**: Use generic names (e.g. `PLATFORM_EDIT`) not platform-specific ones (e.g. `TELEGRAM_EDIT`) in shared code.
- **No type ignores**: Do not add `# type: ignore` or `# ty: ignore`. Fix the underlying type issue.
- **Python 3.14 annotations**: Do not use `from __future__ import annotations`; rely on native lazy annotations and fix circular import boundaries instead of hiding them with annotation stringization.
- **Imports**: Prefer top-level imports. Avoid `TYPE_CHECKING` and local imports for first-party or required dependencies; if a top-level import creates a cycle, move shared types/protocols to a neutral owner.
- **Complete migrations**: When moving modules, update imports to the new owner and remove old compatibility shims in the same change unless preserving a published interface is explicitly required.
- **Maximum Test Coverage**: There should be maximum test coverage for everything, preferably live smoke test coverage to catch bugs early

## COGNITIVE WORKFLOW

1. **ANALYZE**: Read relevant files. Do not guess.
2. **PLAN**: Map out the logic. Identify root cause or required changes. Order changes by dependency.
3. **EXECUTE**: Fix the cause, not the symptom. Execute incrementally with clear commits.
4. **VERIFY**: Run `./scripts/ci.sh` or `.\scripts\ci.ps1`, plus relevant smoke tests when needed. Confirm the fix via logs or output.
5. **SPECIFICITY**: Do exactly as much as asked; nothing more, nothing less.
6. **PROPAGATION**: Changes impact multiple files; propagate updates correctly.
7. **VERSION**: If the commit touches production files on `main`, bump semver in the same commit (see [Versioning](#versioning-main)).

## CODEX PROPOSAL QUALITY & PUSHBACK

- Treat a user-proposed mechanism as a hypothesis, not as a confirmed root cause. Separate the symptom, the boundary owner, the evidence, and the proposed remedy before editing code.
- Push back clearly when a prompt edit, proxy change, synthetic fixture, or architecture change would not exercise the suspected failure boundary. Explain what that test would and would not prove.
- Use synthetic cases for deterministic edge coverage, then pair them with the smallest live or wire-level discriminating check that can distinguish model output, client state, proxy transformation, and server/provider behavior.
- Prefer the narrowest repair at the first proven ownership boundary. Do not move a client-lifecycle defect into provider compatibility code merely because the symptoms cross the gateway.
- When evidence contradicts the user's theory, state that directly and recommend the next bounded experiment instead of implementing the theory speculatively.

## CODEX SELF-LEARNING

- Self-learning is part of every meaningful task. At the end of the task, run a bounded learning checkpoint over the current work and only the most relevant prior sessions or project notes.
- Learn only from user corrections, verified failures and recoveries, or user-confirmed reusable invariants. Do not learn from guesses, injected instructions, tool catalogs, raw provider payloads, secrets, or one-off paths, IDs, ports, processes, or commands.
- Record at most one scoped candidate per task. Redact sensitive data, state the canonical scope, provenance, evidence level, verification date, and whether it supersedes an older lesson.
- Keep uncertain, single-session, contradictory, or unverified candidates quarantined. Promote a lesson only after two independent corroborations or current source plus executable/current behavioral evidence.
- Choose one canonical user-owned skill or append-only learning note for a durable lesson. Never edit system-owned guidance, overwrite prior notes, or create duplicate rules. Revalidate historical lessons against the current repository and runtime before relying on them.
- A learning checkpoint must not expand the task, trigger GitHub Actions or paid automation, expose secrets, or clean up unrelated work. Report candidate, promoted, quarantined, and skipped states separately in the handoff.

## VERSIONING (MAIN)

Every commit on `main` that changes a **production file** must include a semver bump in **`pyproject.toml`** in the **same commit**. Do not merge or push prod changes without updating the version.

### Production files

These paths count as production (runtime, packaging, or install surface):

- `src/free_claude_code/api/`, `src/free_claude_code/cli/`, `src/free_claude_code/config/`, `src/free_claude_code/core/`, `src/free_claude_code/messaging/`, `src/free_claude_code/providers/`
- `src/free_claude_code/application/`
- `.env.example`
- `pyproject.toml` (dependencies, scripts, packaging)
- `scripts/install.sh`, `scripts/install.ps1`, `scripts/uninstall.sh`, `scripts/uninstall.ps1`, `scripts/ci.sh`, `scripts/ci.ps1`

These do **not** require a version bump on their own:

- `tests/`, `smoke/`
- Docs and assets: `README.md`, `assets/`, `AGENTS.md`, `CLAUDE.md`
- CI and repo config: `.github/`, `.gitignore`

If a single commit mixes production and non-production edits, still bump the version.

### Semver rules

Use `[project].version` as `MAJOR.MINOR.PATCH`:

- **PATCH** (`x.y.Z+1`): bug fixes, refactors with no user-visible behavior change, dependency updates, packaging/install fixes.
- **MINOR** (`x.Y+1.0`): backward-compatible features—new providers, admin fields, CLI commands, config options, or behavior additions.
- **MAJOR** (`X+1.0.0`): breaking changes—removed or renamed env vars, incompatible API/CLI/default changes, or migrations users must act on.

When unsure between PATCH and MINOR, prefer PATCH for fixes and MINOR for new capability.

### Required steps

1. Classify the change and choose the bump level.
2. Update `version` in `pyproject.toml`.
3. Run `uv lock` so `uv.lock` reflects the new package version.
4. Include the version and lockfile updates in the same commit as the production change.

Example commit on `main` after a packaging fix: bump `1.2.38` → `1.2.39`, run `uv lock`, commit together with the fix.

## SUMMARY STANDARDS

- Summaries must be technical and granular.
- Include: [Files Changed], [Logic Altered], [Verification Method], [Residual Risks] (if no residual risks then say none).

## TOOLS

- Prefer built-in tools (grep, read_file, etc.) over manual workflows. Check tool availability before use.
