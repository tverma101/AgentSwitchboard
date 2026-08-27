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
Each quality matrix job exact-syncs a shared warm environment at:

```text
$HOME/.cache/harness-actions/venvs/${RUNNER_OS}-${RUNNER_ARCH}-py314
```

The checks use `uv run --no-sync` after that sync, avoiding repeated dependency
resolution and virtual-environment setup across the serial matrix jobs.
Hosted fallback remains correct without this optional cache.

The local Python entrypoints set descriptive operating-system process titles via
`setproctitle`. Activity Monitor should therefore show names such as `Harness
Server`, `Harness Desktop`, and `Harness CI pytest [gw0]` instead of treating
every FCC or xdist process as an anonymous Python 3.14 process. xdist workers
remain separate processes so their CPU and memory still need to be summed when
measuring a test job; this change labels the work and does not hide or merge
resource usage. External Node-based clients keep their own process names.

On the current 4-performance-core/6-efficiency-core Apple Silicon runner, the
pytest job sets `PYTEST_XDIST_AUTO_NUM_WORKERS=6`. This uses pytest-xdist's
supported auto-worker override and was measured against this repository's full
suite; the default ten-worker setting was slower. The workflow keeps xdist's
default `load` scheduler because this suite's local `worksteal` benchmark was
slower.

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

## Emergency Codespaces burst runner

The repository `tverma101/Rumple` is the minimal Codespaces host for emergency
compute when the Mac runner is overloaded or slow. Its checked-in devcontainer
is derived from the
[Pwd9000-ML GitHub Actions Runner template](https://github.com/Pwd9000-ML/devcontainer-templates/tree/main/src/github-actions-runner-devcontainer)
version `1.0.3`. It registers against `tverma101/Harness` with the
`harness-burst` and `rumple` labels.

Run an explicit burst from a pushed Harness branch:

```sh
fcc burst --ref fix/my-branch
```

If a burst needs to be stopped independently, run:

```sh
fcc burst stop
```

The command reuses or creates a Rumple Codespace, defaults to GitHub's
`basicLinux32gb` machine (2 cores, 8 GB RAM), waits for the runner, dispatches
the `CI` workflow with `harness-burst`, watches every matrix job, and stops the
Codespace even when the run fails. It uses GitHub's Codespaces REST start API
because some installed GitHub CLI versions do not provide `gh codespace
start`.

Configure the `GH_OWNER`, `GH_REPOSITORY`, and `GH_TOKEN` Codespaces secrets in
Rumple before the first launch. The token is never stored in either repository.

The workflow's normal push and pull-request behavior is unchanged: the
repository's existing `HARNESS_RUNNER` setting continues to control trusted
work, and fork pull requests remain on `ubuntu-latest`. The burst command does
not modify that setting; only an explicit workflow dispatch can select
`harness-burst`.

## Local runner operations

The runner is registered only for `tverma101/Harness`, with the custom label
`harness-local`. It runs as the user LaunchAgent
`com.tverma101.harness-actions-runner` and keeps its warm workspace and
toolchain caches outside the repository checkout.

Each quality job exact-syncs and then reuses the Harness environment at:

```text
$HOME/.cache/harness-actions/venvs/${RUNNER_OS}-${RUNNER_ARCH}-py314
```

The checks use `uv run --no-sync` after that sync, avoiding repeated dependency
resolution and virtual-environment creation across the serial matrix jobs.

The LaunchAgent is enabled with `RunAtLoad` and `KeepAlive`: it starts when
the user’s macOS GUI session begins after a restart and respawns the runner if
the listener exits. It is intentionally a user LaunchAgent rather than a
pre-login system daemon because the runner uses this user’s credentials.

Keep the LaunchAgent's process type as `Interactive`; GitHub's macOS runner
template uses that type so the persistent runner is not treated as a constrained
background service.

The runner application should be kept current. In particular, runner 2.336.0
has open macOS ARM64 reports of process-spawn and finalization hangs; verify
the installed version after runner updates and do not leave a known-bad
version in service when a newer release is available.

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
