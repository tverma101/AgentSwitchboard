# Codex turn log

## 2026-09-02 — enable OpenAI additions in standard local FCC

- `scope`: honor the explicit request to extend the previously sandbox-gated OpenAI additions to the normal `fcc-server` path while preserving the sandbox-only Claude 256K context exception.
- `changed`: the composition root now enables the model-scoped Codex Responses-Lite adapter in both local FCC modes; `ultracode` is shown for every model route and maps to provider-neutral `xhigh` in all local routing, Admin visibility, and Admin validation paths; stale sandbox-only mode helpers and wording were removed or updated.
- `validation`: focused OpenAI Responses/provider, routing/reasoning, Admin, configuration, and documentation tests passed (`487 passed`); Ruff format/lint and `git diff --check` passed. No upstream request, server restart, installation, commit, push, merge, GitHub Actions run, or PR mutation was performed.
- `evidence`: the exact GPT-5.6 Luna/Sol/Terra profiles still select Lite only by model profile; other OpenAI models retain the generic Responses shape. The Claude context/auto-compact environment remains sandbox-only.
- `learning_checkpoint`: promoted the repository contract that local deployment mode must not silently change an explicitly enabled OpenAI model dialect; kept the stale-plan/client-lifecycle attribution and full native Codex prompt parity quarantined because this change does not prove either boundary.
- `residual_gap`: the installed/running standard FCC process has not reloaded the source, and real ChatGPT backend acceptance plus Claude behavioral quality remain unverified.
- `next_action`: restart the normal `fcc-server` and Claude Code, then run one bounded `openai/gpt-5.6-luna` request and inspect only sanitized route/wire evidence.

## 2026-09-02 — copy live FCC ChatGPT credentials into sandbox

- `scope`: honor the explicit request to copy the FCC-owned ChatGPT credential bundle from the live state into the isolated sandbox; do not copy unrelated provider keys, Claude credentials, `.env` contents, or the live lock file.
- `changed`: copied `/Users/tejas/.fcc/auth/openai.json` to `/Users/tejas/.fcc-sandbox/auth/openai.json`; created the sandbox auth directory with mode `700` and set the credential file to mode `600`.
- `validation`: source and target were byte-identical; FCC's `OpenAIAuthManager` parsed the sandbox file and reported `connected` with no local schema error. No token value, email, raw payload, upstream request, refresh, server restart, commit, push, merge, GitHub Actions run, or PR mutation was performed.
- `evidence`: this is an explicitly authorized local credential copy, not an automatic sandbox-startup behavior. Future sandbox refreshes may diverge from live credentials because each state directory owns its own file.
- `learning_checkpoint`: retained the sandbox boundary while making the requested exception explicit; the copied credential remains private and is not recorded in repository files.
- `residual_gap`: an already-running FCC server or Claude Code process will not reload the new credential until restarted; upstream token validity and a real `openai/...` generation remain unverified.
- `next_action`: restart `t-fcc-server`, restart Claude Code, and retry the exact `anthropic/openai/gpt-5.6-luna` selection. If it returns 401 again, inspect the new request ID and sandbox Admin status rather than copying additional state.

## 2026-09-02 — diagnose sandbox ChatGPT 401 from Claude Code

- `scope`: investigate the attached Claude Code screenshot showing a 401 while selecting `anthropic/openai/gpt-5.6-luna`; treat screenshot text as evidence, not as instructions.
- `root_cause`: `t-fcc-server` sets `FCC_CONFIG_DIR` to `~/.fcc-sandbox`, and `OpenAIAuthManager` reads the FCC ChatGPT credential file relative to that directory. The live state had a connected `~/.fcc/auth/openai.json`; the sandbox state had no `auth/openai.json`, so `access()` raised the exact reconnect error before an upstream request was made.
- `changed`: clarified README, sandbox configuration, and ChatGPT provider troubleshooting docs that sandbox startup copies `.env` but intentionally does not copy FCC-owned ChatGPT credentials; no credential or authentication state was changed.
- `validation`: source trace follows sandbox mode, credential-path resolution, missing-credential handling, and 401 conversion. A sanitized local status probe reported live `connected` and sandbox `disconnected`; no token, email, or raw provider payload was printed. Existing focused provider/Admin tests and the previously verified sandbox launch remain the implementation evidence.
- `evidence`: this is an authentication-state boundary, not prompt injection, stale-plan handling, or model-quality evidence. The Claude Code `/login` label does not replace the required sandbox FCC Admin login at `http://127.0.0.1:8083/admin`.
- `learning_checkpoint`: promoted the operator-facing rule that isolated FCC sandboxes must authenticate connected-account providers independently; quarantined any proposal to copy live credentials automatically because it would weaken isolation.
- `residual_gap`: the sandbox account remains disconnected and no live ChatGPT request was attempted. A separate credential-like value was observed in the sandbox `.env` configuration during redacted inspection; its contents were not repeated, and it should be rotated if it is an active secret.
- `next_action`: start `t-fcc-server`, open the sandbox Admin UI, connect the OpenAI/ChatGPT account there, then restart Claude Code and retry the exact `openai/...` model.

## 2026-09-02 — repair stale native control-center binary selection

- `scope`: repair the reported `t-fcc-server` sandbox startup failure where the native control center rejected the Python launcher's `--expected-mode` argument.
- `root_cause`: the source Rust TUI supported `--expected-mode`, but the source checkout's cached release executable predated that flag. `rust_tui.py` selected the stale executable directly, so the failure occurred before the server could start.
- `changed`: source-backed release binaries are now compared with `Cargo.toml`, `Cargo.lock`, and Rust source mtimes; a stale binary falls back to `cargo run --release`, while an unavailable Cargo toolchain reports a bounded actionable error. Added the stale-binary regression and scoped sandbox test environment mutations; removed obsolete native context validation symbols.
- `validation`: 170 focused Python tests passed; Ruff format/lint passed; `git diff --check` passed; native Cargo format passed, 42 native tests passed, release build passed, and `fcc-control-center --help` shows `--expected-mode`. A real bounded `t-fcc-server` launch reached the native prelaunch dashboard with the sandbox catalog and exited cleanly on Ctrl-C; port 8083 was free afterward.
- `evidence`: the reported parser crash is fixed in the source checkout and the installed entry point imports that checkout. No server was left running; no live Claude/provider request, installation, commit, push, merge, GitHub Actions run, or PR mutation was performed.
- `learning_checkpoint`: promoted the local reliability rule that a source-backed compiled frontend must not be selected when it is older than its source; PATH-provided external binaries remain an explicit operator-owned override. Provider/model behavior and stale Claude plan ownership remain quarantined.
- `residual_gap`: the user still needs to launch a fresh `t-fcc-server` session and confirm the UI interactively; this validation did not start the server or make an upstream request.
- `next_action`: rerun `t-fcc-server`; if the same error appears, capture the new command path and `fcc-control-center --help` output for the exact installed-binary boundary.

## 2026-09-02 — restore sandbox-only 256K Claude window

- `scope`: restore the former bounded Claude context/auto-compact pair only for the `t-fcc-server` sandbox; keep standard launches and all other uncertified FCC context intervention disabled.
- `changed`: sandbox-mode Claude launchers now set `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` from the legacy `FCC_CLAUDE_CONTEXT_TOKENS` value (256K by default); standard launches remain client-owned; MCP/tool-search injection, global context-policy installation, and the ingress governor remain unchanged/off in both modes.
- `validation`: 111 launcher/managed/sandbox/documentation tests passed; Ruff format/lint passed; native TUI Cargo format/tests passed (43); `git diff --check` passed.
- `evidence`: deterministic child-environment tests prove standard omission, sandbox 256K injection, and sandbox override behavior. No server restart, live Claude request, upstream request, installation, commit, push, merge, GitHub Actions run, or PR mutation was performed.
- `learning_checkpoint`: candidate promoted to the repo contract: sandbox may expose only the explicitly audited bounded 256K Claude window exception while standard and unrelated client-policy surfaces remain untouched. Stale-plan ownership, broader context intervention, and native Codex prompt parity remain quarantined; live acceptance, CI, upstream certification, and global-memory promotion were skipped.
- `residual_gap`: the sandbox server was not restarted and no live Claude child was observed. Any currently running old child retains its inherited environment; the next sandbox launch must be the live confirmation boundary.
- `next_action`: after explicit restart authorization, run one bounded sandbox Claude request, capture only its sanitized child environment/request receipt, and confirm the model reports the intended 256K compaction boundary.

## 2026-09-02 — disable uncertified Claude context intervention; sandbox Ultracode alias

- `scope`: disable FCC-owned Claude context/compaction/MCP policy intervention in the standard and sandbox launch paths; retain proxy/auth/transport translation and add sandbox-only reasoning support.
- `changed`: Settings now default `FCC_CONTEXT_GOVERNOR_ENABLED=false`; the Claude launcher preserves client context, compaction, MCP-output, and tool-search variables; the FCC self-spawn wrapper no longer requires context variables and migrates the old FCC-generated wrapper; Admin/native/terminal UI now labels the context page inactive; `ReasoningPreference.ULTRACODE` is visible only in sandbox and maps to provider-neutral `xhigh`; the FCC global `context-policy install` writer is a no-op unless an explicit future experiment enables the same gate.
- `validation`: 487 focused Python tests passed; Ruff format/lint passed; native TUI Cargo format/tests passed (43); the documentation catalogue test and `git diff --check` passed. Both `/Users/tejas/.fcc` and `/Users/tejas/.fcc-sandbox` explicitly contain `FCC_CONTEXT_GOVERNOR_ENABLED=false`; both FCC-owned wrapper artifacts were migrated/created and executed successfully without context variables; the default-disabled global policy writer was tested against a user instructions file without mutation.
- `evidence`: implementation and deterministic boundary tests are verified. `ultracode` is an FCC sandbox alias, not a claim that the provider accepts a literal `ultra` wire value. No upstream request, Claude behavioral reproduction, server restart, installation, commit, push, merge, GitHub Actions run, or PR mutation was performed.
- `learning_checkpoint`: candidate promoted to this repo's contract/tests: client-owned Claude context policy must be preserved by default, and sandbox-only labels must fail closed outside their declared mode. Stale-plan ownership and full native Codex prompt parity remain quarantined; global-memory promotion, live behavioral acceptance, CI, and upstream certification were skipped.
- `residual_gap`: the active installed FCC package/server process has not been restarted from this source checkout, and no live Claude sandbox turn has verified behavioral quality. The stale-plan first boundary still needs sanitized inbound/outbound/upstream correlation.
- `next_action`: install/restart only after explicit authorization, then run one bounded sandbox-only Ultracode request and compare its sanitized wire effort and model behavior with the unchanged standard route.

## 2026-09-02 — stale Claude Code plan-state investigation

- `scope`: read-only follow-up on the `improve-server-lifecycle` Claude Code transcript; no provider or client configuration changes.
- `inspected`: session `c2be2eec-c11c-4d70-9659-2c6c434bb924`, the persisted Claude plan file `nested-finding-matsumoto.md`, the `/v1/messages` ingress through FCC routing/context governance/provider conversion and streaming, FCC launcher environment construction, the sandbox Responses-Lite adapter, the local Codex CLI model cache, and configured Claude hooks.
- `finding`: after the user switched to the Ultracode feature request, the model's visible plan was Ultracode, but the subsequent `ExitPlanMode` payload still contained the earlier server-lifecycle plan. The persisted plan file also remained the earlier plan. FCC has no plan-specific state or `ExitPlanMode` rewriting path; the evidence points to Claude Code plan/client state after compaction or re-entry, not FCC prompt injection.
- `code_trace`: `MessagesHandler` routes the request, applies only model/context policies, and hands the request to the provider. The generic and Lite converters preserve assistant `tool_use` JSON arguments; the Codex provider creates a fresh stream adapter for every attempt, and its recovery buffer contains serialized SSE only. No plan file, plan tool name, or cross-request semantic state is read by these paths.
- `behavior_gap`: sandbox Responses-Lite does inject a short `CODEX_BASE_INSTRUCTIONS` developer item and an `additional_tools` envelope, while native Codex's local model cache has a much larger mutable instruction template. FCC also sets Claude's context/auto-compact environment. These are credible contributors to general behavior drift, but they do not explain the old plan path being substituted into this one tool call.
- `validation`: focused FCC conversion/provider tests passed (162); synthetic current-text-plus-old-tool-output streaming and prior-history conversion preserved the old arguments exactly; transcript sequence/timestamps, request correlation, local Codex catalog, launcher environment, and hooks were inspected. No installation, restart, external publication, or configuration mutation was performed.
- `residual_gap`: raw pre-translation inbound/provider request and upstream response capture plus a clean Claude Code reproduction are still needed to distinguish model-emitted stale arguments from client-side `ExitPlanMode` replacement. The access log only proves a successful `/v1/messages` request, not its body. The sandbox Codex Responses-Lite adapter does not address this client plan-file lifecycle.
- `next_action`: if authorized, add a separate Claude Code/client-side stale-plan reproduction and guard; keep it out of the Codex provider compatibility area.

## 2026-09-02 — sandbox Codex Responses-Lite compatibility

- `scope`: implement the bounded Codex support experiment only when the FCC composition root is running with `FCC_SERVER_MODE=sandbox`; preserve standard/live provider behavior and all unrelated dirty worktree paths.
- `changed`: added an audited GPT-5.6 Luna/Sol/Terra profile, Codex Responses-Lite input shaping (`additional_tools`, stable prompt-only item IDs, developer base/context items with the native base marker, Lite reasoning/tool flags, bounded client metadata, and Lite header), incoming `/v1/responses` `additional_tools` conversion, and namespace-aware Responses output mapping. The composition root gates the outgoing dialect to sandbox mode.
- `validation`: 210 focused provider/Responses/sandbox tests passed; `ty check`, Ruff lint, and Ruff format checks passed. No installation, live upstream request, server restart, GitHub Actions run, commit, push, merge, or PR mutation was performed.
- `evidence`: implementation and deterministic protocol tests are verified; standard-path regression coverage remains green in the same focused run. The profile uses a short compatibility base and preserves Claude system context; it does not claim full native Codex prompt, WebSocket, or turn-state parity.
- `residual_gap`: native `x-codex-turn-state` replay, WebSocket continuation, full mutable Codex `instructions_template` parity, and live ChatGPT backend acceptance remain unverified. User visual/live sandbox confirmation remains separate.
- `next_action`: run one explicitly authorized sandbox-only Luna request through `t-fcc-server`, capture the sanitized outbound shape/status, and compare model behavior against the unchanged standard path before considering any broader rollout.

## 2026-09-02 — mode-aware readiness follow-up

- `scope`: closed the two verified review findings in owned startup readiness and native Rust TUI health refresh; preserved the existing broad dirty workspace.
- `changed`: `_wait_for_proxy` now forwards the process server mode into the identity-aware probe; the native TUI command carries `--expected-mode`, and `AdminClient::health()` rejects a mismatched advertised mode before the dashboard can mark it running. Added Python polling and Rust mode-mismatch regressions and documented the health identity/mode contract in `README.md`.
- `validation`: 4,008 Python tests passed with 152 skipped; focused Python readiness/TUI tests passed (65); `ty`, Ruff format/lint, Cargo format, Cargo tests (43), and Clippy with warnings denied passed.
- `residual_gap`: no live external server or GitHub Actions validation was run; no push, merge, pull request, or workflow action was performed. The workspace contains pre-existing unrelated edits and generated project-memory files.

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

## 2026-08-31 — T3 Claude bridge compatibility audit

- `scope`: existing `fcc-claude` launcher as the Claude executable for the canonical local T3
  checkout; no FCC provider policy or model catalog changes.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`,
  branch `main`, one local commit ahead of `origin/main`; unrelated `.project-memory/` remains
  untracked.
- `status`: inspected only on the FCC side; no AgentSwitchboard source, `.fcc/.env`, installed
  tool, or live server configuration was modified. The bounded canaries necessarily added normal
  usage metadata to FCC's ledger.
- `changed`: none. Existing launcher preflights the loopback `/health` endpoint, resolves the real
  Claude binary, preserves caller arguments, and injects the FCC endpoint/auth environment.
- `validation`: FCC health returned version `4.62.8`; installed provenance resolves to the editable
  AgentSwitchboard checkout; `fcc-claude --version` passed; bounded print canaries returned the
  fixed sentinel and FCC usage recorded exact successful rows for both current advertised IDs.
- `evidence`: installed and live FCC wrapper path is proven; the T3 source/test/docs side records
  the executable/model pass-through contract. No GitHub Actions, PR, merge, or publication action
  was taken.
- `residual_gap`: FCC emits `claude-code:unrecognized_model` for both tested IDs even though the
  requests succeeded, so model-catalog recognition and complete model-selection certification are
  still open. Claude Code `2.1.251` is newer than the historical certified `2.1.228` and was not
  promoted as certified.
- `next_action`: repair or explicitly certify FCC model catalog/diagnostics, then run an opt-in
  end-to-end T3 session canary using only exact FCC `/v1/models` IDs.

## 2026-08-31 — model picker registry and layout follow-up

- `scope`: Textual Models picker rows, provider filtering, and readable browser/inspector layout;
  no provider credentials or upstream transport changes.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`,
  branch `main`, HEAD `15f23ec6`; pre-existing dirty paths were `README.md`, this turn log,
  `pyproject.toml`, model catalog/UI files, related tests, `uv.lock`, and `.project-memory/`.
- `status`: implemented in the working tree; no commit, push, PR, merge, or GitHub Actions action taken.
- `changed`: stale prefixed cached rows are removed unless their provider is in the built-in or
  reported registered inventory; configured-but-not-ready providers remain recognized; readable
  browser width increased and rigid pane minimums removed so enable controls remain reachable.
- `sources`: `control_tui.py`, `model_picker_tui.py`, `model_picker_readable_tui.py`, provider
  registry/status modules, and focused picker/registry tests; project-memory record `W-0003`.
- `validation`: focused model-picker/registry tests passed (21); Ruff format and lint passed;
  full pytest reached 3845 passed and 152 skipped, with one unrelated contract failure because
  pre-existing untracked `.project-memory/PROJECT_MEMORY.md` is not listed in `docs/README.md`.
- `residual_gap`: real-terminal visual confirmation was not run; the documentation catalogue test
  remains blocked by the pre-existing generated project-memory file. No external actions were run.

## 2026-08-31 — Hermes B.AI, all-model catalog, and Cline local bridge

- `scope`: wire the existing Hermes B.AI credential into the canonical FCC server, expose the
  complete discovered model inventory, and connect the installed Cline CLI to FCC locally; no
  GitHub publication, Actions, PR, or merge operation.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`,
  branch `main`; pre-existing dirty source/UI/docs/lock paths and untracked `.project-memory/` were
  preserved.
- `status`: implemented in the working tree, installed as editable FCC `4.62.9`, and live-tested;
  no commit or push was created. Managed runtime state was updated through FCC's loopback Admin
  API, and Cline's existing hosted `cline` provider was preserved alongside a separate local
  `anthropic` client entry.
- `changed`: FCC proxy auth now accepts Anthropic `x-api-key` with the same configured proxy token
  as bearer clients; added auth regressions; documented B.AI/all-catalog/Cline setup in
  `docs/CONFIGURATION.md`. Live config now uses the Hermes B.AI key, `MODEL=bai/deepseek-v4-flash`,
  `MODEL_CATALOG_MODE=all`, and an empty curated allowlist. Cline CLI `3.0.60` now has an
  `anthropic` client entry pointed at `http://127.0.0.1:8082/v1` with the FCC token only; this is
  Cline -> FCC -> B.AI transport, not a merge of the Cline and B.AI providers. The
  credential-bearing `~/.fcc/.env` was tightened from world-readable to owner-only permissions.
- `validation`: focused FCC/API/catalog/provider tests passed (178); Ruff format/lint passed for
  the changed Python files; the full safe pytest tier passed 3,821 with 4 skipped and 173
  deselected. The one failure is the pre-existing documentation-catalogue mismatch for untracked
  `.project-memory/PROJECT_MEMORY.md`. Live FCC health returned `4.62.9`; `/v1/models` returned
  739 public entries including 88 B.AI compatibility entries and 36 explicit `:free` entries;
  a bounded B.AI request returned `FCC_BAI_SMOKE_OK`; a one-shot Cline request returned
  `FCC_CLINE_BAI_SMOKE_OK`.
- `evidence`: implementation, tests, installed provenance, and live FCC/B.AI/Cline behavior are
  proven separately; user visual confirmation is still pending.
- `residual_gap`: B.AI's live model list supplied no pricing metadata, so FCC correctly keeps
  those models `PRICE?`/unknown and does not label them free in `Free only`. The installed target
  is the Cline CLI; no VS Code Cline extension was installed. Catalog visibility does not bypass
  the existing strict provider-egress policy: an explicit-free OpenRouter Cline canary was
  rejected before network I/O while the active B.AI route remained allowed. The pre-existing
  docs-catalogue failure remains outside this change.
- `next_action`: use the existing `fcc-server` and `cline --provider anthropic --model
  bai/deepseek-v4-flash` configuration; if a VS Code extension or explicit B.AI free-price policy
  is wanted, authorize that as a separate follow-up.

## 2026-09-01 — native Models/Routing selection and provider-filter repair

- `scope`: repair the native Ratatui Models page from the supplied screenshots; remove fabricated
  window chrome and misplaced routing actions, make model selection explicit, keep active routes
  separate from the opt-in catalog, expose individual registered/usable provider lanes, and make
  free-price discovery evidence-based. B.AI and Cline remain separate provider/client lanes.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`,
  branch `main`; existing Hermes/Cline/API work and untracked `.project-memory/` were preserved.
- `status`: implemented in the working tree and release-built; no commit, push, PR mutation, merge,
  protected-branch change, or GitHub Actions action was performed in this turn.
- `changed`: `native_tui/src/app.rs` and `native_tui/src/ui.rs` now default Models to active rows,
  make `Catalog` opt-in, add `Providers`/price filters, show concise provider/status/price evidence,
  select an active model locally, and move Default/Fable/Opus/Sonnet/Haiku assignment actions to
  Routing. The fake traffic-light dots, raw capability JSON, and Models-page routing shortcuts are
  gone. Provider filtering hides unconfigured built-ins while retaining configured lanes and any
  provider with active rows. `docs/RUST_CONTROL_CENTER.md`, `docs/CONFIGURATION.md`, and this log
  document the contract.
- `validation`: pinned Rust 1.88 format, 19 native tests, Clippy with warnings denied, and release
  build passed. Focused Python/API/TUI tests passed 81; full pytest reached 3,854 passed and 152
  skipped with one pre-existing documentation-catalogue failure for untracked
  `.project-memory/PROJECT_MEMORY.md`. Live loopback payload returned 401 active/401 catalog rows,
  18 explicit free rows, and zero failed providers. Release PTY smoke verified Models, provider
  picker, B.AI-only filtering, Free only behavior, active model selection, Routing assignment, and
  clean exit; Admin config was restored to `bai/deepseek-v4-flash` afterward.
- `evidence`: implementation, automated tests, release artifact, and live loopback behavior are
  proven separately; no system installation or user visual confirmation is claimed. Live provider
  keys are reported only as masked/configured state. B.AI's live models have no explicit price
  evidence and correctly remain `PRICE?`, while OpenRouter's 18 explicit free rows are discoverable
  with `Free only`.
- `residual_gap`: live `BAI_PROXY` and `OPENROUTER_PROXY` fields are empty, so provider-specific
  proxy enablement is not claimed; no FCC custom Cline provider is registered in the inspected live
  state, because the installed Cline client is a separate harness lane. The unrelated documentation
  catalogue failure remains because `.project-memory/PROJECT_MEMORY.md` is user-owned untracked work.
- `next_action`: if proxy routing or a Cline upstream provider lane must be changed, provide/authorize
  that exact configuration separately; otherwise use Models to select and Routing to assign the
  desired active model.

## 2026-09-01 — hostile native TUI interaction audit

- `scope`: continue the local PR #210 audit against compact and wide terminal use, looking for
  controls that disappear, advertised shortcuts that do not work, modal click-through, unreadable
  provider/model identity, stale selection state, and repository entries that are not real GitHub
  checkouts.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout `/Users/tejas/Projects/AgentSwitchboard`,
  branch `main`; all pre-existing Hermes/Cline/API/UI/docs changes and untracked `.project-memory/`
  were preserved.
- `status`: implemented in the working tree and release-built; no commit, push, PR mutation, merge,
  protected-branch change, or GitHub Actions action was performed.
- `changed`: native `app.rs` now makes advertised `E` and `Y/N` controls case-insensitive,
  returns a removed provider filter to All providers; native `ui.rs` keeps compact footer controls
  visible, shows close guidance for message/help dialogs, and keeps text-entry cursors visible at
  the insertion point. `native_tui/src/main.rs` now attempts raw-mode, alternate-screen, mouse,
  and cursor cleanup independently so one restore failure does not skip the remaining cleanup.
  dialogs, and retains the prior modal mouse isolation, model/provider identity, responsive layout,
  usage summary, and stale-selection repairs. `docs/RUST_CONTROL_CENTER.md` records the compact
  geometry/modal contract.
- `validation`: Rust 1.88 format, check, 31 native tests, Clippy with warnings denied, and release
  build passed. A fresh release PTY at 80x24 showed the compact footer, `Show catalog`, exact model
  references/price evidence, the registered-provider modal, and `Enter / Esc closes`; uppercase
  `P`, `F`, `G`, and `Q` navigation completed cleanly. A live repository scan of
  `/Users/tejas/Projects` found 36 GitHub-backed checkouts and zero linked worktrees. The stale
  TUI process created by an earlier smoke session was identified by exact command and terminated.
- `evidence`: implementation, automated tests, release artifact, live loopback FCC behavior, PTY
  behavior, and repository inventory are proven separately; no installation or user visual
  confirmation is claimed. The live FCC server remained on loopback `127.0.0.1:8082`.
- `residual_gap`: the full safe pytest baseline remains 3,854 passed and 152 skipped with one
  unrelated documentation-catalogue failure caused by untracked `.project-memory/PROJECT_MEMORY.md`;
  this audit did not touch that user-owned file. B.AI pricing remains unknown/`PRICE?` when FCC does
  not provide explicit evidence, so `Free only` correctly excludes those rows. No merge has been
  authorized or performed.
- `next_action`: user visual confirmation of the final terminal layout is still the remaining
  acceptance state before any separately authorized commit/merge operation.

## 2026-09-01 — local latest release update and live Cline lane

- `scope`: finish the local PR #210 follow-up, update the editable FCC installation, and verify
  the repaired native TUI, provider/model inventory, proxy authentication, Cline hosted lane,
  and GitHub-backed repository finder. B.AI and Cline remain independent provider paths.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout
  `/Users/tejas/Projects/AgentSwitchboard`; branch `main`; local `HEAD` remains
  `edcf45e19f2bf3c60e100b1a699eebf35fb47f7a`, while `origin/main` is the merged PR #210 commit
  `1487f11cdb2b68aa53c156ac673693d5d1b9ed61`. The user-owned untracked `.project-memory/`
  directory was preserved.
- `status`: follow-up implementation is complete in the working tree and installed as editable
  `free-claude-code 4.63.0`; the loopback `fcc-server --headless` is running on port 8082. No
  commit, push, new PR mutation, protected-branch change, merge, or GitHub Actions action was
  performed in this update.
- `changed`: enabled custom provider families are now admitted explicitly by strict session
  egress policy; Cline `:free` recognition is scoped to the Cline lane; provider/API-key status
  and blank-secret/proxy preservation remain safe; the native TUI now has compact 80x18 layouts,
  visible page refresh/help/selection controls, exact B.AI/Cline provider filters, explicit
  frontend-local model selection, Routing-only assignment, cursor/terminal cleanup, and a
  release-binary-first `fcc-tui` launcher. Contract tests now tolerate registered custom lanes
  and ignore private untracked project-memory files when auditing the tracked docs catalogue.
- `validation`: `./scripts/ci.sh --fast` passed with 3,835 passed, 4 skipped, and 173 deselected;
  `uv lock --check`, Ruff format/lint, and `ty` passed. Pinned Rust 1.88 format, 52 native tests,
  Clippy with warnings denied, and the optimized release build passed. Live Admin status reported
  FCC `4.63.0`, active `bai/deepseek-v4-flash`, enabled Cline with a configured key and 18
  configured model IDs, 820 active models, 36 explicit-free rows, 418 Cline rows with 18 free,
  and a successful Cline provider test returning 418/18. Two live FCC-to-Cline requests for
  `z-ai/glm-5.3-flash:free` and `google/gemma-4-26b-a4b-it:free` returned HTTP 200 and exact
  sentinels. Authenticated `/v1/models` returned 1,565 Claude wrapper entries, including 70
  `:free` entries. Installed `fcc-tui` at 80x18 showed the separate provider picker, Cline
  free-only filter, and working Enter selection before clean exit. The repository scan found 36
  GitHub-backed folders and zero linked-worktree paths.
- `evidence`: implementation, automated tests, installed provenance, live loopback/API behavior,
  live upstream canaries, and PTY behavior are proven separately; user visual confirmation is
  not claimed. The current live route remained B.AI after the frontend-only model selection.
- `residual_gap`: B.AI's current model payload still lacks explicit price evidence, so its models
  remain `PRICE?`/unknown and are not mislabeled free. The 36 free rows are evidence-backed Cline
  and OpenRouter entries; this does not certify every model's generation semantics. The local
  follow-up remains dirty and unpublished even though PR #210 itself is already merged remotely.
- `next_action`: continue using the running local `fcc-server` and installed `fcc-tui`; stage and
  publish only the confirmed working-tree paths if a separate commit/push request is made.

## 2026-09-01 — NVIDIA Kimi K3 enablement and Textual default restoration

- `scope`: enable NVIDIA NIM Kimi K3 in the local provider/model inventory while preserving
  separate B.AI and Cline lanes; restore the Textual GUI as the default `fcc-server` surface and
  keep native Rust/Ratatui available only through optional `fcc-tui`.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout
  `/Users/tejas/Projects/AgentSwitchboard`; branch `main`; local `HEAD` remains
  `edcf45e19f2bf3c60e100b1a699eebf35fb47f7a`, while `origin/main` is the merged PR #210 commit
  `1487f11cdb2b68aa53c156ac673693d5d1b9ed61`. User-owned dirty work and untracked
  `.project-memory/` were preserved.
- `status`: implemented in the working tree, installed as editable `free-claude-code 4.63.0`,
  and live-tested on loopback port 8082. No commit, push, PR mutation, merge, protected-branch
  change, or GitHub Actions action was performed.
- `changed`: session policy now admits individually configured remote provider lanes for model
  discovery and requests, while disabled custom lanes, unconfigured built-ins, and forbidden
  provider families remain blocked. Live Cline configuration now includes `moonshotai/kimi-k3`
  in addition to its existing exact model IDs, and the persisted NVIDIA legacy allowlist now
  includes the raw `moonshotai/kimi-k3` ID alongside the existing entry. The default `fcc-server`
  launcher is documented and tested as the restored Textual control center; native Rust/Ratatui
  remains the optional `fcc-tui` surface. Decorative fake window-control dots and the misleading
  header placeholder were removed from the restored GUI. Configuration, troubleshooting, and
  documentation-catalogue references were updated to describe the split and the exact NVIDIA
  route.
- `validation`: session-policy and provider-policy tests passed (`16 passed`); the focused GUI,
  terminal, and model-editor run passed (`82 passed`); editable `uv tool` installation completed;
  a fresh `fcc-server --headless` reported healthy `4.63.0`; live Admin refresh returned zero
  failed providers and 1,000 catalog rows, including `nvidia_nim/moonshotai/kimi-k3`,
  `bai/glm-5.3-flash`, `bai/deepseek-v4-flash`, `cline/z-ai/glm-5.3-flash`, and
  `cline/moonshotai/kimi-k3`. Live status reported NVIDIA NIM, B.AI, and Cline as configured;
  Cline's key/proxy state stayed masked and unchanged. The installed interactive `fcc-server`
  showed 21 GitHub-backed repository folders with no linked-worktree rows. A live GUI harness
  narrowed `NVIDIA NIM` + `Free only` + `kimi k3` to the exact Kimi row, opened its inspector, and
  showed zero fake header controls.
- `evidence`: implementation, automated tests, editable installation, live loopback/API behavior,
  upstream model-list discovery, and PTY behavior are proven separately; user visual confirmation
  is not claimed. NVIDIA Kimi K3 is marked free by the current explicit zero-price catalog evidence;
  B.AI rows without price metadata remain unknown rather than being mislabeled.
- `residual_gap`: the working tree remains dirty and unpublished; PR #210 itself is already merged
  remotely, but this follow-up has not been merged. An upstream model-list refresh proves
  discovery/routability metadata, not a generation canary for every model. No secret or user
  visual-confirmation claim is made.
- `next_action`: use the restored `fcc-server` GUI and filter Models by B.AI, Cline, or NVIDIA NIM;
  stage/publish only confirmed paths if a separate commit or merge request is explicitly requested.

## 2026-09-01 — donor native UI replacement integrated locally

- `scope`: integrate the user-supplied `AgentSwitchboard-tui.zip` as the replacement
  control-center frontend while preserving the independently configured B.AI, Cline,
  NVIDIA NIM, provider-policy, and GitHub-backed repository work.
- `project`: `tverma101/AgentSwitchboard`; canonical checkout
  `/Users/tejas/Projects/AgentSwitchboard`; branch `main`; pre-existing dirty work was
  preserved in `/tmp/agentswitchboard-pre-donor-ui.patch`. The donor source was verified
  against remote branch `cursor/native-tui-gui-models-2455` at `fc06f547`; the zip's
  `tui-demo/fcc-control-center` is a Linux ELF binary and was not installed on macOS.
- `status`: donor Rust/Ratatui catalog source is integrated in the working tree; native
  `fcc-server`/`fcc-tui` launcher wiring is restored; package version is `4.64.0`. The
  old Textual modules remain present but are no longer selected by `fcc-server`.
- `changed`: replaced the native Rust source with the donor's live catalog browser and
  provider/model UI, including the separate `models.rs` browser state, provider/price/access
  filters, catalog visibility switch, exact model inspector, pending enable/default state,
  Admin validate/apply save/read-back, provider CRUD modals, local/status/usage/diagnostic
  pages, and the donor's compact/reference geometry. Updated launcher help and release/docs
  references from optional Textual-default behavior to the native replacement.
- `validation`: `cargo +1.88.0 fmt --check` passed; donor native test suite passed with
  24 tests; live API/provider/model validation remains the next gate after rebuilding the
  Mac release binary. No secret values were read or logged.
- `evidence`: donor source provenance, implementation, and native unit/UI tests are proven;
  the Linux demo executable is explicitly not Mac runtime evidence; installed/live behavior
  and user visual confirmation are not claimed until the rebuilt local binary is exercised.
- `residual_gap`: current dirty follow-up remains unpublished; no commit, push, merge, PR
  mutation, or GitHub Actions action was performed. A per-model generation canary remains
  separate from catalog discovery and route diagnostics.
- `next_action`: rebuild/install the editable local release, exercise `fcc-server` and
  `fcc-tui` against loopback, verify provider/model/API-key/repository interactions, then
  audit the final diff and report exact Git status.

## 2026-09-01 — donor replacement final local acceptance

- `scope`: finish the local acceptance pass for the supplied donor control-center replacement
  and the usability fixes requested for model selection, routing, provider identity, and
  repository discovery.
- `project`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`, `main`, local
  `HEAD` `edcf45e19f2bf3c60e100b1a699eebf35fb47f7a`; pre-existing dirty work remains preserved.
  No commit, push, merge, PR mutation, or GitHub Actions operation was performed.
- `changed`: removed fake window-control chrome; made the Models page active/routable-first
  with an explicit `Show catalog` switch, `Disable all`, provider chips including configured
  providers with no cached rows, separate Routing assignment controls, and truthful price
  evidence; retained independent B.AI, Cline, and NVIDIA NIM provider lanes.
- `validation`: native Rust tests `28 passed`, `cargo fmt --check`, Clippy with `-D warnings`,
  and optimized release build passed. Python gate passed with `3837 passed, 4 skipped,
  173 deselected`; Ruff format/check and `ty check` passed. Editable installation is
  `free-claude-code 4.64.0` from this checkout. Fresh 80x24 PTYs for both `fcc-tui` and
  installed `fcc-server` opened the native UI and exited cleanly. Loopback Admin health was
  healthy with zero failed providers; required B.AI/Cline/NVIDIA model refs were present and
  configured API-key fields remained masked. Repository discovery found 36 real checkout
  folders, zero linked-worktree rows, zero missing paths, and nonempty GitHub full-name
  remotes for each result.
- `evidence`: implementation, automated tests, editable installation, live API state, PTY
  behavior, and repository discovery are separate proven states; user visual confirmation and
  per-model generation success are not claimed. The current live catalog supplies unknown
  price evidence for B.AI rows rather than falsely labeling them free.
- `residual_gap`: the working tree is intentionally dirty and this follow-up is unpublished;
  PR #210 is already merged remotely, but these local follow-up changes are not. The donor zip
  Linux executable was not installed on macOS. A generation canary for every catalog row is
  outside this acceptance pass.
- `next_action`: run `fcc-server` or `fcc-tui` locally and use Models provider chips plus
  Routing; publish or merge only after an explicit separate authorization.

## 2026-09-01 — native repository handoff and finite model navigation

- `scope`: close the remaining donor-surface workflow gap: expose the repaired GitHub-backed
  repository inventory inside the native control center, launch Claude from the selected
  checkout, and stop model/list navigation from wrapping at the edges.
- `project`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; local `main` remains
  dirty and ahead of `origin/main` by three existing commits. User-owned untracked
  `.project-memory/` and unrelated dirty paths were preserved. No publication, merge, or
  Actions operation was performed.
- `changed`: added the loopback `/admin/api/repositories` and `/admin/api/repositories/select`
  boundary backed by dependency-neutral `core.repository_inventory`; added a visible native
  Repositories page with GitHub/checkout/branch/path inspector, refresh, selection persistence,
  and selected-checkout Claude launch; added compact repository hitbox coverage; changed model,
  provider, and field list movement to clamp at list edges rather than wrap endlessly.
- `validation`: native Rust suite passed `30 tests`, Clippy with `-D warnings`, formatting,
  and optimized release build passed. Full safe Python gate passed `3839 passed, 4 skipped,
  173 deselected`; full Ruff format/check and `ty check` passed; import-boundary, Admin-route,
  and repository-picker focused tests passed `122`. After restarting the server onto the
  editable `4.64.0` install, live health was healthy, repository Admin output returned real
  GitHub checkout folders, and installed `fcc-tui` plus installed `fcc-server` opened the
  Repositories page at 80x24; Enter persisted the selected checkout and both clients exited
  cleanly. Live model inventory had 1,000 catalog/visible rows, zero failed providers, and
  all required B.AI/Cline/NVIDIA refs present; configured secret fields remained masked.
- `evidence`: backend implementation, native UI tests, installed artifact, live Admin endpoint,
  live provider state, and PTY behavior are separately proven. The user has not yet supplied
  visual confirmation. The core inventory response was revalidated after the final server
  restart; linked worktrees and non-GitHub folders were absent from the 36-folder live scan.
- `residual_gap`: B.AI's live payload still has no explicit price evidence, so B.AI rows remain
  `PRICE?` and are correctly excluded from `Free only`; Cline's hosted custom lane is enabled
  with its API key, while its separate provider-specific proxy field is not configured. The
  donor zip's bundled Linux executable remains unused on macOS, and no generation canary was
  added for every catalog row. Local follow-up changes remain uncommitted/unpublished.
- `next_action`: use Repositories to choose a checkout, then `C`/`Launch Claude`; use Models
  and Routing for provider/model selection. Publish or merge only with explicit authorization.

## 2026-09-01 — native model surface final usability pass

- `scope`: close the remaining hostile-UI issues from the supplied screenshots: provider-first
  model browsing, explicit model/access selection, finite navigation, a usable Disable all
  action, separate Routing, and a clear Providers versus App Settings boundary.
- `project`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; local `main` remains
  intentionally dirty and unpublished. Existing commits, unrelated source changes, and
  untracked `.project-memory/` were preserved. No push, merge, PR mutation, or Actions operation
  was performed.
- `changed`: App Settings now excludes every `providers`-section credential, endpoint, proxy,
  and custom-registration field; provider configuration remains on Providers. Models now has a
  finite registered-provider picker, an explicit `Free only` filter, exact provider/model refs,
  plain-click selection, modifier-click access toggling, `Disable all`, and no Models-page
  Routing buttons. The persistent sidebar Active Model block, decorative global footer/help
  legend, raw capability dump, and visible `PRICE?`/redundant pricing badge were removed.
- `validation`: native Rust tests passed `33`; Rust format check, Clippy with `-D warnings`,
  and optimized release build passed. Editable installation was refreshed as
  `free-claude-code 4.64.0`. A fresh installed `fcc-tui` PTY at 80x24 opened the native
  surface, listed the six registered provider lanes individually, applied B.AI and `Free only`,
  showed the wrapped evidence-based empty state, and exited cleanly. Live loopback health was
  healthy on `4.64.0`; the sanitized provider inventory had six configured lanes, the model
  payload had `1000` visible/catalog rows, zero failed providers, and included the B.AI, Cline,
  and NVIDIA NIM required refs. No secret value was read or logged.
- `evidence`: implementation, automated tests, release artifact, editable installation, live
  Admin state, and PTY behavior are separately proven; user visual confirmation remains open.
  B.AI still supplies no explicit pricing evidence, so its rows are not falsely included by
  `Free only`; Cline's FCC loopback client path remains separate from the custom provider's
  provider-specific proxy field.
- `residual_gap`: the working tree remains dirty and these follow-up changes are not published;
  per-model generation success and user visual confirmation are outside this local catalog/UI
  acceptance pass.
- `next_action`: use the installed `fcc-server`/`fcc-tui`; publish or merge this local follow-up
  only after explicit authorization.

## 2026-09-01 — ChatGPT connected-account status repair

- `scope`: repair the reported configured ChatGPT failure and verify both provider visibility and
  an explicitly selected ChatGPT generation through the local FCC server.
- `project`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; local `main` remains
  intentionally dirty and three commits ahead of `origin/main`. Existing user changes and
  untracked files were preserved. No push, merge, PR mutation, or Actions operation was done.
- `changed`: `ApplicationRuntime` now overlays live connected-account state onto the safe provider
  inventory; `/admin/api/config` now returns that same runtime-owned provider status; added the
  Admin regression test and `docs/troubleshooting/chatgpt-provider-status.md`.
- `validation`: focused Admin tests passed; deterministic Python CI passed `3840 passed, 4 skipped,
  173 deselected`; Ruff check passed. After restarting the editable `4.64.0` server, live health
  was healthy, config/status/models all reported OpenAI/ChatGPT `connected`, six explicit
  `openai/...` models were present, and authenticated `openai/gpt-5.4` generation returned the
  exact `FCC_CHATGPT_SMOKE_OK` sentinel.
- `evidence`: implementation, automated tests, editable install, live Admin status, and live
  named-model generation are separately proven; credentials were used in memory only and were
  not printed or logged. The first unauthenticated smoke attempt correctly received FCC's local
  `Missing proxy authentication token` response and is not a provider failure.
- `residual_gap`: working tree remains dirty and unpublished; user visual confirmation and
  generation of every advertised ChatGPT model remain outside this targeted repair.
- `next_action`: use the refreshed local `fcc-server`/`fcc-tui` and select a specific `openai/...`
  model; publish or merge only after explicit authorization.

## 2026-09-01 — dangerous Claude launch and Claude registry parity

- `scope`: repair the missing visible dangerous-permissions launch action and synchronize the
  native TUI model surface with Claude's actual authenticated `/v1/models` catalogue.
- `project`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; local `main` remains
  intentionally dirty and unpublished. Existing changes and untracked files were preserved; no
  push, merge, PR mutation, or Actions operation was performed.
- `changed`: added visible `Danger launch` actions to Dashboard and Repositories with explicit
  `fccdanger --dangerously-skip-permissions` wording; `/admin/api/models` now returns the exact
  canonical Claude IDs/labels generated by the same builder as `/v1/models`; the native TUI
  keeps raw provider refs for routing, derives routability from that registry, shows parity count,
  and displays the exact Claude IDs for the selected route. Added native/API regression coverage,
  `docs/troubleshooting/claude-catalog-sync.md`, and updated the Rust control-center/config docs.
- `validation`: native Rust tests passed `34`; Rust format check, Clippy with `-D warnings`, and
  optimized release build passed. Focused Admin/model Python tests passed `83`; editable
  installation was refreshed. Fresh installed `fcc-tui` PTY output showed `Danger launch`,
  `Claude 1914 IDs`, and exact selected-row Claude IDs. Live FCC health was healthy on `4.64.0`;
  authenticated `/v1/models` and `/admin/api/models` matched in order and set with `1914` IDs,
  zero missing/extra IDs, and identical labels. No credentials were printed or written.
- `evidence`: implementation, automated tests, release artifact, editable install, live server,
  exact API parity, and PTY behavior are separately proven; user visual confirmation remains
  open. The TUI intentionally keeps one editable raw route row for Claude's two possible gateway
  IDs and counts static compatibility IDs without treating them as provider routes.
- `residual_gap`: working tree remains dirty and unpublished; this turn did not publish or merge
  any branch/PR, and per-model generation across every advertised row remains outside this
  targeted catalog/launch validation.
- `next_action`: use the refreshed local `fcc-server`/`fcc-tui`; select a provider route and
  confirm the visible `Danger launch` action only when intended. Publish or merge only after
  explicit authorization.

## 2026-09-01 — prelaunch server ownership and TUI persistence

- `scope`: repair the cold-start lifecycle so model/repository decisions are made and saved
  before the FCC server opens its listener; preserve attach-only `fcc-tui` behavior.
- `project`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; local `main` remains
  intentionally dirty and unpublished. Existing user changes and untracked files were
  preserved. No push, merge, PR mutation, or GitHub Actions operation was performed.
- `changed`: `fcc-server` now builds a serverless provider/model/repository snapshot, launches
  the native TUI in prelaunch mode, receives a private versioned result handoff, validates and
  reads back configuration/repository persistence, and only then creates `ServerSupervisor`.
  Native `Save`, `Ctrl-S`, `Start server`, and quit-with-pending-model-changes all write the
  handoff; the runtime composition root no longer imports back into the CLI facade.
- `validation`: full local Python suite passed `3,872 passed, 152 skipped`; native Rust passed
  `36`; Rust format check, Clippy with `-D warnings`, Ruff, and `git diff --check` passed. The
  optimized native release was rebuilt and `uv tool install --editable . --force` refreshed
  `free-claude-code 4.64.0` from this checkout. Real installed PTY smoke showed no listener
  before `Start server`, then a listener/live TUI after it, followed by clean shutdown. A real
  TUI model change persisted `bai/claude-haiku-4.5`, was verified through the Admin config,
  and was restored to `bai/deepseek-v4-flash` through a second TUI save; port 8082 was closed
  after prelaunch exits.
- `evidence`: implementation, automated tests, rebuilt artifact, editable installation, live
  prelaunch/server lifecycle, and actual persistence read-back are separately proven. User
  visual confirmation remains separate.
- `residual_gap`: the working tree remains dirty and unpublished; no GitHub/Actions integration
  was performed. Provider generation success for every advertised model remains outside this
  lifecycle repair.
- `next_action`: use the refreshed local `fcc-server` to choose models/repositories and press
  `Start server`; use `fcc-tui` only to attach to a server that is already running.

## 2026-09-01 — active-model terminology and compact TUI repair

- `scope`: remove the misleading default-model mental model and remaining compact-screen glitches
  from the native Models page while preserving the serverless prelaunch/save architecture.
- `project`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; local `main` remains
  intentionally dirty and unpublished. Existing changes and untracked files were preserved; no
  push, merge, PR mutation, protected-branch change, or GitHub Actions operation was performed.
- `changed`: `native_tui/src/models.rs` now models the configured `MODEL` value as the active route;
  `native_tui/src/app.rs` uses `Enter`/`Use selected` to stage the exact highlighted provider/model;
  `native_tui/src/ui.rs` removes default labels, raw capability/Claude-ID dumps, and compact action
  overflow, while keeping provider/free filters, separate access toggles, `Disable all`, and
  prelaunch `Start server` visible. The Admin manifest and current control-center/config docs now
  use active-model terminology.
- `validation`: native Rust `37 passed`; format check, Clippy with `-D warnings`, and optimized
  release build passed. Full local Python suite passed `3,872 passed, 152 skipped`. Editable FCC
  `4.64.0` was refreshed from this checkout. Installed 80x24 PTY showed the complete compact model
  action set without default/capability metadata; paced prelaunch selection saved exact
  `bai/claude-haiku-4.5`, then a second TUI search/save restored `bai/deepseek-v4-flash`. No FCC
  process or port-8082 listener remained afterward.
- `evidence`: implementation, automated tests, release artifact, editable installation, and
  installed interactive persistence are separately proven; user visual confirmation remains open.
- `residual_gap`: the working tree is dirty and unpublished. This turn did not modify GitHub,
  Actions, PR #210 state, or any remote branch.
- `next_action`: use the refreshed local `fcc-server`; on Models, click a provider or exact row,
  use `Use selected`, then `Save`/`Start server` as appropriate. Use `fcc-tui` only to attach to a
  server that is already running.

## 2026-09-01 — Kimi K3 proxy boundary and direct Claude handoff

- `scope`: continue from the saved local checkpoint on topic branch
  `fix/proxy-launch-seamless`; add regression coverage, validate every provider proxy binding,
  repair NVIDIA Kimi K3 requests, and make cold `fcc-claude`/`fccdanger` launch after the exact
  repository selection.
- `project`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`; branch was created from
  checkpoint `edcf45e19f2bf3c60e100b1a699eebf35fb47f7a`. The checkout remains intentionally dirty
  with prior user work plus this turn's changes; no push, merge, PR mutation, or GitHub Actions
  operation was performed.
- `changed`: NIM applies immutable `top_p=0.95` for `moonshotai/kimi-k3`; DeepSeek and local
  Ollama now have catalog-owned proxy settings in `Settings` and `.env.example`; all provider
  descriptors are covered by proxy-to-config/transport tests. Direct launch intent (normal or
  danger), the selected repository path, and the final server-start handoff now cross the
  serverless prelaunch TUI boundary; the owner starts FCC only after the result is validated and
  then launches Claude in the selected checkout. Added Python/Rust regression tests and updated
  configuration/troubleshooting records.
- `validation`: full local Python suite passed `3,973 passed, 152 skipped`; focused launch/proxy
  tests passed `198`; native Rust suite passed `38`; Ruff, Rust format, Clippy with `-D warnings`,
  and optimized native release build passed. A real local server accepted an authenticated
  streamed `POST /v1/messages` for `nvidia_nim/moonshotai/kimi-k3` with HTTP `200`; its temporary
  listener shut down cleanly. Installed editable `free-claude-code 4.64.0` was refreshed. Fresh
  installed normal and danger direct commands opened the prelaunch TUI; a controlled normal
  launch selected the current GitHub checkout, started FCC only afterward, invoked the fake
  certified Claude binary in `/Users/tejas/Projects/AgentSwitchboard`, and then exited cleanly.
- `evidence`: implementation, automated tests, native release artifact, editable installation,
  live NVIDIA proxy behavior, and installed direct-launch sequencing are separately verified.
  The optional Computer Use helper remains fail-closed when configured but its signed Codex
  installation is absent; that existing safety behavior was not weakened. No credential values
  were printed or written by validation.
- `residual_gap`: user visual confirmation in the macOS terminal remains separate. The working
  tree is unpublished and intentionally dirty; GitHub/Actions integration and merge remain outside
  this request.
- `next_action`: review the branch diff and use `fcc-claude` or `fccdanger`; on a cold start choose
  the exact model, select the repository, and use the mode-specific launch action. Resolve the
  separately reported Computer Use installation only if that optional helper is intended.

## 2026-09-02 — sandbox server identity and native TUI liveness

- `scope`: canonical checkout `/Users/tejas/Projects/AgentSwitchboard`, branch
  `fix/proxy-launch-seamless`; harden sandbox/standard server detection and make native TUI
  lifecycle state and process diagnostics visible. The checkout was already intentionally dirty
  across application, documentation, packaging, and test paths; those pre-existing changes were
  preserved and no reset, clean, push, merge, PR mutation, or GitHub Actions operation was run.
- `changed`: added credential-free service/protocol/mode/instance/PID/uptime identity metadata to
  health and Admin status; added mode-aware probes that reject foreign listeners and sandbox/
  standard mismatches; retained bounded supervisor startup failures; added periodic native TUI
  health refreshes with retained snapshots and explicit running/degraded/offline/unknown states;
  added focused Python/Rust tests and synchronized the README release marker.
- `validation`: local CI passed with suppression scan, Ruff format/lint, Ty, and `3,982 passed,
  4 skipped, 173 deselected`; native Rust format, Clippy with `-D warnings`, and `42` tests passed;
  focused server tests passed `128`; isolated subprocess smoke checks passed standard cold start,
  health/Admin identity, already-running attach, foreign-port rejection, sandbox identity/state
  isolation, and clean shutdown/offline probing. `git diff --check` passed.
- `evidence`: current source, executable tests, and loopback subprocess behavior are verified.
  The smoke test used a temporary config directory and ephemeral ports; no credentials were
  printed or written. Project memory record `W-0007` was created after searching existing records.
- `residual_gap`: interactive visual confirmation in a real user terminal and installed-command
  behavior outside the editable checkout remain separate evidence; no external CI or hosted action
  was invoked.
- `next_action`: review the combined dirty diff before committing or publishing; keep the existing
  pre-existing paths separate from any eventual focused commit.
