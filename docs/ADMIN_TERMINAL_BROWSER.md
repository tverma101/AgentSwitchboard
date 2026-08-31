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

The control center is a Textual application with a persistent sidebar and a
main pane. Navigate with the arrow keys, mouse, or Enter. The Claude and Danger
buttons launch the selected next-launch profile and repository; the application
returns to the control center when that child exits or reports a launch error.
Launch failures remain in a persistent red error card with the actionable
diagnostic and exit status. When the FCC Claude compatibility firewall blocks a
version, the launcher automatically tries an exact known-good executable from
the configured path, PATH, or FCC's private npm offline cache; it never enables
uncertified mode or substitutes an unverified older binary. The error screen
also exposes visible `Repair & start` buttons, so a missing fallback can be
repaired and retried without quitting `fcc-server`.
If `fcc-claude` starts its own server owner, it launches the original Claude
arguments after the server is ready and then returns to this same control
center.

Each page exposes explicit buttons for its actions. Profiles can be created and
selected without nested shell prompts. Models use full-width rows: Space or a
click toggles a pending selection, while `Enable selected`, `Disable selected`,
and `Disable all` are separate actions. `Disable all` clears the curated
allowlist but retains the discovered inventory so it can be searched and
re-enabled. The Models page provides provider, search, and `Free first`/
`Free only`/`All prices` filters; filters never enable a model implicitly.
The discovery response is reused while filtering or searching, so typing does
not issue a provider request for every key. Use `Refresh` to explicitly fetch a
new discovery snapshot. The provider filter also includes configured/usable
providers that do not have a cached model row yet; selecting one shows an
explicit message telling the user to refresh that provider.

The Repositories page pairs each remote identity with its local checkout folder;
branch and home-relative path details are available in the same table. The first
load uses the fresh local repository cache when available, while `Refresh` forces
a live scan of the configured roots. Remote metadata is shown when available, but
a GitHub CLI login is not required. The current working directory is selected by
default, the selected folder is marked and restored after refresh, and `Open path`
adds a checkout outside the standard scan roots.
Repository and profile selection is local-only: it applies to the next child
launch and does not change a live server/session namespace. Locked Admin fields
remain read-only. Provider,
account, usage, diagnostics, policy, logs, and settings actions report failures
in the page summary and an error notification instead of silently flashing away.
The command palette's theme selection is persisted in
`~/.fcc/control-center.json`.

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

FCC's provider account and Codex Tool Accounts are separate. The FCC provider
uses `~/.fcc/auth/openai.json`; `fcc accounts` uses `$CODEX_HOME/auth.json` and
`$CODEX_HOME/accounts/profiles`. The command lists, switches, refreshes, adds,
and forgets private local Codex auth snapshots without logging out an upstream
account; selections apply only to new Codex/helper sessions.

The Accounts and Providers pages are separate sidebar destinations. FCC account
login/switching never changes the Codex Tool Account store, and Codex account
switching never changes FCC provider authentication.
