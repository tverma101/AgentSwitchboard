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

## 2026-08-29 — public safety cleanup

- `scope`: public AgentSwitchBoard repository content, launchers, defaults, installers, tests, receipts, and safety documentation.
- `project`: `tverma101/AgentSwitchboard` (`harness` remote); canonical local checkout is `/Users/tejas/Documents/ChatGPT/Harness`.
- `status`: implemented and locally tested on isolated branch `codex/public-safety-cleanup`; not pushed or merged.
- `canonical_doc`: this file, with behavior details in `README.md`, `ARCHITECTURE.md`, and `docs/CONFIGURATION.md`.
- `rollout_refs`: none.
- `last_verified`: 2026-08-29; public `main` baseline `bfde744d6595d3ed9cc802b61272077c384cf55b`.
- `goal`: remove publicly available permission bypasses, remote-runner automation, unrestricted Computer Use bridging, unsafe network defaults, weak example credentials, unsafe installer hints, and stale evidence that advertised those capabilities.
- `changed`: removed the `fccdanger` launcher and permission-bypass forwarding paths, and made `fcc-claude` reject bypass arguments; removed `fcc burst`, its self-hosted-runner documentation, and tests; removed the unrestricted legacy Computer Use bridge; changed Computer Use to decline-by-default; bound the server to loopback by default and require a token off-loopback; replaced the shared example token and pipe-to-shell hints; disabled raw-payload logging in live smoke probes; corrected installer ownership metadata; sanitized receipts/docs and updated contracts/tests.
- `validation`: `./scripts/ci.sh` passed with Ruff format, Ruff lint, `ty`, and `3705 passed, 4 skipped, 173 deselected`; `./scripts/ci.sh --only pytest --installers` passed with `82 passed, 66 skipped`; `git diff --check`, POSIX shell syntax, and all smoke-receipt JSON validation passed. PowerShell parsing was not run because `pwsh` is unavailable on this host.
- `evidence`: implementation and local deterministic/installer tests are confirmed; installation, live service behavior, integration, interactive behavior, and user confirmation are not claimed.
- `residual_gap`: the public GitHub repository remains unchanged until an authorized review/push; GitHub secret scanning and Dependabot security updates are disabled in the repository settings; live/integration/interactive checks were intentionally not run. Legacy `fccdanger` remains only in installer/uninstaller stop lists and their cleanup fixtures so upgrades can terminate an old process safely; it is not installed, exposed in help, or launched.
- `next_action`: review the isolated diff, then explicitly authorize publication if desired.
- `memory`: no global memory update; durable implementation detail is kept in this repository log and the linked authoritative docs.

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
- `project`: `tverma101/AgentSwitchboard`; follow-up branch `codex/tui-hardening` and PR #200.
- `status`: committed as `50d3c0c` and ready to push as a follow-up to PR #200; no merge or protected-branch mutation performed.
- `changed`: added a sanitized provider-status inventory to `/admin/api/models`, merged configured/usable providers with discovered model providers in both Models renderers, made empty states provider-specific and refreshable, and added API/TUI regressions plus release/documentation updates.
- `validation`: focused provider/model tests passed; `./scripts/ci.sh` passed with 3793 passed, 4 skipped, and 173 deselected; suppression scan, Ruff, `ty`, and `git diff --check` passed.
- `evidence`: implemented and locally tested; installed/live macOS behavior, provider network refresh, GitHub Actions, and user visual confirmation remain separate evidence states.
- `residual_gap`: a configured provider with no model-list result still requires an explicit `Refresh` and a healthy upstream endpoint; this is now visible and actionable instead of being omitted.
- `next_action`: push the verified topic branch and let PR #200 run the normal protected-branch review/check workflow.

## 2026-08-30 — FCC usage attribution labels

- `scope`: FCC metadata-only usage ledger, account attribution, Admin usage view, and terminal usage surfaces; native Codex account snapshots remain separate.
- `project`: `tverma101/AgentSwitchboard`; follow-up branch `codex/tui-hardening` and PR #200.
- `status`: implemented and locally validated; no merge or protected-branch mutation performed.
- `changed`: persisted `fcc_proxy` source and privacy-preserving per-account fingerprints, separated model totals by source/account/wire API, added legacy schema migration, and clarified Admin/TUI labels and usage documentation.
- `validation`: 30 focused regressions passed; `./scripts/ci.sh` passed with 3798 passed, 4 skipped, and 173 deselected; suppression scan, Ruff, `ty`, and `git diff --check` passed.
- `evidence`: implemented and locally targeted-tested; installed/live behavior, external account identity, GitHub Actions, and user visual confirmation remain separate evidence states.
- `residual_gap`: pre-migration events remain account-unidentified because historical account identity is not reconstructed.
- `next_action`: push this verified follow-up to PR #200 if publication is authorized; review/merge remains a separate maintainer action.
