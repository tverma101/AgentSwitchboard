# AgentSwitchboard CI runner policy

The protected `CI` workflow runs push, pull-request, and merge-group checks on
GitHub-hosted `ubuntu-latest` runners. The workflow does not read the legacy
`HARNESS_RUNNER` repository variable, and the persistent Mac runner is not part
of the normal execution path.

The workflow's manual dispatch defaults to `ubuntu-latest`. Its only alternate
label is `harness-burst`, which is reserved for the explicit `fcc burst`
Codespaces path described below. Do not use that path for ordinary pull-request
validation.

## Emergency Codespaces burst runner

The optional `fcc burst` command provisions or reuses a Codespace in
`tverma101/Rumple` and dispatches a workflow run against a pushed branch. The
temporary Codespace runner is an explicit fallback for exceptional capacity
needs; it is not required for protected CI.

```sh
fcc burst --ref fix/my-branch
fcc burst stop
```

The default machine is GitHub's `basicLinux32gb` (2 cores). The command waits
for the temporary `harness-burst` runner, watches the dispatched run, and stops
the Codespace when the run finishes or fails. Configure the `GH_OWNER`,
`GH_REPOSITORY`, and `GH_TOKEN` Codespaces secrets in Rumple before the first
launch. The token is never stored in either repository.

## Local development observability

Local Python entrypoints set descriptive operating-system process titles via
`setproctitle`. Activity Monitor should identify the AgentSwitchboard server,
desktop, and CI worker instead of treating every FCC or xdist process as an
anonymous Python 3.14 process. Existing compatibility installations may still
expose legacy labels until the runtime/packaging migration is completed. xdist
workers remain separate processes, so their CPU and memory still need to be
summed when measuring a local test job.
