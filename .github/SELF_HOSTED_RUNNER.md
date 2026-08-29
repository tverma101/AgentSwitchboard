# AgentSwitchBoard CI runner policy

Every protected CI job runs on GitHub-hosted `ubuntu-latest`. The workflow has
no self-hosted label, runner selector, persistent Mac runner, or Codespaces
fallback. Manual dispatch uses the same hosted runner as push, pull-request,
and merge-group validation.

The historical `fcc burst` path is not part of protected CI and must not be
used to validate or merge this repository. Local validation remains bounded
and serial so it does not compete aggressively with an active workstation.

## Local development observability

Local Python entrypoints set descriptive operating-system process titles via
`setproctitle`. Activity Monitor should identify the AgentSwitchboard server,
desktop, and CI worker instead of treating every FCC process as an anonymous
Python 3.14 process. The default local pytest tier is serial and excludes
subprocess-heavy installer, integration, live, and interactive tests; opt into
those tiers explicitly with `scripts/ci.sh --integration`,
`scripts/ci.sh --installers`, or `scripts/ci.sh --full`.
