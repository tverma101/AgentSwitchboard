# Codex turn log

## 2026-08-29 — live remote-runner command removal

- `scope`: public AgentSwitchBoard default branch, limited to the retired remote Codespaces/CI provisioning command and its public references.
- `project`: `tverma101/AgentSwitchboard`; live baseline `7b3bcc866a380091f3168d9a06511fa8e9e8f352`.
- `status`: committed as `1d1f3c364bcff45658d0f134339ecf81411c573e` and pushed to the isolated remote branch `codex/remove-retired-runner-command`; the protected default branch is not yet updated.
- `changed`: removed the remote-runner CLI module and tests, removed its top-level dispatcher/help entry, deleted the obsolete runner-policy page, removed the stale CI-policy wording, and updated documentation contracts.
- `validation`: direct CLI probe confirmed the retired command is unknown; 64 targeted tests passed; Ruff format/lint passed; the final exact-reference scan passed. The repository CI tier reported 3718 passed, 4 skipped, 173 deselected, and two unrelated model-picker UI failures in untouched files; a bounded rerun reproduced one of those baseline failures and passed the other.
- `evidence`: current live branch was fetched from the verified GitHub remote before editing; no unrelated safety-branch changes were included.
- `residual_gap`: historical commits are not rewritten; a direct default-branch push was rejected because all five required status checks are expected. No workflow run or pull request was created.
- `next_action`: authorize the protected-branch pull-request/status-check workflow, then merge the already-pushed commit into the default branch.

## 2026-08-30 — TUI and repository-picker hardening

- `scope`: Textual and terminal control surfaces, shared selection picker, and local repository discovery/cache; no server protocol or provider behavior changes.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Documents/ChatGPT/Harness`; base `main` was synchronized to the verified remote before editing.
- `status`: committed as `2daf572`, pushed to `harness/codex/tui-hardening`, and opened as [PR #200](https://github.com/tverma101/AgentSwitchboard/pull/200) against `main`; it is not merged.
- `changed`: serialized page/filter/poll state, recoverable action errors, defensive payload normalization, bounded shutdown/input/rendering, authenticated-owner repository discovery, canonical deduplication, durable selection recency, cache failure reporting, model editor reconciliation, and settings snapshot rebinding; added `docs/troubleshooting/tui-hardening.md`.
- `validation`: focused TUI/repository suite passed 135 tests; `./scripts/ci.sh` passed with 3791 tests passed, 4 skipped, and 173 deselected; suppression scan, Ruff format/lint, `ty`, and `git diff --check` passed.
- `evidence`: implemented and locally tested only; installed/live macOS behavior, external GitHub authentication, GitHub Actions, and user visual confirmation remain separate evidence states.
- `residual_gap`: installed/live macOS behavior, external GitHub authentication, GitHub Actions, and user visual confirmation remain separate evidence states; no merge is authorized by this request.
- `next_action`: review PR #200 and merge only after the project maintainer completes the normal protected-branch review/check workflow.

## 2026-08-30 — registered provider visibility in Models

- `scope`: Models-tab provider filters and the loopback Admin model payload; no provider credentials, discovery cache contents, or upstream transport behavior changed.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Documents/ChatGPT/Harness`; follow-up branch `codex/tui-hardening` and PR #200.
- `status`: committed as `50d3c0c` and ready to push as a follow-up to PR #200; no merge or protected-branch mutation performed.
- `changed`: added a sanitized provider-status inventory to `/admin/api/models`, merged configured/usable providers with discovered model providers in both Models renderers, made empty states provider-specific and refreshable, and added API/TUI regressions plus release/documentation updates.
- `validation`: focused provider/model tests passed; `./scripts/ci.sh` passed with 3793 passed, 4 skipped, and 173 deselected; suppression scan, Ruff, `ty`, and `git diff --check` passed.
- `evidence`: implemented and locally tested; installed/live macOS behavior, provider network refresh, GitHub Actions, and user visual confirmation remain separate evidence states.
- `residual_gap`: a configured provider with no model-list result still requires an explicit `Refresh` and a healthy upstream endpoint; this is now visible and actionable instead of being omitted.
- `next_action`: push the verified topic branch and let PR #200 run the normal protected-branch review/check workflow.
