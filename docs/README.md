# AgentSwitchboard documentation

This directory contains current user-facing feature and operations references
for the terminal-only AgentSwitchboard release. The top-level [README](../README.md)
is the install and daily-driver entry point; this index keeps the feature
boundaries explicit so design notes are not mistaken for release guarantees.

AgentSwitchboard is the current product name. The `fcc*`, `FCC_*`, and
`free_claude_code` names that appear in commands, configuration, imports, and
receipts are retained compatibility identifiers, not a competing product brand.

## Current documentation

| Document | Scope | Status |
| --- | --- | --- |
| [Configuration](CONFIGURATION.md) | `~/.fcc/.env`, provider/model refs, context, reasoning, routing isolation, and local state | Current release-head configuration contract |
| [Troubleshooting](TROUBLESHOOTING.md) | Terminal diagnostics for server, route, model, compact/resume, and auth failures | Current release-head runbook |
| [Claude context policy](CLAUDE_CONTEXT_POLICY.md) | Client context cap, advisory global leash, hard artifact-backed governor, and compact receipts | Current; live receipts are boundary-specific |
| [Learning, memory, and skills](CLAUDE_LEARNING.md) | Hook lifecycle, local state, safety rails, and CLI controls | Current; optional integration |
| [Terminal-only startup](ADMIN_TERMINAL_BROWSER.md) | `fcc-server` lifecycle and the no-browser contract | Current AgentSwitchboard policy |
| [Smoke and receipt guide](../smoke/README.md) | Deterministic and opt-in live validation, receipt schemas, and evidence limits | Current validation guide |
| [Upstream regression watch](UPSTREAM_REGRESSION_WATCH.md) | Bounded provenance registry for promoted external edge cases | Current manual registry; no hot-path polling |
| [Diagnostics](DIAGNOSTICS.md) | Terminal-only synthetic route and capability explanations | Current; zero-network diagnostic surface |
| [Terminal visual UX](TERMINAL_VISUAL_UX.md) | Bounded image attachment cards, previews, and local source handling | Current; local presentation only |

## Active design and conformance contracts

These documents are intentionally kept in the repository so implementation
agents have one current contract instead of reviving old stacked design PRs.
They may describe partially shipped behavior and future acceptance criteria;
each document begins with an explicit status banner.

| Document | Scope |
| --- | --- |
| [Capability-aware routing](CAPABILITY_ROUTING.md) | Request-derived capability truth, controller/helper policy, provider isolation, and future semantic computer-use routing |
| [Claude compatibility firewall](CLAUDE_COMPATIBILITY_FIREWALL.md) | Known-good client certification, process containment, candidate promotion/quarantine, and update-survival fixtures |
| [Reasoning presentation conformance](REASONING_PRESENTATION_CONFORMANCE.md) | Truthful separation of reasoning usage, visible summaries, opaque continuation state, Anthropic thinking blocks, and Claude UI behavior |
| [Compaction conformance](COMPACTION_CONFORMANCE.md) | Effective-window, compact/resume, semantic continuity, inheritance, and economic acceptance rules |
| [Context-pressure leash](CONTEXT_PRESSURE_LEASH.md) | Managed Claude guidance, hard artifact-backed result governance, and OFF-vs-ON effectiveness testing |
| [Upstream harvest plan](UPSTREAM_ROUTER_HARVEST.md) | Fork/adapt/wrap/test-only rules for router, Playwright browser, macOS AX, and capability prior art |

The maintainer architecture map is [ARCHITECTURE.md](../ARCHITECTURE.md). It
describes package ownership and extension boundaries, not a promise that every
optional package surface is part of the daily-driver release.

Attribution and licensing are documented in [UPSTREAM.md](../UPSTREAM.md) and
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Evidence vocabulary

Documentation uses these terms deliberately:

- **Current-source verified** means code, deterministic tests, and the local CI
  sequence passed on the checked-out release head.
- **Live receipt evidence** means a sanitized client/provider run was captured;
  the receipt's own package version, commit metadata, and scope remain
  authoritative.
- **Partial** means a boundary is implemented but not part of the compact Muse
  release claim or lacks a complete client/provider matrix.
- **Unverified** means the observed probe did not establish the requested
  boundary. It is not a success claim.
- **Planned/design** means no shipped runtime guarantee is documented.

The current status summary and the exact checked-in receipt links live in the
[top-level README](../README.md). Raw prompts, tool payloads, provider bodies,
credentials, and local debug traces are intentionally not documentation
artifacts.

## Documentation audit rule

When a command, model ref, environment variable, or receipt changes, update the
smallest authoritative document and run the documentation-link contract. The
release version in the README must match `[project].version` in `pyproject.toml`.
Historical receipts are not rewritten to look like a later release; capture a
new receipt when current-release live evidence is required.
