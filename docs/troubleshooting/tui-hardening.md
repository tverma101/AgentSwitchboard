# TUI hardening and repository-picker incident

## Scope

This record covers the legacy Textual and line-oriented terminal compatibility
surfaces, the native Ratatui control center, the shared selection picker, and
the local repository inventory used by those surfaces. The target behavior is a
recoverable control surface: a failed backend
request must remain visible with a retry path, a refresh must not overwrite newer
state, and selecting a repository must be durable for the next launch.

## Symptoms

Observed and reproducible failure families included stale or duplicated rows after
refresh, controls disappearing after backend errors, selections applying to a row
that was no longer highlighted, repeated live polling/redraws, malformed Admin
responses terminating a menu, unbounded server shutdown waits, and repository
picker selections that appeared successful but were not written to the cache.
Repository discovery also walked overlapping roots and repeatedly observed the
same checkout, which produced duplicate or weaker metadata.

## Root causes

The control surfaces had several independent state owners without a common
commit boundary. Page renders, debounced model filters, live OAuth polling, and
repository scans could overlap; table/cursor state was not always reconciled
against the current rows; and many UI actions assumed JSON lists/dictionaries
even though the Admin boundary is untrusted. The repository cache stored
selection recency separately from the live inventory and did not consistently
carry the authenticated GitHub owner scope. The picker also used raw path-prefix
logic and scanned every configured root even when one root contained another.

## Implemented hardening inventory

The following bug families are covered by the implementation and regression
tests in this branch:

1. stale page renders can no longer overwrite a newer navigation request;
2. page renders are serialized and expected cancellation is quiet;
3. model-filter timers are cancelled on navigation, refresh, and unmount;
4. model discovery is cached per app and refreshed only explicitly;
5. model rows are mounted in batches instead of one asynchronous mount per row;
6. model-row logic uses a stable `model_ref` protocol across picker variants;
7. malformed model refs, prices, labels, and evidence are ignored safely;
8. configured-but-undiscovered model defaults are not silently replaced;
9. model-editor pending changes survive a catalog refresh;
10. model-editor saves reject malformed Admin responses without closing the page;
11. provider identifiers are deduplicated case-insensitively;
12. connected-account polling suppresses unchanged redraws;
13. connected-account polling prevents overlapping requests;
14. unknown or terminal OAuth states stop polling instead of looping forever;
15. dashboard account-summary failures degrade to visible attention text;
16. provider, account, profile, reviewer, usage, policy, settings, and log
    failures retain a visible page and retry/action boundary;
17. malformed Admin mappings/sequences no longer crash field, provider, or
    settings editors;
18. table cursor and selected profile/provider/account state are reconciled after
    rows change;
19. launch failures remain in the TUI with a retry/repair action;
20. owned server shutdown uses a bounded join and reports a still-live worker;
21. broken terminal `isatty` wrappers fail closed to the non-curses path;
22. curses cursor visibility, resize, narrow-terminal, and bounded-line writes
    are defensive;
23. launcher failures, huge numeric input, and malformed model/provider payloads
    remain inside the terminal menu;
24. repository paths are canonicalized before identity, selection, and recency
    comparison;
25. home-relative display paths no longer misclassify sibling directories with a
    shared textual prefix;
26. duplicate observations of one checkout merge stronger metadata and latest
    recency while distinct clones remain distinct;
27. nested and duplicate scan roots are removed before filesystem walking;
28. repository discovery can be scoped to the authenticated GitHub owner;
29. cache entries are rebuilt from live Git metadata and reject another owner's
    explicitly scoped cache;
30. future-dated and malformed cache files are treated as stale/missing;
31. cache writes use replace semantics and clean temporary files on failure;
32. repository selection is persisted immediately, including authenticated-owner
    scope, and failure is reported separately from session-only selection;
33. repository lookup/discovery/cache failures fail closed instead of showing an
    unvalidated path;
34. the terminal repository menu uses the same owner-scoped discovery and cache
    semantics as the Textual picker;
35. settings mutations refresh the in-memory snapshot before a subsequent launch,
    preventing stale profile/model state from being resurrected.
36. the Models provider filter includes configured/usable providers before their
    first model discovery, and a selected provider with no cached rows receives
    an actionable refresh message instead of disappearing or showing a generic
    empty state.
37. the minimum 80x18 terminal keeps every Models action hitbox inside the main
    viewport, preserves the compact active/free count summary, and exposes a
    visible Providers-page Refresh action;
38. compact help text retains the custom-provider editor controls instead of
    clipping them below the modal, and the installed `fcc-tui` launcher uses an
    existing checkout release binary before falling back to Cargo.

## Recovery and validation

The repository picker now marks recency only after canonical deduplication. A
successful write is reported as the next-launch default; an `OSError` leaves the
selection active for the current session but emits a warning that the cache could
not be written. A failed scan does not replace a known inventory with an empty
cache or reinsert an unvalidated selected path. Discovery is GitHub-only whether
or not the local CLI identity can be read, and linked worktrees are excluded.

Focused validation covers repository persistence/deduplication, terminal and
Textual failure recovery, model filtering/editor state, polling, launch errors,
and curses boundaries. The full local CI command remains the release gate; live
GitHub Actions and external UI confirmation are separate evidence states and are
not claimed by local tests.

## Residual risks

No known defect remains in the covered 80x18, 80x24, and 160x50 local TUI
paths. A real macOS session is still required to confirm visual layout at every
other terminal size and the behavior of external GitHub authentication/remote
probes. Distinct local clones of the same GitHub repository are intentionally
retained because they are different launchable checkouts; they are not duplicate
rows for the same path.

## PR #210 native control center audit

The native Ratatui client consumes the existing loopback Admin API for provider
inventory, masked API-key state, model catalog/evidence, routing assignments,
custom-provider CRUD, local-provider status, usage, and diagnostics. It keeps
cataloged-but-not-routable models visible with an explicit policy status while
allowing assignment only for models currently admitted by FCC. Blank configured
API-key and proxy editors omit those fields on update so the backend preserves
the existing credential; explicit secret clearing remains a separate confirmed
action.

The native frontend was also exercised across all pages and modal types at the
160x50 reference viewport and an 80x24 compact viewport. The release binary was
run against the real loopback server; the live Models page defaults to active rows,
the provider modal shows B.AI and OpenRouter as separate lanes, and `Free only`
shows only explicit free-price evidence. Model selection is frontend-local until
the selected model is assigned from Routing, which is the only page exposing the
Default/Fable/Opus/Sonnet/Haiku assignment actions. A PTY-compatible startup path
avoids a cursor position query during alternate-screen setup because some local
terminal wrappers do not answer that query.

## 2026-09-01 — restored Textual default and configured-provider discovery (superseded)

At this intermediate checkpoint, the default `fcc-server` surface was the
restored mouse-first Textual control center. This checkpoint was superseded by
the supplied donor replacement recorded below: the native Rust/Ratatui client
is now the default `fcc-server` surface, with `fcc-tui` attaching to the same
frontend. The repository filtering contract described here remains current:
only real GitHub-backed checkout folders are listed and linked worktrees are
excluded.

The live model refresh exposed a policy defect: configured NVIDIA NIM, OpenCode
Zen, and OpenCode Go providers were present in the runtime but their model-list
requests were blocked before network I/O because the session guard admitted only
the primary provider and custom lanes. Session policy composition now admits
configured remote provider lanes individually. Disabled custom providers and
unconfigured built-ins remain excluded, and the existing forbidden-provider
families remain blocked.

The exact NVIDIA route is `nvidia_nim/moonshotai/kimi-k3`. The persisted NVIDIA
legacy allowlist includes the raw `moonshotai/kimi-k3` ID, and the separate Cline
lane also has `moonshotai/kimi-k3`; B.AI remains independently addressable as
`bai/glm-5.3-flash` and `bai/deepseek-v4-flash`, and Cline's GLM route remains
`cline/z-ai/glm-5.3-flash`. No provider identity is inferred from the upstream
model namespace. The restored GUI removes the fake window-control dots and
misleading header placeholder.

Validation for this recovery includes the session-policy regression suite,
focused GUI/model-editor tests, editable installation, a fresh headless
`fcc-server` health check, and a live Admin model refresh with zero failed
providers. The refreshed catalog returned 1,000 rows; the installed GUI's
NVIDIA + Free-only + `kimi k3` filters narrowed to exactly
`nvidia_nim/moonshotai/kimi-k3`, and its inspector displayed the exact route.
Provider/API-key status remained masked/configured; secrets were not read back
or logged. The remaining acceptance boundary at that checkpoint was user
visual confirmation of the restored Textual window.

## 2026-09-01 — donor native catalog UI replacement

The supplied `AgentSwitchboard-tui.zip` is the donor artifact for the native
catalog control center. Its bundled `tui-demo/fcc-control-center` is a Linux
ELF demo binary and is not installed on macOS; the source was recovered from
the matching `cursor/native-tui-gui-models-2455` commit instead.

The donor Rust/Ratatui frontend is now the foreground `fcc-server` surface and
the `fcc-tui` attach surface. It owns no provider registry or secret store. In
live attach mode, model/provider/config mutations still go through the loopback
Admin API. On a cold start, the prelaunch TUI writes a private result handoff
that the Python owner validates and commits before the server exists.
The existing Textual implementation remains in the checkout as compatibility
code, but is no longer selected by the server launcher.

Validation after the replacement included Rust formatting, 24 native unit/UI
tests, and an optimized macOS release build. The donor Models page was checked
against the live loopback catalog for exact provider/model identity, separate
B.AI/Cline/NVIDIA filters, explicit free-price filtering, catalog-vs-active
visibility, pending enable/default changes, and Admin read-back save behavior.
The editable FCC installation was refreshed to 4.64.0 and the installed
release binary was rebuilt from this checkout.

Residual boundary: the donor zip's Linux executable is not a valid macOS
artifact, and a per-model generation canary remains separate from catalog
discovery/route diagnostics. Do not treat the donor fixture's mock server as
live provider evidence.

## 2026-09-01 — donor replacement final acceptance

The replacement was rebuilt from the local canonical checkout and installed
editable as `free-claude-code 4.64.0`. The native surface now starts with the
active/routable model set, exposes the full cache only through `Show catalog`,
keeps `Disable all` separate from the explicit `MODEL` route, and moves tier
assignment to the Routing page. Provider chips are based on configured
provider inventory as well as cached model rows, so an independently
registered B.AI, Cline, or NVIDIA NIM provider remains findable.

Final local evidence: 28 native Rust tests, optimized release build, Rust
formatting, and Clippy passed; the Python gate passed with 3,837 tests plus
Ruff and `ty`; fresh PTYs opened both `fcc-tui` and installed `fcc-server` at
80x24; loopback health and Admin provider/model checks were healthy with no
failed providers; and repository discovery returned 36 real folders with no
linked-worktree or missing-path rows. API-key values were not read or logged.

The local working tree remains intentionally dirty and unpublished. The donor
zip's bundled Linux binary is not macOS runtime evidence, and a per-model
generation canary remains a separate follow-up.

## 2026-09-01 — native repository handoff and finite navigation

The native replacement now includes a visible Repositories page. Its rows come
from the core GitHub-backed inventory boundary, which revalidates cached paths
against live Git metadata and omits linked worktrees, non-GitHub remotes, and
stale folders. `Enter`/`Use selected` persists the chosen checkout; `C` or
`Launch Claude` starts in that checkout's working directory. The standalone
`fcc-repos` picker remains available and uses the same filtering contract.

The model/provider/field lists now clamp at their first and last rows instead
of wrapping around indefinitely. Final evidence after the server restart was
30 native tests, 3,839 safe Python tests, full Ruff/`ty`, import-boundary and
focused Admin/picker checks, optimized release build, and fresh 80x24 PTYs for
both installed native entrypoints. The loopback repository endpoint returned
36 real GitHub checkout folders with no linked-worktree or missing-path rows.

Residual boundary: B.AI price metadata is still unknown and is not mislabeled
free; the donor zip's Linux demo binary is not macOS runtime evidence; and
per-model generation success is not implied by catalog discovery.

## 2026-09-01 — provider-first model picker and settings boundary

The remaining screenshot defects were caused by treating the catalog as the
primary navigation surface and mixing three different concerns into one page:
provider registration, model access, and routing assignment. The native client
now derives its provider picker from the sanitized registered-provider inventory,
keeps missing-key providers out of the selectable cache, and shows each
registered lane separately with its model/free-evidence counts. `Free only` is
evidence-based: unknown B.AI pricing stays unknown instead of being guessed.

Models uses finite selection. A plain click only changes the inspected model;
Shift/Ctrl/Option/Command-click changes its pending access state. The explicit
`Disable all` action clears the curated access set while preserving the chosen
`MODEL` route, and disabling that route requires using another active model first.
Routing assignment buttons exist only on Routing. Provider credentials, endpoints,
proxies, and custom-provider registration fields exist only on Providers; App
Settings contains runtime/application controls and no provider-registration fields.

Validation after the final rebuild/install was 33 native tests, format check,
Clippy, optimized release build, and a fresh 80x24 installed PTY. The PTY
confirmed the finite provider list and the wrapped B.AI/Free-only empty state;
live FCC health and sanitized Admin model/provider checks were also healthy.
