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

## Attribution rule for future ports

Any future copied or adapted implementation must record its source repository,
exact revision, license, local path, and modification status here before it is
distributed. Unlicensed or unclear material may be used as behavioral reference
only and must not silently become copied source.
