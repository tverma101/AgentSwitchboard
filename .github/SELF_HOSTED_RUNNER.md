# Harness self-hosted CI runner

The main `CI` workflow prefers the repository variable `HARNESS_RUNNER`.
Set it to `harness-local` to use the repository-scoped Apple Silicon runner on
the designated Mac. If the variable is absent, the workflow uses
`ubuntu-latest`.

GitHub does not automatically treat a self-hosted label and a GitHub-hosted
label as an `OR` choice. If the local runner is offline while
`HARNESS_RUNNER=harness-local`, jobs remain queued. To fall back to GitHub's
hosted runner, change the repository Actions variable to:

```text
HARNESS_RUNNER=ubuntu-latest
```

The issue-triggered version validator intentionally remains on
`ubuntu-latest`; it processes untrusted issue content and should not execute on
the persistent Mac runner.

## Local runner operations

The runner is registered only for `tverma101/Harness`, with the custom label
`harness-local`. It runs as the user LaunchAgent
`com.tverma101.harness-actions-runner` and keeps its warm workspace and
toolchain caches outside the repository checkout.

Check service state:

```sh
launchctl print "gui/$(id -u)/com.tverma101.harness-actions-runner"
```

Inspect logs:

```sh
tail -f "$HOME/Library/Logs/harness-actions-runner.log"
tail -f "$HOME/Library/Logs/harness-actions-runner.error.log"
```

Self-hosted runners execute repository code on the Mac. Keep this runner
restricted to trusted/private repository workflows and do not expose it to
untrusted fork jobs.
