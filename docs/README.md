# AgentSwitchboard documentation catalogue

This catalogue is the discovery entry point for AgentSwitchboard documentation.
It identifies the intended reader, primary purpose, status, and update trigger for
each document so user guidance, maintainer contracts, evidence records, and
historical material are not confused with one another.

The top-level [README](../README.md) is the install and daily-use entry point
(`README.md`). The maintenance policy is [Documentation maintenance](DOCUMENTATION.md)
(`docs/DOCUMENTATION.md`). This catalogue is `docs/README.md`.
AgentSwitchboard is the current product name. The `fcc*`, `FCC_*`, and
`free_claude_code` names that appear in commands, configuration, imports, and
receipts are retained compatibility identifiers, not a competing product brand.

**Catalogue audit:** 2026-08-30. Every tracked Markdown file is listed below.

## Start here

| Reader need | Document | Status |
| --- | --- | --- |
| Install and use the product | [Project README](../README.md) | Current |
| Configure providers, models, and local state | [Configuration](CONFIGURATION.md) | Current |
| Recover from common failures | [Troubleshooting](TROUBLESHOOTING.md) | Current |
| Understand package ownership and extension boundaries | [Architecture](../ARCHITECTURE.md) | Maintainer reference |
| Contribute and run local checks | [Contributing](../CONTRIBUTING.md) | Current contributor workflow |
| Find commands, smoke targets, and evidence limits | [Smoke and receipt guide](../smoke/README.md) | Operational reference |
| Maintain this documentation set | [Documentation maintenance](DOCUMENTATION.md) | Current policy |

## User and operator guidance

These pages help users or operators complete a task. They should lead with
prerequisites, copyable commands, expected results, and a bounded recovery path.

| Path | Audience | Primary purpose | Status | Update when |
| --- | --- | --- | --- | --- |
| `README.md` | Users and operators | Install, launch, use, and understand supported release boundaries | Current | Install, daily workflow, public link, or release claim changes |
| `docs/CONFIGURATION.md` | Users and operators | Environment variables, settings precedence, provider/model values, and local state | Current | A setting, default, provider/model value, precedence rule, or state path changes |
| `docs/TROUBLESHOOTING.md` | Users and operators | Diagnose and recover from server, route, model, compact/resume, and authentication failures | Current | A user-visible failure or recovery step changes |
| `docs/ADMIN_TERMINAL_BROWSER.md` | Operators | Start and administer `fcc-server` while preserving the terminal-only browser policy | Current | Launcher lifecycle, terminal startup, or no-browser behavior changes |
| `docs/RUST_CONTROL_CENTER.md` | Users and maintainers | Explain the native Ratatui control center, Admin API boundary, model/provider controls, and installation contract | Current; installed visual acceptance is separate | Native TUI controls, API boundary, geometry, launcher, or CI contract changes |
| `docs/DIAGNOSTICS.md` | Users and maintainers | Run zero-network diagnostics and interpret synthetic route/capability output | Current | Diagnostic commands, output fields, or safety boundaries change |
| `docs/CLAUDE_CONTEXT_POLICY.md` | Users and maintainers | Explain client context caps, advisory leashes, artifact-backed governance, and compact receipts | Current; boundary-specific live evidence | Context policy, compaction behavior, or receipt interpretation changes |
| `docs/CLAUDE_LEARNING.md` | Users and maintainers | Explain learning hooks, local state, safety rails, and CLI controls | Current; optional integration | Learning lifecycle, state, privacy, or controls change |
| `docs/TERMINAL_VISUAL_UX.md` | Users and maintainers | Define bounded image attachment cards, previews, and local source handling | Current; local presentation only | Terminal presentation or local media-source behavior changes |
| `docs/troubleshooting/tui-hardening.md` | Maintainers and contributors | Record TUI/repository-picker failure classes, recovery behavior, and validation boundaries | Current incident record | TUI state, picker persistence, discovery, or cache behavior changes |
| `docs/troubleshooting/usage-attribution.md` | Maintainers and contributors | Record FCC usage source, account attribution, legacy migration, and labeling boundaries | Current incident record | Usage schema, attribution, or usage-surface labeling changes |

## Architecture and active contracts

These documents explain why the system is shaped this way or preserve boundaries
that implementation must maintain. An **active contract** is not automatically a
claim that every optional or live acceptance path is complete.

| Path | Audience | Primary purpose | Status | Update when |
| --- | --- | --- | --- | --- |
| `ARCHITECTURE.md` | Maintainers and contributors | Map package ownership, runtime lifecycle, protocol flow, testing, and extension checklists | Current maintainer reference | A package boundary, lifecycle, resource owner, or extension point changes |
| `docs/CLAUDE_BOUNDARY_MANIFEST.md` | Maintainers | Assign Claude-facing behavior to delegate, translate, reject, or quarantine boundaries | Active contract | A Claude/provider compatibility boundary or ownership decision changes |
| `docs/CLAUDE_COMPATIBILITY_FIREWALL.md` | Maintainers | Define known-good client containment, candidate promotion/quarantine, and compatibility fixtures | Active contract; some acceptance unverified | Client compatibility, admission, quarantine, or update-survival behavior changes |
| `docs/CLAUDE_PROXY_RETRY_OWNERSHIP.md` | Maintainers | Define retry ownership between Claude Code and the FCC proxy/provider transport | Active contract; implementation decision | Retry, streaming fallback, commit-boundary, or fault-attribution behavior changes |
| `docs/CAPABILITY_ROUTING.md` | Maintainers | Define request-derived capability truth, controller/helper policy, and provider isolation | Active contract; semantic extensions may be planned | Capability detection, routing, helper ownership, or provider isolation changes |
| `docs/REASONING_PRESENTATION_CONFORMANCE.md` | Maintainers | Preserve reasoning usage, visible summaries, opaque continuation state, and UI semantics | Active contract; live acceptance is boundary-specific | Reasoning translation, thinking blocks, summaries, or presentation behavior changes |
| `docs/COMPACTION_CONFORMANCE.md` | Maintainers | Define effective-window, compact/resume, semantic continuity, inheritance, and economic acceptance | Active contract; evidence is scoped | Compaction, resume, fork, child/subagent inheritance, or cache economics changes |
| `docs/CONTEXT_PRESSURE_LEASH.md` | Maintainers | Define managed guidance, hard artifact-backed result governance, and efficacy evidence | Active contract; efficacy receipt unverified where stated | Context-pressure policy, artifact governance, or effectiveness evidence changes |
| `docs/CODEX_SUBSCRIPTION_BRIDGE.md` | Maintainers | Preserve subscription/provider bridge behavior and its compatibility boundary | Active contract; provider acceptance is scoped | Subscription bridge, provider routing, or continuation behavior changes |
| `smoke/README.md` | Maintainers and operators | Define deterministic/live smoke targets, fixtures, receipt schemas, prerequisites, and failure classes | Operational reference | A smoke target, receipt schema, evidence class, or live prerequisite changes |

## Research, provenance, and upstream references

These pages record external source material, pinned behavior, licensing context,
or bounded design research. They are not user-facing release guarantees. Update
source revisions and attribution when the referenced upstream changes; update the
contract owner when the repository adopts or rejects the research.

| Path | Audience | Primary purpose | Status | Update when |
| --- | --- | --- | --- | --- |
| `UPSTREAM.md` | Maintainers and distributors | Record upstream attribution, project history, and provenance | Provenance / historical | Upstream source, attribution, or project history changes |
| `THIRD_PARTY_NOTICES.md` | Maintainers and distributors | Record copied/adapted code, licenses, and distribution obligations | Provenance / licensing | Third-party source, license, or shipped adaptation changes |
| `docs/UPSTREAM_ROUTER_HARVEST.md` | Maintainers | Record router, browser, macOS accessibility, and capability prior art and adoption rules | Research / design record | A source pin, adoption decision, or upstream behavior changes |
| `docs/UPSTREAM_REGRESSION_WATCH.md` | Maintainers | Maintain a bounded registry of promoted external edge cases without hot-path polling | Operational registry; manual | A promoted regression, source revision, or watch policy changes |
| `docs/FALLBACK_POLICY_HARVEST.md` | Maintainers | Preserve fallback-policy research and its implementation boundary | Research / design record | Upstream fallback behavior or the adopted policy changes |
| `docs/CAPABILITY_SNAPSHOT_UPSTREAMS.md` | Maintainers | Record capability-snapshot provenance and behavioral references | Research / decision record | Referenced upstream behavior, revision, or routing decision changes |
| `docs/CODEX_BROWSER_UPSTREAMS.md` | Maintainers | Record browser automation upstreams and the separation between implementation and native acceptance | Research / decision record | Browser upstream, integration seam, or acceptance boundary changes |
| `docs/CODEX_COMPUTER_USE_UPSTREAMS.md` | Maintainers | Record Codex Computer Use protocol and implementation references | Research / decision record | Protocol source, revision, or translation boundary changes |
| `docs/CODEX_COMPUTER_USE_CURRENT_HOST.md` | Maintainers and operators | Record current-host computer-use compatibility facts and remaining evidence boundaries | Operational / host-specific reference | Host capability, helper seam, or native acceptance evidence changes |
| `docs/HELPER_ADAPTER_UPSTREAMS.md` | Maintainers | Record helper-adapter research and the controller/helper ownership seam | Research / design record | Helper protocol, upstream source, or adapter boundary changes |
| `docs/REVIEWER_SCARS_UPSTREAMS.md` | Maintainers | Record provenance and boundaries for reviewer-scar learning concepts | Research / design record | Learning evidence model or referenced upstream changes |
| `docs/codex/turn-log.md` | Maintainers | Preserve time-bounded Codex research and implementation-turn notes | Historical / provenance | A new research turn or correction must be recorded; do not rewrite old evidence |
| `src/free_claude_code/cli/_vendor/openai_screenshot/SOURCE.md` | Maintainers and distributors | Identify vendored screenshot source and its provenance/license context | Vendored-source provenance | Vendored source, revision, or license changes |

## Evidence and verification records

These pages describe validation machinery and historical issue-sweep evidence.
A deterministic result does not certify a live provider, installed client, device,
or benchmark. Closed receipt-only issues remain traceable as historical context,
not as an active backlog claim.

| Path | Audience | Primary purpose | Status | Update when |
| --- | --- | --- | --- | --- |
| `docs/OPEN_ISSUE_CERTIFICATION.md` | Maintainers and release operators | Run reusable deterministic/live certification steps and interpret their boundaries | Operational reference; issue registry is historical where closed | Certification commands, steps, prerequisites, or evidence semantics change |
| `docs/OPEN_ISSUE_SWEEP_COMMANDS.md` | Maintainers and release operators | Provide shared certification, browser-canary, and native-vs-AgentSwitchboard comparator commands | Operational reference | A validation command, argument, output, or prerequisite changes |
| `docs/OPEN_ISSUE_SWEEP_STATUS.md` | Maintainers and reviewers | State implemented evidence machinery and explicit unverified boundaries | Historical/status record; scoped to its recorded revision | A new sweep or implementation boundary needs a new dated status record |
| `docs/README_OPEN_ISSUES.md` | Maintainers and contributors | Redirect issue/evidence discovery to the catalogue and current contracts | Compatibility pointer | The catalogue or evidence-guide locations change |

The certification registry may associate steps with issue identifiers for
traceability. That association does not determine whether a GitHub issue is open,
planned, closed, or supported. Use GitHub issue state and the owning contract for
current status; use receipts for the exact version, commit, scope, and boundary
that they actually prove.

## Repository instructions and contribution governance

These files are part of the documentation surface even though they are not
product user guides. They govern how agents and contributors work in the
repository and must be kept aligned where the project requires parity.

| Path | Audience | Primary purpose | Status | Update when |
| --- | --- | --- | --- | --- |
| `AGENTS.md` | Coding agents and maintainers | Repository-scoped agent instructions and engineering workflow | Current repository policy | Agent workflow, validation, versioning, or safety rules change |
| `CLAUDE.md` | Claude Code and maintainers | Repository-scoped Claude instructions and engineering workflow | Current repository policy; keep identical to `AGENTS.md` | Same trigger as `AGENTS.md`, unless an explicit Codex-only exception is requested |
| `CONTRIBUTING.md` | Contributors | Define contribution workflow, local checks, standards, and versioning | Current contributor workflow | Pull-request checks, setup, standards, or versioning rules change |

## Related non-Markdown assets

The following tracked files are documentation inputs or publication surfaces. They
are not included in the Markdown completeness invariant, but changes to them can
still require documentation updates.

| Path | Audience | Primary purpose | Update when |
| --- | --- | --- | --- |
| `.env.example` | Users and operators | Complete configuration-template inventory | An environment variable, default, or provider/model option changes |
| `.github/ISSUE_TEMPLATE/bug-report.yml` | Issue reporters | Collect reproducible bug information | Required report fields or supported issue workflow changes |
| `.github/ISSUE_TEMPLATE/feature-request.yml` | Issue reporters | Collect feature context and acceptance boundaries | Required request fields or supported issue workflow changes |
| `assets/how-it-works.mmd` | Users and maintainers | Source for the architecture/overview diagram | Runtime flow, package ownership, or displayed architecture changes |
| `assets/*.svg` | Users and maintainers | Branding and documentation illustration assets | Branding, illustration, or referenced product name changes |

## Maintenance summary

For the authoritative ownership table, status vocabulary, update triggers, writing
rules, privacy/provenance requirements, and validation commands, see
[Documentation maintenance](DOCUMENTATION.md). In particular:

- update the smallest authoritative document in the same change as the behavior;
- distinguish current behavior, active contracts, planned work, and unverified
  evidence;
- retain historical issue and receipt traceability without presenting closed
  receipt-only work as an open feature or bug;
- keep secrets, raw prompts, provider payloads, screenshots, and local traces out
  of committed documentation; and
- run the focused documentation contracts plus `git diff --check` before review.
