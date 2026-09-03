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

At the time of this earlier checkpoint, no known residual defect remained in
the covered local TUI paths. That statement is historical and is superseded by
the later native audit sections below. A real macOS session is still required
to confirm visual layout at every terminal size and the behavior of external
GitHub authentication/remote probes. Distinct local clones of the same GitHub
repository are intentionally retained because they are different launchable
checkouts; they are not duplicate rows for the same path.

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
run against the real loopback server; the live model page showed the full catalog
and a filtered `openrouter/free` row as routable/free, while the Providers page
showed B.AI as a separate provider. A PTY-compatible startup path avoids a cursor
position query during alternate-screen setup because some local terminal wrappers
do not answer that query.

## 2026-09-03 — native model-picker recovery

### Symptoms

The native Models page opened with a catalog dump, hid the distinction between
active and catalog-only models, exposed routing shortcuts on the wrong page,
showed misleading price metadata, and made bulk enable/disable and exact model
selection difficult. A configured provider with no discovery result could also
look absent.

### Root cause

The page treated the discovery catalog as the primary selection list and used
the same row state for display, routing, and pending policy edits. Provider
metadata was not scoped to the registered provider inventory, and catalog policy
updates were sent as independent fields. The visible footer also advertised a
help modal that did not improve the actual workflow.

### Recovery

The native page now starts with active/routable models, keeps the full cached
catalog behind an explicit View toggle, filters by registered provider and
All/Free-only pricing, and preserves exact provider/model references in the
inspector. Enabled custom-provider model IDs are visible in Catalog before
discovery fills the server cache. Space or Shift/Ctrl-click creates a pending
multi-selection; `Toggle selected` inverts the actual ON/OFF state of those
exact rows and `Disable all` clears the active allowlist in one validated
Admin transaction. Model-policy saves run off the input thread and trigger a
full snapshot refresh before success is shown. `Show catalog` and `Active
only` are explicit page actions. Only Enter/Set MODEL assigns `MODEL`.
Routing shortcuts and the decorative help affordance were removed from Models.

### Validation

Native Rust tests: 48 passed; Clippy with warnings denied: passed; optimized
release build: passed; Rust-TUI Python contract tests: 35 passed; full Python
suite: 3881 passed and 152 skipped. The installed binary was exercised in a
160x50 PTY against the live loopback server: active-only showed 2 rows, Catalog
showed 399 rows, Free-only showed 18 rows, Space selected both active rows, and
the registered B.AI filter displayed an actionable no-cached-model state.

### Residual boundary

The live server snapshot may still have cached model rows for OpenAI, OpenRouter,
and OpenCode Go only; B.AI, Cline, and NVIDIA NIM can be registered/configured
without discovery rows. The native Catalog now supplements that cache from
enabled custom-provider model lists, but refreshing provider discovery and
proving authenticated upstream proxy requests remain separate live provider
evidence. A running old TUI process is not changed by installing a new binary;
the next launch must resolve to the recorded installed release hash.

## 2026-09-03 — remove the editor-workbench shell

The visible native TUI is an AgentSwitchboard control center, not a VS Code
replacement. The render path now draws one direct page-navigation sidebar and
one FCC page surface. It does not draw an activity rail, fake traffic-light
controls, file tabs, Explorer/Search/Source Control destinations, or a
permanent keyboard-help legend. The command palette exposes FCC pages and
actions only; retained path/diff/review flags are CLI conveniences and do not
reintroduce editor chrome.

The page sidebar also owns its keyboard focus now: `Ctrl+0`, `↑↓`/`j`/`k`, and
`Enter` move through and open FCC pages rather than dispatching to a hidden
workspace view. A zero-sized geometry assertion protects the removed tab and
activity regions, and a rendered-shell regression rejects the old labels and
fake controls.

## 2026-09-03 — bounded navigation and dashboard reorganization (superseded shell)

### Symptoms

The native workbench still made finite editor lists feel infinite because
vertical selection wrapped from the last row to the first. The activity rail
also exposed icons without names, and the Dashboard spent most of its space on
generic architecture prose instead of the exact launch route and current
runtime state.

### Recovery

Main page/list navigation now clamps at the first and last row. Page and popup
choice controls retain intentional cycling. Model-only shortcuts and the
model search key require editor focus on the Models page, so sidebar navigation
cannot accidentally change model policy. The Dashboard is a responsive
operational grid showing server/API state, exact `MODEL` and active routes,
model inventory and free counts, provider health, catalog policy, workspace/git
state, pending fields, and normal/danger Claude launch actions. Narrow terminals
collapse the grid into one dense card. The temporary labeled activity rail from
this checkpoint was removed by the direct-shell repair above.

### Validation boundary

Rust unit and render coverage now includes list-edge behavior, focus-gated
model controls, and the concrete Dashboard.
The optimized release was rebuilt and installed at the same SHA256 as the
source artifact. A fresh installed-binary PTY pass at compact and reference
sizes confirmed the Dashboard cards/actions, exact model-route display, and
bounded model cursor. Live provider discovery and
authenticated upstream proxy behavior remain separate evidence from this
UI-only change.

## 2026-09-03 — senior hostile-UI and launch-boundary audit

### Symptoms

The remaining hostile paths were not cosmetic: the provider picker could omit
models explicitly registered on an enabled custom provider, a single modal
click only moved a cursor instead of committing the choice, mouse scrolling a
file viewer silently changed it back to the page surface, edge keys could act
against the wrong focused region, partial refresh errors could be overwritten by
success notices, and a direct launch could start Claude before the user reached
the control center.

### Root cause

The frontend had separate selection and activation semantics for keyboard and
mouse, used discovery cache state as the only custom-provider catalog source,
and treated refresh as an unobservable side effect. The Python owner also
invoked the pending client before handing the terminal to the native frontend,
and did not carry the caller's working directory into that launch.

### Recovery

The native catalog now merges enabled custom-provider model IDs using exact
`provider/model` references and recognizes explicit `:free` IDs across
providers. Modal option clicks activate in one step; modal misses cannot reach
the page below. Mouse and keyboard motion preserve the focused page/file/list,
and Home/End/PageUp/PageDown clamp to the current finite control. Tab and
Shift-Tab now move focus without cycling pages, and collapsing the sidebar
returns focus to the visible page. Page refreshes run in one background task
and apply only when complete, so the TUI remains navigable while discovery is
in flight. Mutation refreshes cancel an older snapshot before applying the
mutation, and refresh success/failure is returned to callers so a partial
snapshot cannot be hidden by a later green notice.
Usage/Diagnostics scrolling uses Ratatui's rendered wrapped-line count, so
long JSON cannot stop early on narrow terminals. Structured Admin error bodies
are preserved but bounded before entering the TUI. Direct `fcc`/`fccdanger`
launches now hold their args, working directory, and original danger intent
until the user chooses Normal or Danger after server readiness.

### Validation boundary

Rust unit/render tests cover the catalog merge, free-ID evidence, provider
filter strictness, modal activation, file-viewer mouse scrolling, finite
navigation, contrast/focus colors, and bounded Admin errors. Python tests cover
pending launch context and the native command boundary. Release build,
installed-binary PTY smoke, and full Python-suite results are recorded in the
turn log for the exact commit; they do not prove authenticated upstream
provider requests or macOS visual confirmation.

### Residual boundary

The native frontend still launches the installed `fcc-claude`/`fccdanger`
commands as a separate child process; proxy/provider behavior remains owned by
the Python backend. Repository discovery remains a separate `fcc-repos` path,
which intentionally excludes linked worktrees and non-GitHub remotes. No
GitHub Actions or PR merge is performed by this audit; the verified topic
branch is the only publication boundary.
