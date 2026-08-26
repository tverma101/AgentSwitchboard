# Playwright browser helper

**Status: implemented opt-in adapter; live browser evidence is unverified.**

Harness wraps the maintained Microsoft `playwright-cli` executable through
`PlaywrightCliBrowserAdapter`. Harness owns the helper allowlist, explicit
session policy, cancellation boundary, output bounds, privacy filtering, and
metadata-only receipts. Playwright owns browser launch, accessibility
snapshots, locators, navigation, input, console collection, and response-body
handling.

The adapter is not enabled by default and never discovers helpers from the
filesystem or network. Repository-owned startup code must register the helper
before freezing the existing `ApprovedHelperRegistry`:

```python
from free_claude_code.runtime.playwright_cli_browser import (
    PlaywrightCliBrowserAdapter,
)

browser = PlaywrightCliBrowserAdapter(session_name="fcc-browser")
registry.register(browser.approved_helper())
registry.freeze()
```

The executable must already be installed and available as `playwright-cli`, or
passed as an explicit executable path. The adapter never runs `npm`, `npx`, or
an install command. The upstream CLI uses an in-memory browser profile unless
the caller explicitly configures persistence.

## Supported surface

| Harness operation | Official CLI command | Boundary |
| --- | --- | --- |
| `status` | `list` | Session inventory; profile/workspace paths are removed |
| `list_tabs` | `tab-list` | Tab inventory; credentials, query strings, and fragments are removed from URLs |
| `open` / `goto` | `open` / `goto` | Only absolute `http` and `https` URLs without credentials |
| `snapshot` / `find` | `snapshot` / `find` | Accessibility-first inspection |
| `click` / `fill` / `type_text` / `press_key` | matching CLI commands | Fixed semantic input commands only |
| `scroll` / `console` / `screenshot` | matching CLI commands | Console is bounded by the generic helper executor; screenshots are side-effecting because the CLI writes an artifact |
| `download` | `response-body <1-based request index>` | Uses the CLI's managed output location; arbitrary output filenames are not exposed |
| `close` | `close` or `detach` | Attached sessions detach; owned sessions close |

`run-code`, `eval`, storage/cookie commands, arbitrary file paths, and network
request inspection are intentionally not exposed through this helper. In
particular, Playwright's arbitrary-code surface is not an acceptable substitute
for a fixed Harness operation. A download is requested only by a previously
identified request index; it is not a URL fetcher or a way to bypass provider
policy.

Existing-browser attachment requires both `allow_existing_session=True` and an
explicit attachment target. CDP targets are restricted to `chrome`, `msedge`,
or loopback HTTP(S) endpoints. Extension attachment is restricted to the
`chrome` and `msedge` channels. The adapter does not copy cookies, storage
state, page arguments, or output content into helper receipts.

## Upstream decision

Reviewed Microsoft `microsoft/playwright-cli` at
`60cb176373cf4400405122703e6de26cd58c7a1c` (`@playwright/cli` `0.1.18`,
Apache-2.0) and Microsoft `microsoft/playwright-mcp` at
`16cf228d7b02c07f800ec3423f471ec2a42d22a` (Apache-2.0). No upstream source is
copied into Harness. The adapter wraps the installed CLI and records the
command mapping in deterministic tests.

The CLI is selected for the coding-agent path because its official skill
documents a token-efficient session workflow and structured `--json` output.
The MCP server remains a reviewed upstream option for a persistent specialist
loop, but Harness does not add a generic MCP process manager or hot-path
discovery. The existing loopback-only `ChromeCdpBrowserBridge` remains the
narrow fallback for callers that already provide a `BrowserBridgePort`.

The current evidence is source review, deterministic adapter tests, local type
checking, and local static checks. A real browser session, authenticated
attachment, download, and literal Claude/OpenCode tool-call run require a
separate opt-in machine smoke and are not claimed here.
