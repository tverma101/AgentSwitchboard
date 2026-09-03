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

## 2026-09-03 — native model picker and installed TUI recovery

- `scope`: current `feat/tui-tode-transplant` checkout; native Ratatui Models page, Admin model-policy transaction, provider filter inventory, help/routing chrome, contract tests, and installed local control-center binary.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; HEAD remains `edcf45e1`; no commit, push, merge, PR-state change, or Actions mutation performed.
- `status`: implemented and installed locally; all source and repository tests are green. Existing unrelated/in-progress donor and TUI edits remain dirty and were preserved.
- `changed`: made active/routable models the default view; added explicit Catalog, registered-provider, and price filters; added deterministic exact-ID sorting, Space/Shift/Ctrl-click bulk selection, Enable selected, Disable selected, Disable all, and exact `MODEL` assignment; grouped catalog mode/allowlist writes behind Admin validate/apply; removed Models-page routing shortcuts and the decorative help path; excluded generated `.claude`/`.project-memory` trees from the docs contract; allowed custom Cline status without treating it as a built-in provider.
- `validation`: native Rust `cargo test` 48 passed; Clippy `-D warnings` passed; release build passed; `tests/cli/test_rust_tui.py` 35 passed; full `uv run --no-sync pytest -q` 3881 passed and 152 skipped; installed PTY smoke at 160x50 against live `127.0.0.1:8082` showed 2 active rows, 399 catalog rows, 18 Free-only rows, multi-selection, and registered B.AI empty-state behavior; built and installed SHA256 `5366a26494ab7c68f0bd4ded8bad56af6e9bfe9a9dbcfd845071fe98ec28e5f0`.
- `evidence`: implementation, local tests, optimized artifact, and installed-artifact PTY behavior are verified separately. The live server snapshot reports 2 active models and 399 cached catalog models; provider discovery/upstream proxy success for B.AI, Cline, and NVIDIA NIM is not claimed from this UI smoke.
- `residual_gap`: PID 90813 is a pre-existing old TUI process and was intentionally not killed; the next launch uses `/Users/tejas/.local/bin/fcc-control-center` at the recorded SHA. Provider refresh/authenticated multi-provider proxy behavior and user visual confirmation remain separate evidence states.
- `next_action`: relaunch the installed TUI after the user closes the old process, select the intended repository, and use Models > Catalog > registered provider > Refresh to populate any provider whose cache is empty; authorize a separate live provider smoke only if upstream requests need proving.

## 2026-09-03 — bounded navigation and Dashboard reorganization

- `scope`: native Ratatui workbench navigation, activity rail, Dashboard layout, and focused regression coverage; provider transport and server lifecycle remain unchanged.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; current branch `feat/tui-tode-transplant`; existing dirty work was preserved.
- `status`: implemented in the working tree; no commit, push, merge, PR-state change, or Actions mutation performed.
- `changed`: clamped main page/list selection instead of wrapping; gated Models shortcuts on editor focus; replaced the icon-only activity gutter with labeled destinations; replaced generic Dashboard prose with concrete server, route, model, provider, policy, workspace, and launch state; added narrow-terminal fallback and Rust regressions; updated the native control-center runbook and troubleshooting record.
- `validation`: native Rust tests passed with 51 passed; Clippy with warnings denied passed; optimized release build passed; `tests/cli/test_rust_tui.py` passed with 35 passed; full `uv run --no-sync pytest -q` passed with 3881 passed and 152 skipped; `git diff --check` and `cargo fmt --check` passed. The installed release and source release artifact match SHA256 `c7186f6c0e4a4e260e12877ab5439142aff1b8024321752e67a69d355f8119c2`. Fresh installed PTY smoke at compact and 160x50 sizes confirmed the Dashboard cards/actions, named activity rail, exact route display, bounded model cursor, and the `Set MODEL` action label.
- `evidence`: implementation, source tests, optimized artifact, installed-artifact behavior, and live loopback rendering are verified separately; user visual confirmation is not claimed.
- `residual_gap`: the existing live provider snapshot still does not prove B.AI, Cline, or NVIDIA NIM discovery/proxy success; the already-running old TUI process must not be treated as the rebuilt artifact.
- `next_action`: user can relaunch the installed TUI after closing any older running TUI process; provider discovery/authenticated proxy validation remains a separate live-provider task if requested.

## 2026-09-03 — restore the direct AgentSwitchboard shell

- `scope`: visible native TUI shell and its FCC command inventory; provider transport, model catalog semantics, server lifecycle, and existing workspace compatibility code remain outside this UI cleanup.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; current branch `feat/tui-tode-transplant`; existing dirty work was preserved.
- `status`: implemented and installed locally; no commit, push, merge, PR-state change, or Actions mutation performed.
- `changed`: removed the rendered activity rail, fake traffic-light controls, file-tab strip, duplicate workspace sidebar dispatch, and permanent keyboard-help legend; made the remaining sidebar a direct FCC page navigator with keyboard focus; removed editor/workspace actions from the command inventory; updated the native shell, configuration, transplant decision record, troubleshooting record, and regressions.
- `validation`: native Rust `cargo test` passed with 52 passed; Clippy with warnings denied passed; `cargo fmt --check` passed; optimized release build passed; `tests/cli/test_rust_tui.py` passed with 35 passed; full `uv run --no-sync pytest -q` passed with 3881 passed and 152 skipped; fresh installed PTY at 160x50 showed direct `CONTROL CENTER` page navigation with no activity rail, Explorer/Search/Source Control labels, fake traffic lights, file tabs, or footer help; source and installed release match SHA256 `a82d6a4415db1e8e4df4948bcc124ec80905405c12d0882f448373863ded064f`.
- `evidence`: implementation, source tests, optimized artifact, installed-artifact behavior, and fresh loopback PTY rendering are verified separately; user visual confirmation is not claimed.
- `residual_gap`: legacy explicit-file compatibility code remains non-rendered and is not exposed by the FCC palette; the currently running user session was not restarted or otherwise mutated by this change. Provider discovery/authenticated proxy success and end-to-end Claude launch remain separate live-provider evidence.
- `next_action`: close/relaunch the currently visible TUI to load the installed binary if its process predates this artifact; then visually confirm the direct shell and continue provider/proxy debugging separately if needed.

## 2026-09-03 — explicit provider/catalog controls and live status repair

- `scope`: current `feat/tui-tode-transplant` checkout and PR #215; native Models and Providers pages, connected-account status, model-policy saves, model discovery policy, and installed control-center artifact.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; base HEAD before this turn `aff93c5b`; no unrelated dirty paths were removed.
- `status`: implemented, fully locally tested, rebuilt, installed, and exercised against a task-owned loopback server; publication remains the next lifecycle step.
- `changed`: made Active versus Catalog an explicit finite view; added a registered-provider picker and All/Free-only filter; removed redundant Enable/Disable-selected actions in favor of `Toggle selected` plus `Disable all`; kept exact provider/model IDs in the inspector; removed price noise, routing marketing, and decorative help; wrapped compact summaries and empty states; overlaid live connected-account status without rendering OAuth payloads; made model-policy saves background transactions with refresh/operation locking; separated configured metadata discovery permission from inference egress policy; removed stale command-palette labels.
- `validation`: `cargo test` passed with 76 passed; Clippy with warnings denied and `cargo fmt --check` passed; full `uv run --no-sync pytest -q` passed with 3887 passed and 152 skipped; Ruff format/lint, `ty`, compileall, and `git diff --check` passed. Source and installed release binary match SHA256 `21ab75d92903765db402c9cd15def247b62e47746a8214f23b68950ebfc2a78e`.
- `live_evidence`: task-owned `fcc-server --headless` was healthy on `127.0.0.1:8082`; Admin config reported OpenAI / ChatGPT `Connected`; Models reported 6 active, 1017 catalog, 69 free, and zero failed providers; installed PTY checks at 160x50 and 80x24 showed the full catalog toggle, compact wrapped summary, explicit 11-provider picker, Cline 425-row catalog, and Cline 18-row Free-only view.
- `evidence`: implementation, source tests, optimized artifact, installed-artifact behavior, and loopback API/rendering are verified separately; no authenticated upstream inference request was issued by this turn, so provider proxy success and user visual confirmation remain separate evidence states.
- `residual_gap`: remote PR checks, external provider inference, and merge are not established; the task-owned tmux server/TUI sessions should be cleaned after publication, while any user-owned session must remain untouched.
- `next_action`: review the confirmed diff, commit the topic-branch changes, push `feat/tui-tode-transplant` to update PR #215, verify exact remote head, then report merge as a separate maintainer action.
