# terminal-code interaction transplant

Status: research / decision record. This page records what was verified about
the external `terminal-code` project, which interaction ideas were transplanted
into AgentSwitchboard's native control center, and which parts were explicitly
rejected. It is not a release claim about VS Code compatibility.

## Verified upstream facts

Fetched and read end to end on 2026-09-03 (no vendored source; behavioral
reference only):

| Source | Verified content |
| --- | --- |
| `zenbu-labs/terminal-code` (GitHub) | "VS Code inside your terminal"; MIT license; ~1.9k stars / 77 forks at fetch time; `tode` CLI with `open path`, `--goto f:l:c`, `--add`, `--new-window`, `--wait`, `--diff a b`, `--reuse-window`, `--install-extension` / `--uninstall-extension` / `--list-extensions`, `--split direction` / `--size fraction`, `--timing`, `--review`, `--ssh`, `--shortcut-setup`, `--import`, `--theme`, `--serve`, `--skill`, `--upgrade`, `--shutdown`, `--uninstall` |
| `terminal-code.com` | Same install (`curl -fsSL https://tode.sh/install \| bash`) and command summary |
| `zenbu-labs/terminal-browser` (GitHub) | "A real browser that runs inside your terminal"; MIT license; ~2.5k stars at fetch time; renders Chromium pixels via Electron offscreen rendering through the Kitty graphics protocol; outer UI is a Rust engine with a React-defined interface; `--app-mode` bundles toolbars/shortcuts/overlays off |
| How it works (both READMEs) | `terminal-code` = `code-server` (VS Code in the browser) + `terminal-browser` (browser in the terminal) |

Not verified: the launch-post date, like/repost counts, and author handles
supplied with the request could not be confirmed from the repository or website
fetches above (social metrics need an authenticated session). They are not
repeated here as facts.

## Architecture decision

A literal transplant of the pixel path (code-server + Chromium/Electron +
Kitty pixels) is rejected for this repository:

- The terminal-only startup contract (`docs/ADMIN_TERMINAL_BROWSER.md`) forbids
  launching a desktop browser, `terminal-browser`, or any browser presentation
  for the Admin surface.
- The Rust frontend accepts only a loopback Admin base URL
  (`src/free_claude_code/native_tui/src/api.rs`); an SSH-remote or
  browser-hosted session cannot satisfy that guard.
- The install surface is a Python wheel plus a small Rust binary; a
  Chromium/Electron runtime is not an acceptable dependency, and Windows has no
  official terminal-code build either.
- The cell-exact geometry contract (`docs/RUST_CONTROL_CENTER.md`) governs the
  native UI; pixel-perfect VS Code rendering is explicitly out of scope.

What was transplanted instead is the interaction model, reimplemented natively:

| terminal-code idea | FCC native form |
| --- | --- |
| Command palette (`cmd+p` / `ctrl+k`) | `Ctrl+K` / `Ctrl+P` palette in the Rust control center covering all 9 pages plus every page-contextual action (`src/free_claude_code/native_tui/src/app.rs`: `palette_inventory`, `match_palette`) |
| `tode [path]` workspace open | `fcc-tui [path]` validates the path and attaches with a workspace notice |
| `tode --goto f:l:c` | `fcc-tui --goto <file:line:col>` with existence and range validation |
| `tode --diff a b` | `fcc-tui --diff <a> <b>` prints a bounded (120-line) unified preview, then attaches |
| `tode --review` | `fcc-tui --review` prints a bounded `git status` snapshot, then attaches |
| `tode --split/--size` | `fcc-tui --split/--size` prints a tmux split suggestion when `TMUX` is set, otherwise fails closed with guidance; the TUI never splits the terminal itself |
| `tode --theme` | `fcc-tui --theme` accepts the built-in `dark` theme and rejects anything else |
| `tode --shortcut-setup` | `fcc-tui --shortcut-setup` prints the terminal-vs-TUI conflict table using Kitty/Ghostty/iTerm2/VS Code/tmux markers |
| `tode --timing` | `fcc-tui --timing` reports parse/settings/total stage timings |
| `tode --list-extensions` | `fcc-tui --list-commands` lists the palette inventory (FCC manages providers/models, not VS Code extensions) |

Explicitly rejected with a fail-closed error: `--ssh` (loopback-only Admin),
`--install-extension` / `--uninstall-extension` (use the Providers page for
custom OpenAI-compatible endpoints). Server lifecycle verbs (`--serve`,
`--shutdown`, `--upgrade`, `--uninstall`) remain owned by `fcc-server` and the
repository installers.

## Verification

```bash
cargo test --manifest-path src/free_claude_code/native_tui/Cargo.toml
cargo clippy --manifest-path src/free_claude_code/native_tui/Cargo.toml --all-targets -- -D warnings
uv run pytest -n 0 tests/cli/test_rust_tui.py tests/cli/test_entrypoints.py
./scripts/ci.sh --fast
```

Rust palette coverage: `palette_inventory_reaches_every_page` (all 9 pages),
filter semantics, open/execute/cancel/quit/out-of-range cases, and the
cell-exact chrome test with the palette open. Python coverage: workspace,
goto, diff preview + truncation, split with/without tmux, ssh/extension
rejections, `--list-commands` page coverage, shortcut setup, review rejection
outside a checkout, timing, and help.

## Provenance

Behavioral reference only; no terminal-code or terminal-browser source is
vendored or distributed. Both upstreams are MIT-licensed Zenbu Labs projects.
