# Terminal-only FCC startup

This personal fork does not launch a desktop browser, `terminal-browser`, or
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

The control center keeps the surface intentionally small: Enter/C launches
`fcc-claude`, D launches `fccdanger`, O selects a locally discovered repository,
F selects or manages the next-launch learning profile (including explicit
bundle preview/transfer), P opens provider/account status and explicit
configuration, testing, local reachability, or connected-account login
actions, and lets the user add, edit, test, enable/disable, or remove custom
providers through the canonical Admin API. M lists cached models and opens the
shared filterable picker for an explicit model change, U shows local usage, X
runs metadata-only route diagnostics, S edits Model and Reasoning Policy
through the canonical loopback Admin API, L previews/filters the existing
structured server log, R restarts only an FCC supervisor owned by this
terminal, and Q exits. Locked Admin fields remain read-only. Repository and
profile selection are local-only; they are passed to the child launch and do
not change a live server/session namespace.

The home screen is deliberately local-only: it uses the startup settings
snapshot and supervisor state and does not request Admin/provider data on every
redraw. Network or provider work happens only after an explicit action.

`fcc-server --terminal` and `fcc-server --no-browser` are accepted as explicit
terminal-only compatibility flags. Browser-opening flags and the old
`FCC_OPEN_BROWSER`/`FCC_ADMIN_OPEN_MODE` presentation settings are not part of
this fork's startup contract.

The local HTTP Admin API remains an implementation surface for explicitly
scripted local tooling. It is never opened automatically by FCC. Normal agent
work stays in the terminal through `fcc-claude`, `fccdanger`, `fcc-codex`, or
`fcc-pi`. `fccdanger` is the personal-fork convenience alias that adds
`--dangerously-skip-permissions` while retaining FCC routing.

The terminal control-center home redraw uses the already-loaded local settings
object and does not make an Admin request. Explicit settings edits still use
the local Admin API; after a successful edit, the terminal invalidates its
settings cache before the next redraw.

Codex ChatGPT subscription profiles are managed separately with `fcc accounts`.
That command lists, switches, refreshes, adds, and forgets private local auth
snapshots without logging out an upstream account; selections apply only to
new Codex/helper sessions.
