# AgentSwitchboard native Rust control center (`fcc-server` / `fcc-tui`)

The default interactive `fcc-server` surface is the native Rust/Ratatui control
center. The standalone `fcc-tui` command attaches the same frontend to an
already-running server; the Python/FastAPI server remains the
canonical runtime, provider, routing, persistence, session, and authentication
owner.

The Repositories page is the native project handoff: it loads the server-owned
GitHub-backed checkout inventory, omits linked worktrees and non-GitHub folders,
and persists the selected checkout through the local repository picker
boundary. `C` or `Launch Claude` starts the selected client with that checkout
as its working directory. `Danger launch` starts `fccdanger`, which passes
`--dangerously-skip-permissions` to Claude explicitly. `fcc-repos` remains
available as the standalone shell picker.

## Architecture donor

The primary architecture and interaction donor is **GitUI** (`gitui-org/gitui`) at commit `2fa693cb6ed431b21ebc300dd02e83c2476699ce`, reviewed as an MIT-licensed Rust/Ratatui application. The useful donor patterns are code-driven component composition, a central event pump, reusable panels, popup/modal ownership, contextual actions, dense list/detail workflows, and a responsive terminal layout.

AgentSwitchboard does not vendor GitUI's git engine or source modules. It adapts the application architecture and terminal-GUI interaction ideas to FCC's domain. `jaylfc/tuiui` remains a secondary visual/mouse reference for terminal-desktop chrome; it is not the runtime base.

## Process boundary

```text
fcc-server (Python lifecycle + native frontend)
    |
    | owns server lifecycle
    v
FastAPI + canonical FCC runtime
    +-- loopback-only /admin/api/* --> native control center

fcc-tui (standalone Rust attach)
    |
    | loopback-only /admin/api/*
    v
fcc-control-center (Ratatui)
    |
    +-- Ratatui/Crossterm rendering
    +-- mouse + keyboard events
    +-- local forms and modals
    +-- launches fcc-claude / fccdanger while the server remains alive
```

The live and sandbox servers bind to loopback by default, and the Rust client accepts only a loopback Admin base URL. Changing `HOST` to a non-loopback address is an explicit deployment choice for the API surface; it does not make the Rust Admin client remote-capable. The Rust client does not import provider SDKs, construct provider routes itself, or write FCC configuration files directly. All mutations go through the existing Admin validation/apply endpoints.

### Cold-start lifecycle

An interactive `fcc-server` launch has two explicit phases. First, the Python
owner builds a serverless prelaunch snapshot: provider/model discovery and
repository inventory run in-process, but no Uvicorn worker or HTTP listener is
created. The native TUI edits that snapshot and atomically writes a private
owner-only result file. `Save`, `Ctrl-S`, `Start server`, and `Q` with pending
model changes all write the result; the parent validates and reads it back.
Only a result that passes validation and persistence read-back is followed by
`ServerSupervisor` creation and the live Admin-backed TUI. `fcc-tui` remains
attach-only and never owns this startup boundary.

## API keys and credentials

The Admin API remains the secret owner. Configured secret fields are returned as masked state, not plaintext. The Rust UI therefore renders only `configured`/`not configured` state for existing keys. Opening a configured secret starts with an empty editor:

- blank + save preserves the existing key;
- entering a new value replaces it through Admin validation;
- explicit clear requires a confirmation and sends an empty value;
- the Rust frontend never needs the old plaintext key.

Custom providers follow the same rule more strongly: their public status exposes `api_key_configured` and `proxy_configured` booleans, and editing an existing custom provider omits `api_key` when the replacement field is blank so FCC preserves the previous secret.

The sidebar's `App Settings` page is intentionally not a second provider form:
it excludes every field in the Admin manifest's `providers` section, including
provider API keys, base URLs, proxies, and custom-provider registration. Runtime
and application controls remain there; provider registration and credential
editing are available only from `Providers`.

## Provider and local setup

The Providers page consumes the server's provider inventory dynamically. Built-in provider configuration uses the field keys advertised by the canonical Admin manifest. The UI supports provider tests, connected-account login/disconnect, custom-provider CRUD, API keys, base URLs, proxies, and explicit model lists without maintaining a second provider registry.

The Local Setup page exposes the existing FCC controls for LM Studio, llama.cpp, and Ollama. Reachability checks use `/admin/api/providers/local-status`; the Rust process never probes arbitrary network hosts itself.

## Model routing

The Models page uses FCC's cached/discovered model inventory and price evidence. It
starts with active/routable rows only; `Show catalog` explicitly opts into the full
cached inventory, including blocked discoveries, so a large public catalog cannot
obscure models that can be used immediately. `P` or the provider chip opens a
finite picker containing only registered providers, including a configured
provider with no cached rows, whose empty state points to `Refresh`. Missing-key
providers are excluded even if stale catalog rows remain cached.

`Free only` is a display filter. It accepts only explicit `is_free`/zero-price
evidence or the narrow OpenRouter `:free` reference convention. Missing price
evidence is not shown as FREE. Provider identity comes from the exact prefix in
`provider/model`; B.AI and Cline therefore remain distinct lanes when both are
registered.

The provider picker reports each registered lane individually. A configured custom
lane with no discovered models remains selectable and points to `Refresh`; it is
not silently merged into another provider. This is how an enabled Cline hosted
lane and the FCC B.AI lane remain separately discoverable.

The Admin model response also carries `claude_models` and
`claude_model_labels`, generated by the same builder as the authenticated
`/v1/models` endpoint. The TUI keeps one editable row per raw
`provider/model` route so enabling and routing remain unambiguous, but marks a
row routable only when its exact Claude-facing gateway ID is in that registry.
The registry remains backend evidence; the picker does not dump duplicate Claude
IDs or raw capability metadata into the model-selection view.

Plain click selects the exact row shown in the inspector. `Enter` or `Use
selected` stages that exact row as the active `MODEL` route and enables it; it does
not write until `Save`, `S`, or `Ctrl-S`. `E` or `Space` toggles access, and
Shift/Ctrl/Option/Command-click toggles the clicked row while keeping the exact
selection visible. `A` clears the curated catalog, and `Disable all` does the same
from the action bar. The active route cannot be disabled through the single-row
toggle until another row is used, so access changes never silently redirect a
request. Tier assignments are intentionally kept on the separate Routing page:
choose the target on Models, then use the route action there. All assignments go
through the existing Admin validation/apply endpoints:

- `MODEL`
- `MODEL_FABLE`
- `MODEL_OPUS`
- `MODEL_SONNET`
- `MODEL_HAIKU`

The Routing page also exposes the server-owned controls for parent-model inheritance, model catalog mode/allowlist, stable model aliases, capability routing, allowed helpers, paid fallback, and root/per-tier reasoning. Direct `provider/model` references remain the canonical routing IDs.

## Claude Code context policy

Context remains a visible status page so operators can see that the FCC-owned
intervention is disabled in standard mode. Standard FCC does not set or remove
Claude's context, compaction, MCP-output, or tool-search environment values.
The sandbox intentionally sets Claude's bounded 256K context/auto-compact pair;
MCP-output and tool-search policy remain client-owned. The legacy
`FCC_CLAUDE_CONTEXT_TOKENS` field remains readable for old configuration files
and supplies the sandbox value.

## GUI-like geometry contract

The terminal still renders in character cells, so the deterministic acceptance language is **cell-exact geometry** rather than claiming the terminal emulator's font rasterization is under application control. Ratatui `TestBackend` regressions pin a reference `160 x 50` viewport to:

- top application bar: 3 rows;
- persistent navigation rail: 28 columns;
- bottom status/shortcut bar: 2 rows;
- main workspace: 132 columns;
- the same persistent shell on the Context page and other workspaces.

At terminals below 100 columns the shell contracts to a 22-column navigation
rail, keeps navigation rows to one line, and wraps action buttons onto visible
rows. The minimum supported compact layout keeps the Models page's search,
registered-provider picker, `Free only`, `Show catalog`, `Disable all`, Save,
Undo, selection, and Refresh hitboxes inside the main viewport. Providers also
has a page-level Refresh action. Text editors request a visible cursor at the
insertion point. Open modals consume background mouse input; the registered-
provider picker supports wheel, click, and finite keyboard selection. Message and
confirmation dialogs close with `Enter` or `Esc`; there is no global decorative
help legend competing with the workspace.

The final macOS acceptance gate is an installed-terminal screenshot/interaction pass. Code-level geometry tests cannot prove font- or emulator-level pixel identity.

## Development and installation boundary

The native launcher resolves the frontend in this order:

1. `FCC_CONTROL_TUI_BINARY` when an explicit local build is supplied;
2. `fcc-control-center` on `PATH`;
3. the existing source checkout's `target/release/fcc-control-center`;
4. source-backed `cargo run --release` using the packaged Cargo manifest.

After changing the native source, rebuild that release binary so `fcc-tui` uses
it immediately. Both `fcc-server` and `fcc-tui` use the same native frontend;
`fcc-server` owns the Python server lifecycle while `fcc-tui` attaches to an
already-running instance. `uv tool install
--editable . --force` refreshes the installed Python launcher and server
metadata; it does not compile the Rust executable.

The standalone `fcc-tui` command attaches the native frontend to the configured
loopback server. The interactive `fcc-server` path owns the server and uses the
same frontend; `fcc-claude` remains the client launcher.

`fcc-server --headless` remains the explicit server-only escape hatch. The Rust source is intentionally kept inside the Python package tree so an editable AgentSwitchboard checkout can run the frontend directly against the same local server without copying configuration or provider code.

Hosted CI installs Rust `1.88.0` and runs `rustfmt`, Clippy with warnings denied, and the Rust test suite on the exact PR head. The ordinary Python Ruff/ty/pytest gates remain unchanged.
