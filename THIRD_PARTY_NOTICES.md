# Third-party notices

This inventory covers third-party source currently identified as copied or
ported into AgentSwitchboard. Research notes and protocol references remain
separate from distributed implementation; a reference in `docs/` is not, by
itself, a copied-code notice.

## OpenAI Codex screenshot subset

AgentSwitchboard includes a deliberately small, modified subset of the OpenAI
Codex screenshot skill:

- **Local path:** `src/free_claude_code/cli/_vendor/openai_screenshot/`
- **Source:** [`openai/skills` at commit `49f948faa9258a0c61caceaf225e179651397431`](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/screenshot)
- **License:** Apache License 2.0
- **Notice:** [the preserved local license](src/free_claude_code/cli/_vendor/openai_screenshot/LICENSE.txt)

Only the macOS Screen Recording permission and focused-window primitives are
carried forward. The general-purpose screenshot CLI, non-macOS support,
interactive capture paths, and unrelated environment behavior are not vendored.
The modified derivative files retain their source headers and are wrapped by
AgentSwitchboard privacy admission, authorization, validation, receipt, and
persistence policy.

## Codex Computer Use app-server reference

The active app-server/session shape was cross-checked against
**fitchmultz/macuse** at commit `447df5214c143c7e88e644295451fc81fee71d70`:

- **Source:** [fitchmultz/macuse](https://github.com/fitchmultz/macuse)
- **License:** MIT
- **Use in AgentSwitchboard:** behavioral and protocol reference only; no
  macuse source or binary is distributed. FCC keeps its own Python MCP
  boundary, policy checks, native-contract validation, screenshot preservation,
  and bounded read-only recovery.

## Attribution rule for future ports

Any future copied or adapted implementation must record its source repository,
exact revision, license, local path, and modification status here before it is
distributed. Unlicensed or unclear material may be used as behavioral reference
only and must not silently become copied source.

## Harlequin TUI patterns

The AgentSwitchboard terminal control-center redesign vendors and adapts UI shell patterns and components from **Harlequin**, pinned to commit `fcfaa6c524a6cd47e17701d931eac0243c8c85b6`:

- Upstream: `tconbeer/harlequin`
- License: MIT
- Copyright (c) 2023 Ted Conbeer

The reused/adapted material includes the persistent left/right application shell, focus/border conventions, footer/navigation behavior, confirmation-modal interaction, and related Textual layout patterns. AgentSwitchboard-specific provider/account/repository/profile actions remain AgentSwitchboard code.

Harlequin's MIT license notice:

> MIT License
>
> Copyright (c) 2023 Ted Conbeer
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## tuiui desktop interaction patterns

The desktop-style control-center shell and model browser adapt interaction and
layout patterns from **tuiui**, pinned to commit
`09c28e13f30f9616868411ac40637b7daf8e5384`:

- Upstream: `jaylfc/tuiui`
- License: MIT
- Copyright (c) 2026 JAN LABS LTD (https://janlabs.co.uk)
- Local adaptation: `src/free_claude_code/cli/model_picker_tui.py`

The adaptation is limited to terminal-desktop interaction ideas and presentation
patterns: compact desktop chrome, launcher-like navigation, native-window/panel
hierarchy, dense list + inspector settings workflows, and mouse-first controls.
AgentSwitchboard does **not** vendor tuiui's Rust daemon, PTY/apphost runtime,
remote-session stack, file manager, compositor, or binaries. All provider,
model, settings, launch, and persistence actions continue to use
AgentSwitchboard's existing Python/Textual backends.

tuiui's MIT license notice:

> MIT License
>
> Copyright (c) 2026 JAN LABS LTD (https://janlabs.co.uk)
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.
