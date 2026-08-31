# AgentSwitchboard troubleshooting

Use the terminal evidence first. AgentSwitchboard does not open a browser as
part of server or launcher startup.

## `fccdanger` says the proxy is not reachable

Start the server in another terminal and keep it running:

```bash
fcc-server
```

Then retry `fccdanger`. A healthy startup reports the configured local port and
the terminal-only control endpoint. If the port is already occupied, inspect
the existing process instead of starting a second server:

```bash
lsof -nP -iTCP:8082 -sTCP:LISTEN
curl -fsS http://127.0.0.1:8082/health
```

The expected health response contains `"status":"healthy"`.

## `fcc-server` reports “address already in use”

This normally means an FCC server is already listening. Confirm the process and
health response above. Stop the existing FCC-owned process through its normal
terminal lifecycle before restarting. Do not kill an unrelated process merely
because it owns the port.

## The request appears to use `firstParty` or another provider

Claude Code's client-facing compatibility metadata can say `firstParty`; that
label is not the upstream receipt. Check FCC's local server log and usage
ledger for the provider, protocol, terminal event, and attempt count. For the
verified Muse path, expect `provider=OPENCODE_GO`, `protocol=responses`, a
completed terminal event, and one upstream attempt on the healthy path.

Also check for routing keys in every active Claude settings layer:

```bash
rg -n 'ANTHROPIC_BASE_URL|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_API_KEY' \
  ~/.claude/settings.json .claude/settings.json .claude/settings.local.json
```

The launcher intentionally fails closed when those settings would override FCC.
Remove the conflicting keys or explicitly disable that settings layer.

## Model or alias is rejected

Use an exact provider-qualified value:

```dotenv
MODEL=opencode_go/muse-spark-1.2-contributor
```

Check `src/free_claude_code/config/provider_catalog.py` and
`src/free_claude_code/providers/opencode_go/provider.py` for the current provider
ID and native protocol manifest. Unknown OpenCode Go model protocols fail closed
instead of probing another endpoint.

## Provider reports that the model is unavailable

FCC treats an upstream `Model is unavailable` response as a non-retryable
route problem rather than repeatedly retrying the same request. Select a
currently available provider/model pair in the FCC Models view, save the
profile, restart `fcc-server`, and start a new Claude session. Check the
effective `MODEL` and per-alias model settings in `~/.fcc/.env`; blank alias
overrides intentionally inherit the base `MODEL`, so every Claude alias can
fail together when that base model is unavailable. The error's request ID is
safe to include when inspecting the matching local server receipt.

## Compact or resume fails

Keep the client context cap within the supported range and retry with a normal
multi-turn conversation. FCC launches Claude with an explicit auto-compact
window and a 75% default threshold, while removing inherited `DISABLE_COMPACT`
and `DISABLE_AUTO_COMPACT`, plus the legacy unknown-model wait override.
Provider completion receipts are reconciled to the same governed input estimate
including cache-read and cache-write buckets. Restart `fcc-claude` after
changing the launcher or environment; an already-running Claude process cannot inherit
the corrected boundary. A single huge message is not a valid compaction proof;
Claude requires enough distinct conversation groups before `/compact` can run.
The release receipt requires an actual compact success/boundary event and a
continuation marker. The global context policy is advisory, while the launcher
context cap is the enforced client budget.

## Provider authentication or usage limit failures

Confirm the credential and exact model in `~/.fcc/.env`, restart `fcc-server`,
and inspect the terminal/server receipt. A provider HTTP error or usage limit is
not evidence that FCC silently switched providers. Do not enable a fallback
route unless it is explicitly configured and its provider boundary is understood.

## Usage labels look like native Codex usage

FCC's usage page labels its ledger as `FCC proxy` and shows the ingress API and
account fingerprint for each model row. Native Codex Tool Account usage is a
separate snapshot and is not folded into FCC's proxy ledger. An older usage
database may show `Account not identified` for historical rows; FCC does not
guess an account after the fact. See
[usage attribution](troubleshooting/usage-attribution.md) for the schema and
privacy boundary.

## Inspect installed versions

```bash
fcc-server --version
fcc-claude --version
command -v fcc-server fccdanger fcc-claude
```

If an old executable is selected, refresh the editable uv tool installation and
verify the resolved command path before testing again.

### A subagent appears to use the wrong model

FCC defaults to `FCC_SUBAGENT_MODEL_INHERIT=true`. It records the first
resolved route for a stable Claude session and applies that route to later
logical child-model requests. Confirm that the client sends one of the
supported session headers (`anthropic-session-id`, `x-anthropic-session-id`,
`claude-session-id`, `x-claude-session-id`, or
`x-claude-code-session-id`). Without a session header there is no safe way to
identify the parent, so the request uses the normal `MODEL_*` tier mapping (or
`MODEL` when that tier is unset).

If independent child-tier routing is intentional, set
`FCC_SUBAGENT_MODEL_INHERIT=false` and configure the relevant `MODEL_*` value.
Restart FCC after changing this setting because it is captured per provider
generation.
