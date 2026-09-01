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

No known residual defect remains in the covered local TUI paths. A real macOS
session is still required to confirm visual layout at every terminal size and
the behavior of external GitHub authentication/remote probes. Distinct local
clones of the same GitHub repository are intentionally retained because they are
different launchable checkouts; they are not duplicate rows for the same path.

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
