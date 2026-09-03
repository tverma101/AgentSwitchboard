# Codex turn log

## 2026-08-29 — live remote-runner command removal

- `scope`: public AgentSwitchboard default branch, limited to the retired remote Codespaces/CI provisioning command and its public references.
- `project`: `tverma101/AgentSwitchboard`; live baseline `7b3bcc866a380091f3168d9a06511fa8e9e8f352`.
- `status`: committed as `1d1f3c364bcff45658d0f134339ecf81411c573e` and pushed to the isolated remote branch `codex/remove-retired-runner-command`; the protected default branch is not yet updated.
- `changed`: removed the remote-runner CLI module and tests, removed its top-level dispatcher/help entry, deleted the obsolete runner-policy page, removed the stale CI-policy wording, and updated documentation contracts.
- `validation`: direct CLI probe confirmed the retired command is unknown; 64 targeted tests passed; Ruff format/lint passed; the final exact-reference scan passed. The repository CI tier reported 3718 passed, 4 skipped, 173 deselected, and two unrelated model-picker UI failures in untouched files; a bounded rerun reproduced one of those baseline failures and passed the other.
- `evidence`: current live branch was fetched from the verified GitHub remote before editing; no unrelated safety-branch changes were included.
- `residual_gap`: historical commits are not rewritten; a direct default-branch push was rejected because all five required status checks are expected. No workflow run or pull request was created.
- `next_action`: authorize the protected-branch pull-request/status-check workflow, then merge the already-pushed commit into the default branch.

## 2026-08-30 — TUI and repository-picker hardening

- `scope`: Textual and terminal control surfaces, shared selection picker, and local repository discovery/cache; no server protocol or provider behavior changes.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; base `main` was synchronized to the verified remote before editing.
- `status`: committed as `2daf572`, pushed to `harness/codex/tui-hardening`, and opened as [PR #200](https://github.com/tverma101/AgentSwitchboard/pull/200) against `main`; it is not merged.
- `changed`: serialized page/filter/poll state, recoverable action errors, defensive payload normalization, bounded shutdown/input/rendering, authenticated-owner repository discovery, canonical deduplication, durable selection recency, cache failure reporting, model editor reconciliation, and settings snapshot rebinding; added `docs/troubleshooting/tui-hardening.md`.
- `validation`: focused TUI/repository suite passed 135 tests; `./scripts/ci.sh` passed with 3791 tests passed, 4 skipped, and 173 deselected; suppression scan, Ruff format/lint, `ty`, and `git diff --check` passed.
- `evidence`: implemented and locally tested only; installed/live macOS behavior, external GitHub authentication, GitHub Actions, and user visual confirmation remain separate evidence states.
- `residual_gap`: installed/live macOS behavior, external GitHub authentication, GitHub Actions, and user visual confirmation remain separate evidence states; no merge is authorized by this request.
- `next_action`: review PR #200 and merge only after the project maintainer completes the normal protected-branch review/check workflow.

## 2026-08-30 — registered provider visibility in Models

- `scope`: Models-tab provider filters and the loopback Admin model payload; no provider credentials, discovery cache contents, or upstream transport behavior changed.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; follow-up branch `codex/tui-hardening` and PR #200.
- `status`: committed as `50d3c0c` and ready to push as a follow-up to PR #200; no merge or protected-branch mutation performed.
- `changed`: added a sanitized provider-status inventory to `/admin/api/models`, merged configured/usable providers with discovered model providers in both Models renderers, made empty states provider-specific and refreshable, and added API/TUI regressions plus release/documentation updates.
- `validation`: focused provider/model tests passed; `./scripts/ci.sh` passed with 3793 passed, 4 skipped, and 173 deselected; suppression scan, Ruff, `ty`, and `git diff --check` passed.
- `evidence`: implemented and locally tested; installed/live macOS behavior, provider network refresh, GitHub Actions, and user visual confirmation remain separate evidence states.
- `residual_gap`: a configured provider with no model-list result still requires an explicit `Refresh` and a healthy upstream endpoint; this is now visible and actionable instead of being omitted.
- `next_action`: push the verified topic branch and let PR #200 run the normal protected-branch review/check workflow.

## 2026-08-30 — FCC usage attribution labels

- `scope`: FCC metadata-only usage ledger, account attribution, Admin usage view, and terminal usage surfaces; native Codex account snapshots remain separate.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; follow-up branch `codex/tui-hardening` and PR #200.
- `status`: implemented and locally validated; no merge or protected-branch mutation performed.
- `changed`: persisted `fcc_proxy` source and privacy-preserving per-account fingerprints, separated model totals by source/account/wire API, added legacy schema migration, and clarified Admin/TUI labels and usage documentation.
- `validation`: 30 focused regressions passed; `./scripts/ci.sh` passed with 3798 passed, 4 skipped, and 173 deselected; suppression scan, Ruff format/lint, `ty`, and `git diff --check` passed.
- `evidence`: implemented and locally targeted-tested; installed/live behavior, external account identity, GitHub Actions, and user visual confirmation remain separate evidence states.
- `residual_gap`: pre-migration events remain account-unidentified because historical account identity is not reconstructed.
- `next_action`: push this verified follow-up to PR #200 if publication is authorized; review/merge remains a separate maintainer action.

## 2026-08-31 — PR #210 native control center completion

- `scope`: PR #210 native Ratatui control center, loopback Admin API client, model catalog/routing display, provider secret/proxy editing, and GitHub-backed repository discovery; unrelated canonical-checkout work remains outside this branch.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; isolated task worktree `/private/tmp/agentswitchboard-pr210`; topic branch `refactor/posting-gui-shell`.
- `status`: implementation complete and locally validated; exact-head publication/checks and protected-branch merge remain the next lifecycle steps.
- `changed`: preserved the legacy launcher seam while routing to the native TUI; added a standalone `fcc-tui` script; made the native client tolerate the live Admin provider shape; exposed full catalog plus routable model state; preserved blank configured API keys/proxies; made repository discovery GitHub-only and exclude linked worktrees; added fail-closed discovery behavior, render coverage, release metadata, lockfile, and documentation.
- `validation`: full `uv run --no-sync pytest -q` passed with 3851 passed and 152 skipped; repository safe CI passed with 3825 passed, 4 skipped, and 173 deselected; Ruff/ty/suppression/diff checks passed; pinned Rust 1.88 format, Clippy, 14 Rust tests, and release build passed; live loopback config/model/validate smoke and release `fcc-tui` PTY startup passed without exposing secrets.
- `evidence`: implemented and locally tested; built release and live loopback behavior verified; installed-artifact and user visual confirmation remain separate evidence states; canonical `main` dirty changes were preserved.
- `residual_gap`: remote PR checks and merge confirmation are not established until the exact pushed head is green; no GitHub Actions workflow mutation is part of this work.
- `next_action`: stage only the confirmed PR paths, push `refactor/posting-gui-shell`, verify exact-head checks, then merge PR #210 and confirm the remote merge commit.

## 2026-09-03 — OpenAI backend preservation audit

- `scope`: current `feat/tui-tode-transplant` checkout; OpenAI/ChatGPT Codex provider, connected-account auth, Responses conversion/streaming, FCC API routes, and runtime composition only.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; HEAD `edcf45e1`; PR #210 commit `1487f11c`.
- `status`: backend source is present and wired; no OpenAI source changes were made by this audit. The working tree contains separate in-progress TUI transplant edits, which were preserved.
- `validation`: 396 focused OpenAI/provider/API/runtime tests passed; the full suite reported 3849 passed, 152 skipped, and 3 unrelated failures (Cline manifest inventory, documentation scan of ignored/untracked worktree files, and project-versus-installed version metadata).
- `evidence`: source and mocked/local contract behavior are verified; PR #210's file set does not remove the OpenAI provider. This does not establish a successful authenticated live ChatGPT upstream request.
- `residual_gap`: the previously observed live ChatGPT Codex path returned upstream HTTP 404, and the installed CLI metadata is `4.64.0` while the checkout declares `4.63.0`; live upstream and installed-artifact parity remain separate checks.
- `next_action`: if requested, repair the live ChatGPT endpoint/account failure and refresh the installed editable artifact after the TUI branch settles; do not merge or overwrite the in-progress TUI edits as part of this audit.
