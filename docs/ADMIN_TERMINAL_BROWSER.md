# Terminal-only FCC startup

AgentSwitchboard does not launch a desktop browser, `terminal-browser`, or
any other browser presentation for the local Admin surface. `fcc-server` is a
terminal process and reports readiness in the terminal.

```bash
fcc-server
```

If another FCC instance already owns the configured port, the command reports
the healthy instance and attaches the control center without claiming its
lifecycle. If the port is free, this process owns the supervisor until the
control center exits. If an unrelated process owns the port, FCC reports that
conflict without emitting a Uvicorn bind traceback. Use `--headless` or a
non-TTY invocation for the prior blocking server-only behavior.

The control center is a native Rust/Ratatui application with a persistent
sidebar and a main pane. Navigate with the arrow keys, mouse, or Enter. `C`
launches `fcc-claude` and `!` launches `fccdanger`; the frontend suspends while
the child runs, then returns with the exit result visible. `R` refreshes the
current server snapshot and `Q` exits. The full interaction and API contract
are documented in [RUST_CONTROL_CENTER.md](RUST_CONTROL_CENTER.md).

The Providers page shows the server's independent provider inventory and
supports tests, connected-account login/disconnect, and custom-provider CRUD.
The Models page is a live catalog browser: `/` filters the loaded snapshot
instantly, chips group and filter by provider/price/enabled state, and the
inspector shows ref, alias, capabilities, and pricing. Making a model default
enables it; Save persists `MODEL` plus catalog mode/allowlist through the
Admin API and read-back-verifies those fields. Disabled discovered models stay
visible so they can be re-enabled. Settings, local setup, routing, context,
usage, and diagnostics remain explicit Admin API operations.

Repository selection is provided by `fcc-repos`, not by the server lifecycle
screen. The picker rebuilds metadata from live Git state and shows only existing
checkout folders with a GitHub remote. Linked Git worktrees, local-only clones,
and non-GitHub remotes are excluded. A GitHub CLI login is optional; when an
identity is available it scopes the remote owner. Use `fcc-repos --refresh
--root ~/src` to force a bounded rescan.

The native frontend loads one Admin snapshot at startup and does not request
provider data on every redraw. `R`, model refresh, field edits, provider tests,
and diagnostics are explicit loopback Admin API actions.

`fcc-server --terminal` and `fcc-server --no-browser` are accepted as explicit
terminal-only compatibility flags. Browser-opening flags and the old
`FCC_OPEN_BROWSER`/`FCC_ADMIN_OPEN_MODE` presentation settings are not part of
this fork's startup contract.

The local HTTP Admin API remains an implementation surface for explicitly
scripted local tooling. It is never opened automatically by FCC. Normal agent
work stays in the terminal through `fcc-claude`, `fccdanger`, `fcc-codex`, or
`fcc-pi`. `fccdanger` is the personal-fork convenience alias that adds
`--dangerously-skip-permissions` while retaining FCC routing.

The native terminal redraw uses already-loaded state and does not make an Admin
request. Explicit settings edits still use the local Admin API; the Rust client
refreshes its snapshot after a successful mutation.

FCC's provider account and Codex Tool Accounts are separate. The FCC provider
uses `~/.fcc/auth/openai.json`; `fcc accounts` uses `$CODEX_HOME/auth.json` and
`$CODEX_HOME/accounts/profiles`. The command lists, switches, refreshes, adds,
and forgets private local Codex auth snapshots without logging out an upstream
account; selections apply only to new Codex/helper sessions.

FCC account login/switching never changes the Codex Tool Account store, and
Codex account switching never changes FCC provider authentication. Use `fcc
accounts` for the separate Codex Tool Account store; the native Providers page
only operates on FCC provider state.
