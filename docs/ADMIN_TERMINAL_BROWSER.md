# Terminal-native Admin UI

FCC can present its local Admin web UI through Zenbu Labs' `terminal-browser` instead of opening a separate desktop browser window.

The Admin surface remains the same local `http://127.0.0.1:<port>/admin` application. FCC does not reimplement the page as a text TUI. When available, it launches the real Chromium-rendered page with:

```bash
terminal-browser open http://127.0.0.1:<port>/admin --app-mode
```

`--app-mode` removes browser chrome/frame/shortcuts, allows clipboard reads, and keeps links that would create new tabs in terminal-browser's popup stack. See the upstream project for supported terminals and current installation instructions:

- https://github.com/zenbu-labs/terminal-browser

## Selection policy

Set `FCC_ADMIN_OPEN_MODE` to one of:

- `auto` (default): prefer terminal-browser when FCC is running in an interactive terminal and the executable is installed; otherwise use the operating-system browser.
- `terminal`: use terminal-browser only from an interactive terminal. If no interactive TTY is available, it is missing, or it fails during startup, print the Admin URL and **do not** surprise-open a desktop browser.
- `browser`: always retain the historical `webbrowser.open(...)` behavior.

For a terminal-only personal setup:

```bash
FCC_ADMIN_OPEN_MODE=terminal
```

The existing `FCC_OPEN_BROWSER=false` switch still disables automatic Admin presentation entirely.

## Failure behavior

FCC probes a terminal-browser child briefly. An immediate non-zero exit is treated as a startup failure. In `auto` mode FCC falls back to the system browser; in `terminal` mode it leaves the URL in the terminal and does not open anything else.

Desktop/tray launches remain browser-oriented in `auto` mode because they do not inherit an interactive terminal.

## Why this is separate from the Admin UI

The provider/configuration frontend and the presentation mechanism are intentionally independent:

```text
FCC Admin web app
      |
      +-- desktop browser
      `-- terminal-browser --app-mode
```

That keeps provider/auth/model behavior unchanged and lets the dense Admin redesign evolve separately from the local-window routing policy.
