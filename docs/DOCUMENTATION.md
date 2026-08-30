# Documentation maintenance

This guide defines how AgentSwitchboard documentation is organized, reviewed, and
retired. The [documentation catalogue](README.md) is the discovery entry point;
this page is the maintenance policy behind it.

**Last documentation audit:** 2026-08-30

## Organize by reader need

Use one primary purpose per document. The repository applies a lightweight
[Diátaxis](https://diataxis.fr/) model:

| Content type | Reader need | AgentSwitchboard examples |
| --- | --- | --- |
| Tutorial / quickstart | Learn the product by completing a guided path | [README](../README.md) quick start |
| How-to / troubleshooting | Complete one task or recover from one symptom | [Configuration](CONFIGURATION.md), [Troubleshooting](TROUBLESHOOTING.md), [Terminal startup](ADMIN_TERMINAL_BROWSER.md) |
| Reference | Look up stable commands, settings, schemas, or boundaries | [Diagnostics](DIAGNOSTICS.md), [Context policy](CLAUDE_CONTEXT_POLICY.md), [Smoke guide](../smoke/README.md) |
| Explanation / architecture | Understand why the system is shaped this way | [Architecture](../ARCHITECTURE.md), [Boundary manifest](CLAUDE_BOUNDARY_MANIFEST.md) |
| Contract / design record | Preserve an implementation decision and its acceptance boundary | [Capability routing](CAPABILITY_ROUTING.md), [Compaction](COMPACTION_CONFORMANCE.md) |
| Provenance / history | Record source, licensing, research, or a time-bounded event | [Upstream](../UPSTREAM.md), [Third-party notices](../THIRD_PARTY_NOTICES.md), upstream harvest notes, and the Codex turn log |

A document may combine closely related types, but its opening paragraph and
catalogue entry must make the primary purpose clear. Do not create a receipt-only
page when the evidence belongs in an existing receipt, contract, or registry.

## Source-of-truth ownership

Keep each fact in the smallest authoritative document and link to it elsewhere.
When two pages need the same fact, one page owns the detail and the other gives a
short summary plus a link.

| Fact or task | Authoritative document |
| --- | --- |
| Install, daily use, supported release claim, and public project links | [README.md](../README.md) |
| Package boundaries, runtime ownership, extension checklists, and verification architecture | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| Contributor workflow and pull-request checks | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Environment variables, settings precedence, model/provider values, and local state | [CONFIGURATION.md](CONFIGURATION.md) and [.env.example](../.env.example) for the complete template inventory |
| User symptoms and recovery steps | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Diagnostic command output and metadata-only receipts | [DIAGNOSTICS.md](DIAGNOSTICS.md) |
| Smoke target taxonomy, opt-ins, fixtures, and failure classes | [smoke/README.md](../smoke/README.md) |
| Current documentation discovery, status vocabulary, and maintenance policy | [docs/README.md](README.md) and this page |
| Protocol, routing, compaction, reasoning, context, learning, and helper contracts | The named contract page in the [catalogue](README.md) |
| Copied/adapted code and license obligations | [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) |
| Upstream attribution and project history | [UPSTREAM.md](../UPSTREAM.md) |
| External research and pinned behavioral references | The relevant `*_UPSTREAMS.md` or `*_HARVEST.md` decision record |
| Historical issue-sweep state and turn-specific notes | The relevant `OPEN_ISSUE_*` page or `docs/codex/turn-log.md`; never treat it as current product status without its status wording |

The catalogue also lists repository instruction files and non-Markdown
configuration/assets so contributors can find the complete documentation surface.

## Status and evidence vocabulary

Use these labels consistently:

- **Current** — describes the checked-out release-head behavior or a maintained
  user workflow.
- **Active contract** — an implementation boundary that must remain true; it may
  include planned acceptance work and is not, by itself, a shipped-feature claim.
- **Partial** — some behavior is implemented, but a stated release or evidence
  boundary is incomplete.
- **Planned / design** — a proposed behavior with no shipped runtime guarantee.
- **Operational** — a command or runbook for an explicit validation or maintenance
  action; its result is not implied by the existence of the page.
- **Provenance / historical** — a source, decision, or time-bounded record. Do not
  rewrite it to make old evidence appear current.
- **Unverified** — an observation or acceptance boundary that has not been proved.
  It is not a success claim.

Live receipts must identify their own version, commit, scope, and boundary. A
receipt-only issue or completed certification run does not make a feature broadly
supported. Keep raw prompts, responses, screenshots, tool payloads, credentials,
and local debug traces out of committed documentation and receipts.

## When documentation changes

Update documentation in the same change as the behavior it describes. At minimum,
check these triggers:

| Change | Required documentation check |
| --- | --- |
| Install command, launcher, client workflow, or release claim | Update `README.md`; update the relevant how-to/reference page if detail changes |
| Environment variable, default, precedence, provider/model, or local-state path | Update `docs/CONFIGURATION.md` and `.env.example` when the template changes |
| User-visible failure or recovery behavior | Update `docs/TROUBLESHOOTING.md` and, when useful, `docs/DIAGNOSTICS.md` |
| API, wire protocol, routing, context, reasoning, compaction, or tool behavior | Update the owning contract and its deterministic tests |
| Smoke target, receipt schema, evidence class, or live prerequisite | Update `smoke/README.md` and the relevant operational page |
| Package boundary, lifecycle, resource ownership, or extension point | Update `ARCHITECTURE.md` |
| Copied/adapted third-party source or changed upstream pin | Update `THIRD_PARTY_NOTICES.md` before distribution and the relevant research note |
| New or renamed Markdown page | Add it to `docs/README.md` and preserve a useful incoming link |
| Closed, superseded, or historical issue evidence | Retain traceability, but remove wording that presents it as an active backlog item |

Do not duplicate a full command table, environment inventory, release claim, or
receipt interpretation in several pages. Link to the owner instead.

## Writing and review rules

The repository follows the practical guidance from
[GitHub's documentation best practices](https://docs.github.com/en/contributing/writing-for-github-docs/best-practices-for-github-docs):

- name the audience and purpose before adding detail;
- put the conclusion and prerequisites first;
- use meaningful headings, short paragraphs, lists, tables, and in-page links;
- use plain language, active voice, and one main idea per sentence or paragraph;
- distinguish supported behavior from examples, experiments, and future work;
- make commands copyable and state the expected result and failure boundary;
- use descriptive link text and verify relative links after renames.

Documentation is maintained as code, following the
[Write the Docs docs-as-code guidance](https://www.writethedocs.org/guide/docs-as-code/):
plain-text files live in Git, changes are reviewed with the product change, and
automated checks protect links and catalogue completeness. A docs-only change
still needs a focused review of accuracy, scope, privacy, and discoverability.

## Evidence and provenance rules

- Prefer current source and deterministic tests for claims about repository
  behavior.
- Mark live provider, device, installed-client, and benchmark evidence explicitly;
  a skipped prerequisite is `unverified`, not `passed`.
- Preserve historical receipt metadata and capture a new receipt for a new release
  or boundary. Never edit an old receipt to imply later code or a broader scope.
- For upstream research, record the repository, exact revision, license, relevant
  file or behavior, and whether the material was copied, adapted, wrapped, or only
  referenced. Use [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for shipped
  source and the research notes for reference-only material.
- Keep documentation examples free of real credentials, private URLs, prompt
  content, response content, raw tool arguments, image bytes, and personal data.
- If a claim cannot be verified from code, deterministic tests, or clearly marked
  external evidence, say so instead of filling the gap with a plausible statement.

## Review checklist

Before merging documentation:

1. Confirm the page has one clear audience and primary purpose.
2. Update the authoritative page rather than copying stale detail elsewhere.
3. Check commands, paths, environment variables, defaults, versions, and expected
   results against the current source.
4. Check status/evidence wording, especially around live receipts and historical
   issue records.
5. Add or update catalogue navigation and use descriptive relative links.
6. Remove secrets and raw user/provider payloads from examples and artifacts.
7. Run the focused documentation contracts and `git diff --check`.
8. Run the full local CI sequence when documentation accompanies runtime changes or
   when branch-level assurance is needed.

## Local validation

Run the focused contracts from the repository root:

```bash
uv run pytest -n 0 \
  tests/contracts/test_documentation_links.py \
  tests/contracts/test_documentation_catalog.py \
  tests/contracts/test_branding_docs.py \
  tests/contracts/test_open_issue_certification_docs.py \
  tests/contracts/test_open_issue_sweep_commands.py \
  tests/contracts/test_open_issue_sweep_status.py
```

Also run:

```bash
git diff --check
```

Use `./scripts/ci.sh` for the complete local sequence when the documentation
change is coupled to production behavior. Documentation-only changes do not
require a semantic-version bump under the repository versioning policy.
