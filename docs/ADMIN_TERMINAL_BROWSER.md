# Terminal-only FCC startup

This personal fork does not launch a desktop browser, `terminal-browser`, or
any other browser presentation for the local Admin surface. `fcc-server` is a
terminal process and reports readiness in the terminal.

```bash
fcc-server
```

If another FCC instance already owns the configured port, the command reports
the healthy instance and exits. If an unrelated process owns the port, FCC
reports that conflict without emitting a Uvicorn bind traceback.

`fcc-server --terminal` and `fcc-server --no-browser` are accepted as explicit
terminal-only compatibility flags. Browser-opening flags and the old
`FCC_OPEN_BROWSER`/`FCC_ADMIN_OPEN_MODE` presentation settings are not part of
this fork's startup contract.

The local HTTP Admin API remains an implementation surface for explicitly
scripted local tooling. It is never opened automatically by FCC. Normal agent
work stays in the terminal through `fcc-claude`, `fccdanger`, `fcc-codex`, or
`fcc-pi`. `fccdanger` is the personal-fork convenience alias that adds
`--dangerously-skip-permissions` while retaining FCC routing.
