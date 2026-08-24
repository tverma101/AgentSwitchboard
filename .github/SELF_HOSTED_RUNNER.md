# Harness self-hosted CI runner

The main `CI` workflow uses the repository variable `HARNESS_RUNNER` for
trusted repository work. Set it to `harness-local` to use the
repository-scoped Apple Silicon runner on the designated Mac. If the variable
is absent, the workflow uses `ubuntu-latest`.

Pull requests from the same repository use the configured runner. Pull
requests from forks always use `ubuntu-latest`, even when `HARNESS_RUNNER` is
set, because their code is not trusted to run on the persistent Mac.

The CI workflow disables `setup-uv`'s GitHub cache archive. The persistent
self-hosted runner retains uv's filesystem cache between jobs, and archiving
that cache in a post-job hook can block the only runner while it is serialized.
Hosted fallback remains correct without this optional cache.

GitHub does not treat a self-hosted label and a GitHub-hosted label as an `OR`
choice. If the local runner is offline while `HARNESS_RUNNER=harness-local`,
jobs remain queued. To use the hosted fallback, change the repository Actions
variable to:

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
