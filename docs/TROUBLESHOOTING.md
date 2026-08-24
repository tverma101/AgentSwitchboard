# Harness troubleshooting

Use the terminal evidence first. This fork does not open a browser as part of
server or launcher startup.

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

## Compact or resume fails

Keep the client context cap within the supported range and retry with a normal
multi-turn conversation. A single huge message is not a valid compaction proof;
Claude requires enough distinct conversation groups before `/compact` can run.
The release receipt requires an actual compact success/boundary event and a
continuation marker. The global context policy is advisory, while the launcher
context cap is the enforced client budget.

## Provider authentication or usage limit failures

Confirm the credential and exact model in `~/.fcc/.env`, restart `fcc-server`,
and inspect the terminal/server receipt. A provider HTTP error or usage limit is
not evidence that FCC silently switched providers. Do not enable a fallback
route unless it is explicitly configured and its provider boundary is understood.

## Inspect installed versions

```bash
fcc-server --version
fcc-claude --version
command -v fcc-server fccdanger fcc-claude
```

If an old executable is selected, refresh the editable uv tool installation and
verify the resolved command path before testing again.
