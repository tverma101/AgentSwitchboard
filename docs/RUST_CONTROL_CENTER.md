# Native Rust control center

AgentSwitchboard's interactive `fcc-server` control surface now uses a separate Rust/Ratatui frontend instead of the deep Textual inheritance stack. The Python/FastAPI server remains the canonical runtime, provider, routing, persistence, session, and authentication owner.

## Architecture donor

The primary architecture and interaction donor is **GitUI** (`gitui-org/gitui`) at commit `2fa693cb6ed431b21ebc300dd02e83c2476699ce`, reviewed as an MIT-licensed Rust/Ratatui application. The useful donor patterns are code-driven component composition, a central event pump, reusable panels, popup/modal ownership, contextual actions, dense list/detail workflows, and a responsive terminal layout.

AgentSwitchboard does not vendor GitUI's git engine or source modules. It adapts the application architecture and terminal-GUI interaction ideas to FCC's domain. `jaylfc/tuiui` remains a secondary visual/mouse reference for terminal-desktop chrome; it is not the runtime base.

## Process boundary

```text
fcc-server (Python)
    |
    | owns server lifecycle
    v
FastAPI + canonical FCC runtime
    |
    | loopback-only /admin/api/*
    v
fcc-control-center (Rust)
    |
    +-- Ratatui/Crossterm rendering
    +-- mouse + keyboard events
    +-- local forms and modals
    +-- launches fcc-claude / fccdanger while the server remains alive
```

The Rust client accepts only a loopback Admin base URL. It does not import provider SDKs, construct provider routes itself, or write FCC configuration files directly. All mutations go through the existing Admin validation/apply endpoints.

## API keys and credentials

The Admin API remains the secret owner. Configured secret fields are returned as masked state, not plaintext. The Rust UI therefore renders only `configured`/`not configured` state for existing keys. Opening a configured secret starts with an empty editor:

- blank + save preserves the existing key;
- entering a new value replaces it through Admin validation;
- explicit clear requires a confirmation and sends an empty value;
- the Rust frontend never needs the old plaintext key.

Custom providers follow the same rule more strongly: their public status exposes `api_key_configured` and `proxy_configured` booleans, and editing an existing custom provider omits `api_key` when the replacement field is blank so FCC preserves the previous secret.

## Provider and local setup

The Providers page consumes the server's provider inventory dynamically. Built-in provider configuration uses the field keys advertised by the canonical Admin manifest. The UI supports provider tests, connected-account login/disconnect, custom-provider CRUD, API keys, base URLs, proxies, and explicit model lists without maintaining a second provider registry.

The Local Setup page exposes the existing FCC controls for LM Studio, llama.cpp, and Ollama. Reachability checks use `/admin/api/providers/local-status`; the Rust process never probes arbitrary network hosts itself.

## Model routing

The Models page opens on active/routable models and keeps FCC's complete
cached/discovered inventory behind an explicit Catalog view. Provider filters
come from registered providers, and the price filter is either All or Free
only; there is no hidden free-first ordering and unknown pricing is never
invented. Enabled custom-provider model IDs are included in Catalog even when
discovery has not populated the server cache. The page exposes `Show catalog`
and `Active only` as explicit actions, so the complete cached inventory is
never hidden behind an undiscoverable key. Space or Shift/Ctrl-click marks one
or more exact model references for a bulk change; `Toggle selected` inverts
the actual ON/OFF state of those rows, including mixed selections, and
`Disable all` clears the active allowlist. Every change is sent as one Admin
transaction in the background; the page stays navigable while it saves and
then refreshes the full snapshot before reporting success. Enter or Set MODEL
assigns the exact highlighted model to `MODEL`:

- `MODEL`

The Routing page owns the remaining server-side routing controls and tier
overrides. Direct `provider/model` references remain the canonical routing IDs.

## Dashboard

The Dashboard is an operational summary, not a second settings page. It shows
the loopback server status, the exact `MODEL` launch route, the currently
reported active route, active/catalog/free model counts, registered-provider
health, catalog policy, workspace/git state, pending fields, and the latest
feedback. `Claude normal` and `Claude danger` launch actions remain visible at
the bottom of the page. At narrow terminal widths the same values collapse
into one dense card so labels and routes remain readable.

## Claude Code context window

Context is a first-class page, not hidden in generic settings. It edits the canonical `FCC_CLAUDE_CONTEXT_TOKENS` field through the Admin API.

The UI enforces and displays the same FCC contract:

- default: `256000` tokens;
- accepted range: `32000` through `1000000`;
- a new FCC-launched Claude process receives the selected value as both `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and `CLAUDE_CODE_AUTO_COMPACT_WINDOW`;
- changing the setting does not resize an already-running Claude process;
- a known model-native ceiling smaller than the configured FCC cap still wins;
- an upstream model advertising a larger window does not silently raise the FCC session budget.

The server remains the final validator, so the frontend's range check is a usability guard rather than a competing policy implementation.

## Direct control-center geometry

The terminal still renders in character cells, so the deterministic acceptance language is **cell-exact geometry** rather than claiming the terminal emulator's font rasterization is under application control. Ratatui `TestBackend` regressions pin a reference `160 x 50` viewport to:

- top application bar: 3 rows;
- direct AgentSwitchboard page navigation: 30 columns when open;
- page surface: 130 columns with navigation open, or the full 160 columns when it is hidden;
- editor-tab and activity-gutter rectangles: zero-sized and never rendered;
- status bar: 1 row;
- transient status footer: 1 row without a permanent keyboard legend;
- the same direct shell on every page, with an optional 7-row FCC status/provider-alert panel.

The final macOS acceptance gate is an installed-terminal screenshot/interaction pass. Code-level geometry tests cannot prove font- or emulator-level pixel identity.

## Development and installation boundary

The Python launcher resolves the frontend in this order:

1. `FCC_CONTROL_TUI_BINARY` when an explicit local build is supplied;
2. `fcc-control-center` on `PATH`;
3. source-backed `cargo run --release` using the packaged Cargo manifest.

The standalone `fcc-tui` command attaches the native frontend to the configured
loopback server. The interactive `fcc-server` and `fcc-claude` paths use the
same launcher when they own or attach to the server.

## Command palette

`Ctrl+K` (or `Ctrl+P`) opens a command palette over the current page. Typing
filters every page plus the page-contextual actions (provider configure/test,
custom-provider CRUD, model search, bulk model policy, and exact `MODEL`
assignment, field edit, and route diagnostic), plus page-navigation/status-panel
controls and Claude launch actions;
`↑↓` (or `Ctrl+P`/`Ctrl+N`) moves, `Enter` runs, and `Esc` closes. The palette
is a small keyboard index for FCC, not an editor command registry; every entry
maps to an existing Admin-backed action and the cell-exact geometry contract
below is unchanged while it is open. `fcc-tui --list-commands` prints the same
FCC inventory for shell workflows.

## Direct FCC shell

The visible shell is only AgentSwitchboard: a top application bar, one direct
page-navigation sidebar, the selected FCC page, an optional FCC status/provider
alert panel, a status bar, and a transient footer. There is no editor activity
rail, file-tab strip, workspace browser, or duplicate navigation column.
Providers, Models, Routing, Context Window, Local Setup, Settings, Usage, and
Diagnostics are reached directly from the page-navigation sidebar. Main list
navigation and page-navigation movement stop at the first and last row; only
choice controls that represent a finite cycle intentionally wrap.

Keybindings: `Ctrl+B` toggles page navigation, `Ctrl+J` the FCC status panel,
`Ctrl+0`/`Ctrl+1` move focus between navigation and the selected page, and
`Tab`/`Shift-Tab` move focus without changing pages or an opened file;
`↑↓`/`j`/`k` move in the focused control, `Enter` opens or applies the
highlighted FCC action, `/` searches models when the Models page owns focus,
`P` opens the registered-provider picker, `N` toggles All/Free only, `V`
toggles Active/Catalog, `T` toggles the selected models' actual ON/OFF state,
`Shift-X` disables all, and `R` refreshes the current FCC page. Mouse clicks
activate modal choices in one step; PageUp/PageDown/Home/End stay within the
currently focused finite control. Optional
`fcc-tui` path/diff/review flags remain bounded CLI conveniences; they do not
turn the visible control center into an editor.

When a direct `fcc` or `fccdanger` launch has to start the local server, the
requested client arguments and working directory are held as pending launch
context. The control center appears after server readiness, and the user
chooses the Normal or Danger action. A Normal click removes a pending danger
flag so the choice is an actual safety decision, not decorative text.

`fcc-server --headless` remains the explicit server-only escape hatch. The Rust source is intentionally kept inside the Python package tree so an editable AgentSwitchboard checkout can run the frontend directly against the same local server without copying configuration or provider code.

Hosted CI installs Rust `1.88.0` and runs `rustfmt`, Clippy with warnings denied, and the Rust test suite on the exact PR head. The ordinary Python Ruff/ty/pytest gates remain unchanged.
