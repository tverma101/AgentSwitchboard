# Harness documentation

This directory contains current user-facing feature and operations references
for the terminal-only personal Harness fork. The top-level [README](../README.md)
is the install and daily-driver entry point; this index keeps the feature
boundaries explicit so design notes are not mistaken for release guarantees.

## Current documentation

| Document | Scope | Status |
| --- | --- | --- |
| [Configuration](CONFIGURATION.md) | `~/.fcc/.env`, provider/model refs, context, reasoning, routing isolation, and local state | Current release-head configuration contract |
| [Troubleshooting](TROUBLESHOOTING.md) | Terminal diagnostics for server, route, model, compact/resume, and auth failures | Current release-head runbook |
| [Claude context policy](CLAUDE_CONTEXT_POLICY.md) | Client context cap, advisory global leash, hard artifact-backed governor, and compact receipts | Current; live receipts are boundary-specific |
| [Learning, memory, and skills](CLAUDE_LEARNING.md) | Hook lifecycle, local state, safety rails, and CLI controls | Current; optional integration |
| [Terminal-only startup](ADMIN_TERMINAL_BROWSER.md) | `fcc-server` lifecycle and the no-browser contract | Current personal-fork policy |
| [Smoke and receipt guide](../smoke/README.md) | Deterministic and opt-in live validation, receipt schemas, and evidence limits | Current validation guide |
| [Upstream regression watch](UPSTREAM_REGRESSION_WATCH.md) | Bounded provenance registry for promoted external edge cases | Current manual registry; no hot-path polling |

The maintainer architecture map is [ARCHITECTURE.md](../ARCHITECTURE.md). It
describes package ownership and extension boundaries, not a promise that every
optional package surface is part of the daily-driver release.

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
