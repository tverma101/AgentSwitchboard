# Claude catalogue and native TUI parity

## Symptom

The native control center showed raw provider/model routes while Claude Code's
authenticated model picker showed gateway IDs and a different count. The
Repositories page also retained only the hidden `!` shortcut for the dangerous
Claude launch, so there was no visible mouse action.

## Root cause

`/admin/api/models` was assembled from raw provider cache entries, while
`/v1/models` used `build_models_list_response()` to add Claude gateway variants,
aliases, and compatibility entries. The TUI consumed only the raw admin fields,
so it had no authoritative client-facing registry to compare against. The
dangerous launcher itself still worked; only its visible action had regressed.

## Recovery

The admin model payload now calls the same canonical model-list builder as
`/v1/models` and returns its ordered IDs and display labels as
`claude_models`/`claude_model_labels`. The native client keeps raw provider refs
for configuration, derives routability from the exact Claude IDs, and shows the
client IDs in the selected-row inspector and registry count in the toolbar.
`Danger launch` is now a visible action on Dashboard and Repositories, and its
inspector text identifies the `fccdanger` command and exact skip-permissions
flag.

## Validation

- Native Rust tests passed: 34.
- Native formatting, Clippy with `-D warnings`, and optimized release build passed.
- Focused Python Admin/model tests passed: 83.
- Live FCC health was healthy on version `4.64.0`.
- Live authenticated `/v1/models` and `/admin/api/models` matched exactly:
  1,914 IDs, zero missing/extra IDs, and identical labels.
- A fresh installed `fcc-tui` PTY showed `Danger launch`, the live
  `Claude 1914 IDs` count, and exact Claude IDs for the selected route.
- No credential values were printed or written by the validation.

## Residual gap

The TUI intentionally displays one raw provider route per row rather than two
duplicate rows for Claude's normal and no-thinking gateway IDs. Static Claude
compatibility IDs are included in the registry count but do not become editable
provider rows because they resolve through the configured route. User visual
confirmation in the real macOS terminal remains separate from this PTY evidence.

## 2026-09-01 — prelaunch save/start boundary

### Symptom

The control center displayed model choices, but changes made before server
startup did nothing because `fcc-server` had already created the server
runtime before opening the TUI. A TUI exit also had no durable parent-owned
save contract.

### Root cause

`run_owned_control_center` started `ServerSupervisor`, waited for `/health`,
and only then launched the native client. The child process therefore had no
safe way to hand staged model/provider/repository choices back to the owner
before runtime composition.

### Recovery

`fcc-server` now performs a serverless prelaunch phase. It builds a sanitized
state snapshot using short-lived in-process discovery, writes it to the native
TUI, and waits for a versioned owner-only result file. The TUI saves model
changes on `Save`, `Ctrl-S`, `Start server`, and `Q` with pending changes.
Python validates allowed fields, atomically commits them through the Admin
persistence boundary, reads them back, persists the selected repository, and
only then constructs `ServerSupervisor`. `fcc-tui` remains attach-only.

### Validation

- Full local Python suite: `3,872 passed, 152 skipped`.
- Native Rust suite: `36 passed`; formatting and Clippy with `-D warnings`
  passed.
- Installed editable launcher: `free-claude-code 4.64.0` from the canonical
  checkout; optimized native release binary rebuilt from the same checkout.
- Real cold-start PTY: prelaunch rendered with `1,000` route rows and `1,914`
  Claude IDs while `lsof` showed no listener on port `8082`; after the TUI
  `Start server` action the listener appeared, live TUI attached, and `q`
  stopped the supervisor cleanly.
- Real persistence PTY: selected `bai/claude-haiku-4.5`, quit before startup,
  observed the persisted `MODEL` and Admin field change, then restored
  `bai/deepseek-v4-flash` through a second TUI save. Port `8082` was closed
  after each prelaunch exit.

### Residual gap

The change is implemented, fully locally tested, rebuilt, installed, and
verified through PTY/live loopback evidence. User visual confirmation in the
real macOS terminal and publication/merge of the intentionally dirty local
checkout remain separate states; no GitHub Actions, push, merge, or PR state
was changed.

## 2026-09-01 — active-model selection and compact action-bar repair

### Symptom

The model screen still called the configured route the “default model,” making a
highlighted row look like an inspection-only choice. At 80x24, the model toolbar
and two-cell action buttons also pushed the final prelaunch action below the
owned page area, so `Start server` was not clickable. The inspector exposed
large Claude-ID/capability metadata blocks that obscured the exact route.

### Root cause

The frontend state used `pending_default` for the same `MODEL` value that the
user treats as the active route, and the model page reserved five toolbar rows
plus a five-row action bar inside a nineteen-row compact workspace. Dense action
bars wrapped by two rows at a time and silently dropped actions once their
cursor passed the area boundary.

### Recovery

The browser state now uses active-model terminology throughout. `Enter` or
`Use selected` stages the exact highlighted `provider/model`; `Save`, `S`, or
`Ctrl-S` persists it, while `Enable/Disable selected`, modifier-click, and
`Disable all` remain independent access operations. The model toolbar shows
`ACTIVE` and `SELECTED` separately, the list marks the active row with `→`, and
the inspector is limited to the exact route, provider, status, availability,
and paid/free signal. The model page uses a four-row toolbar, and action bars
with seven or more controls use one-cell buttons so compact prelaunch retains
`Start server`.

### Validation

- Native Rust suite: `37 passed`; format check and Clippy with `-D warnings`
  passed; optimized release build passed.
- Full local Python suite: `3,872 passed, 152 skipped`.
- Editable install refreshed from `/Users/tejas/Projects/AgentSwitchboard` as
  `free-claude-code 4.64.0`.
- Fresh installed 80x24 PTY showed `ACTIVE`, `SELECTED`, `Use selected`,
  `Disable all`, `Show catalog`, and `Start server`; the old `DEFAULT` and raw
  `Capabilities` blocks were absent.
- Paced installed PTY selected `bai/claude-haiku-4.5`, saved it, and verified
  the owner persisted that exact `MODEL` before quit. A second paced run
  searched/select-saved `bai/deepseek-v4-flash` and restored the prior state.
  No listener or FCC process remained after either run.

### Residual gap

The repair is implemented, tested, rebuilt, installed, and live-PTY verified;
visual confirmation in the user's macOS terminal remains separate. The working
tree is intentionally dirty and unpublished; no push, merge, PR mutation, or
GitHub Actions operation was performed.

## 2026-09-01 — provider proxy matrix and direct Claude handoff

### Symptom

NVIDIA's live Kimi K3 route reached the upstream NIM endpoint but returned HTTP
400. A cold direct `fcc-claude`/`fccdanger` launch also carried no reliable
repository or normal/danger intent through the prelaunch TUI, so the saved
selection could be ignored when the client started.

### Root cause

NIM's shared request defaults sent `top_p=1` even though the Kimi K3 deployment
rejects every value except `0.95`. Separately, the prelaunch owner discarded
the TUI's selected repository and always invoked the child callback as a normal
Claude launch. DeepSeek and local Ollama also lacked descriptor-to-settings
proxy bindings, so they were not part of the complete provider proxy matrix.

### Recovery

The NIM request builder now enforces Kimi K3's immutable sampling contract at
the provider boundary while preserving the existing defaults for other NIM
models. DeepSeek and Ollama have catalog-owned proxy fields in `Settings`, the
provider manifest, and `.env.example`. Direct launch intent is included in the
serverless bootstrap snapshot; the TUI's repository action persists the exact
checkout, starts the backend only after the result is read back, and the owner
passes the selected path plus the original normal/danger mode to Claude.

### Validation

- Full local Python suite: `3,973 passed, 152 skipped`.
- Native Rust suite: `38 passed`; format check, Clippy with `-D warnings`, and
  optimized release build passed.
- All built-in provider descriptors mapped a configured proxy into both the
  shared `ProviderConfig` and a constructed transport in the regression matrix.
- A live local FCC server returned HTTP `200` with `text/event-stream` for
  `nvidia_nim/moonshotai/kimi-k3` after the fix; the temporary server then
  shut down cleanly and no test listener remained.
- Direct normal and dangerous owner paths have regression coverage proving the
  selected repository and mode reach the Claude callback. No credentials were
  printed or written by validation.

### Residual gap

The implementation, automated tests, native release artifact, editable source
checkout, and live NVIDIA route are verified locally. User visual confirmation
in the macOS terminal and any GitHub publication/merge remain separate; no
push, merge, PR mutation, or Actions operation was performed.

## 2026-09-02 — native ultracode naming boundary

### Symptom

Claude Code could show three entries for a reasoning-capable route, including a
row labeled `(ultracode)`. That label suggested that selecting the row enabled
Claude Code's native ultracode mode.

### Root cause

The row is an FCC gateway variant. It asks FCC to use maximum provider-side
reasoning (`xhigh`); it cannot enable Claude Code's client-side ultracode mode,
which includes dynamic workflow behavior and separate client/organization gates.
The legacy `claude-3-freecc-ultra/...` model ID is retained for compatibility,
but its display label must describe the actual gateway behavior.

### Recovery

The user-facing label is now `(maximum reasoning)`. The launcher separately
defaults gateway sessions to `CLAUDE_CODE_EFFORT_LEVEL=xhigh` while preserving
explicit effort flags and environment settings. Native ultracode remains a
Claude Code client feature and cannot be created by FCC's Anthropic-compatible
model API.

### Validation

- The model-registry regression test verifies that the legacy gateway ID is
  labeled `maximum reasoning`, not `ultracode`.
- Launcher tests verify the default `xhigh` environment value and preservation
  of explicit effort choices.
- The sandbox and standard FCC servers remain separated by ports `8083` and
  `8082` respectively.

### Residual gap

Users who need native ultracode must use a Claude Code session and account that
meet Claude Code's own capability and entitlement requirements. FCC can provide
maximum remote reasoning, but it cannot make that client-only mode appear in
Claude Code's thinking picker.
