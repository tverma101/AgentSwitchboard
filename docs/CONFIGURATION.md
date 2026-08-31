# AgentSwitchboard configuration

This is the configuration reference for the terminal-only AgentSwitchboard
release. The server reads the repository `.env` first, then the managed user file
`~/.fcc/.env`, and finally an explicitly selected `FCC_ENV_FILE` when set.
Later files override earlier files. Keep credentials in the managed file or an
explicit private file; do not commit them.

The `fcc*` commands, `FCC_*` environment variables, and `~/.fcc` paths are the
current legacy compatibility surface. They remain documented so existing
installations continue to work while AgentSwitchboard's public namespace is
migrated separately.

## Minimal OpenCode Go / Muse setup

```dotenv
OPENCODE_API_KEY=your-opencode-key
MODEL=opencode_go/muse-spark-1.2-contributor
ANTHROPIC_AUTH_TOKEN=freecc
FCC_CLAUDE_CONTEXT_TOKENS=256000
REASONING_POLICY=client
```

Start the server in a terminal:

```bash
fcc-server
```

The command opens the terminal control center. Press Enter/C for `fcc-claude`,
D for `fccdanger`, O to select a cached/local repository, or F to select/manage
the profile used by the next launch. F also exposes explicit selective bundle
preview/export/import. P opens provider status and FCC account actions; its custom-provider
path supports add, edit, test, enable/disable, and remove through the
canonical Admin API. M shows models and opens a shared filterable picker for
an explicit model change, U shows local usage, N runs route diagnostics, X
explains the independent Codex Tool Account surface, S edits the supported Model and Reasoning Policy fields, L
previews/filters the structured server log, R restarts only a server owned by
this terminal, and Q exits. If FCC is already healthy, the control center
attaches without claiming its lifecycle. Use `fcc-server --headless` for a
blocking server-only process.

The home redraw is local-only. Admin, provider, model, usage, and diagnostic
requests happen only after selecting their explicit action.

You can also run the terminal client from another terminal:

```bash
fccdanger
```

`fccdanger` is a convenience launcher for `fcc-claude` that adds
`--dangerously-skip-permissions` exactly once. It still targets the local FCC
gateway. If the gateway is unavailable, it exits with a terminal instruction to
start `fcc-server`; it does not open a browser.

## Provider and model values

`MODEL` and the optional tier overrides use the exact form
`provider_id/model_id`. The provider catalog is the source of truth for
provider IDs. Current OpenCode Go examples include:

```dotenv
MODEL=opencode_go/muse-spark-1.2-contributor
MODEL_ALIASES=fast=opencode_go/minimax-m2.7
MODEL_CATALOG_MODE=curated
MODEL_CATALOG_ALLOWLIST=opencode_go/muse-spark-1.2-contributor,opencode_go/minimax-m2.7
OPENCODE_GO_BASE_URL=""
```

Aliases are client-facing names only. Receipts, provider dispatch, and upstream
requests retain the exact provider/model reference. `MODEL_CATALOG_MODE=all`
exposes discovered models; `curated` applies the exact references and wildcard
rules in [model_visibility.py](../src/free_claude_code/config/model_visibility.py).

The provider table and credential names are maintained in
`src/free_claude_code/config/provider_catalog.py` and `.env.example`. Do not
copy a model name from an old screenshot or design document without checking
that source.

`/v1/models` also exposes metadata-only `capability_evidence` and
`catalog_metadata` for discovered models. FCC refreshes the public
`models.dev/api.json` snapshot once per TTL window, stores it at
`~/.fcc/model-metadata-catalog.json`, and enriches all matching discovered
models in memory. The snapshot includes input/output modalities, context and
output limits, display metadata, release/update dates, tool/structured-output
claims, and provenance. It is a metadata source only: it does not authorize a
provider, reveal credentials, or make a hidden model visible to clients.

Set `MODEL_METADATA_CATALOG_ENABLED=false` to disable fetching, or tune
`MODEL_METADATA_CATALOG_TTL_HOURS` between `0.25` and `720`. A catalog outage
leaves provider discovery usable and preserves provider-native metadata.
Provider-native claims take precedence over the public snapshot. Explicitly
unsupported vision metadata remains a preflight rejection; missing or
unconfirmed vision metadata is not treated as a negative claim.

The local Admin Model Config view shows the same evidence for the selected
model, including capability state, confidence, and provenance. A configured
model without cached discovery remains visibly unknown; the panel does not
authorize tools, paid fallback, or provider access.

`OPENCODE_GO_BASE_URL` is optional and defaults to OpenCode Go's documented
endpoint. When set, it is an explicit endpoint override for the configured Go
provider; it is useful for a private gateway or a zero-cost local synthetic
fixture. The strict provider policy still attributes the request to
`opencode_go` and does not enable another provider family.

## Custom OpenAI-compatible providers

The local Admin surface can manage up to eight user-defined OpenAI Chat
Completions endpoints. Open `/admin` only when you explicitly need it, or use
the loopback-only endpoints under `/admin/api/custom-providers`. Changes are
validated and persisted in `CUSTOM_PROVIDERS_JSON`, then require an
`fcc-server` restart so one runtime generation sees one frozen provider
registry.

Each descriptor contains only the supported fields below:

```json
{
  "providers": [
    {
      "id": "local_gateway",
      "display_name": "Local gateway",
      "base_url": "http://127.0.0.1:8000/v1",
      "local": true,
      "models": ["my-model"],
      "enabled": true
    }
  ]
}
```

Remote endpoints must use HTTPS and an API key. Loopback HTTP endpoints may
omit the key, but must be explicitly marked `local: true`; the local/private
classification is checked against the URL rather than trusted from the label.
Optional proxies accept only HTTP(S), SOCKS5, or SOCKS5H URLs. Embedded URL
credentials, query/fragment components, arbitrary headers, plugins, and
transformers are rejected. Explicit `models` are used as a bounded fallback
when model discovery is unavailable.

Keys and proxy URLs are write-only from the Admin API: status responses expose
only whether they are configured. Custom provider setup does not authorize
spend, bypass egress policy, or create a second provider engine. The runtime
uses the existing OpenAI Chat adapter, model cache, routing, and receipts;
receipts contain provider/model metadata rather than credentials.

## Independent FCC and Codex account stores

FCC exposes two deliberately independent account surfaces. The FCC OpenAI/Codex
provider owns `~/.fcc/auth/openai.json`; installed Codex, Computer Use, and
Browser helpers own `$CODEX_HOME/auth.json` and saved snapshots under
`$CODEX_HOME/accounts/profiles`. Logging in or switching one surface never
copies credentials to, logs out of, or replaces the other surface.

The `fcc accounts` command manages the Codex Tool Accounts without changing
FCC's provider OAuth state:

```bash
fcc accounts list
fcc accounts switch <profile>
fcc accounts refresh --all
fcc accounts add <profile>
fcc accounts forget <profile>
```

`add` runs the official Codex sign-in/sign-up flow; add `--device-auth` for
device authorization. API-key environment variables are removed from that
child login environment, and the live `$CODEX_HOME/auth.json` is stashed while
the official flow runs. The manager snapshots the resulting auth under
`$CODEX_HOME/accounts/profiles/<profile>/auth.json` with private file
permissions, keeps normalized credential-free usage data, and uses backend
reported rate-limit durations for labels. Forgetting removes only a local
snapshot and refuses to remove the currently active account; no upstream
logout or token revocation is performed. Switching is local and applies to
new Codex/helper sessions after the documented restart boundary. The Admin
Accounts view exposes the same status, switch, usage, and forget operations;
interactive account addition remains an explicit terminal command so a browser
request cannot silently start or replace a login.

## Context and reasoning

- `FCC_CLAUDE_CONTEXT_TOKENS` defaults to `256000` and accepts `32000` through
  `1000000`.
- `REASONING_POLICY=client` preserves the effort requested by the client.
  `off`, `low`, `medium`, `high`, `xhigh`, and `max` are explicit overrides.
- `fcc-learning context-policy install` adds advisory tool-output discipline to
  the global Claude instructions. It does not replace the launcher context
  cap or provide a hard runtime tool-result governor.
- `FCC_CONTEXT_GOVERNOR_ENABLED` defaults to `true`. At the Messages/Responses
  ingress boundary, oversized text-only `tool_result` content is redirected to
  a local `0600` artifact and replaced with a bounded head/tail locator.
- `FCC_CONTEXT_GOVERNOR_TOOL_RESULT_MAX_BYTES` defaults to `16384` and accepts
  `512` through `1000000`. `FCC_CONTEXT_GOVERNOR_ARTIFACT_DIR` optionally
  selects the private artifact directory; the default is
  `~/.fcc/context-artifacts`. Structured JSON, media, and opaque reasoning
  state are never truncated; oversized values fail explicitly. Redirect
  receipts include byte, line, and estimated-token counts. Retrieve more
  text only through a bounded terminal slice rooted to that directory:

  ```bash
  fcc-learning context-artifact slice /path/from-the-locator.txt \
    --start-line 1 --line-count 80 --max-bytes 16384
  ```

  The command verifies the resolved path stays inside the configured artifact
  directory and reports the full-artifact SHA-256 without placing the full
  artifact back into context.
- FCC's Claude launcher pins the installed executable to the known-good
  `2.1.228` receipt by default. A newer or unparseable binary is quarantined
  before launch; set `FCC_CLAUDE_ALLOW_UNCERTIFIED=1` only for an explicit
  canary. The launcher installs a private absolute
  `CLAUDE_CODE_PROCESS_WRAPPER` under `~/.fcc/bin/` for Claude self-spawns.
  The wrapper preserves arguments/environment, reasserts FCC's local policy,
  and fails closed if proxy auth or the context cap is missing.
  Inspect the current state without launching Claude with
  `fcc-learning claude-compat`.
  Managed Claude sessions (including resume/fork tasks) apply the same
  compatibility check before spawning a child; an uncertified executable exits
  with a typed compatibility failure instead of bypassing the FCC policy.
- Candidate upgrades are evaluated by the neutral
  `free_claude_code.core.claude_candidate` contract using synthetic metadata
  and process results. Candidate assessment is immutable: the explicit
  last-known-good version and route remain active until a caller explicitly
  promotes a certified candidate. Additive metadata is tolerated, while
  changes to an established semantic contract field quarantine the candidate.
  Rollback returns to the preserved last-known-good route. Candidate receipts
  contain only bounded, credential-redacted incompatibility evidence; the
  contract does not update Claude, contact a provider, or mutate user config.
- `/v1/models` exposes explicit reasoning evidence when the provider's model
  catalog supplies it: overall support, individually evidenced effort levels,
  provider default, reasoning-token reporting, visible-summary and opaque-
  continuation behavior, evidence source, and protocol/version fields.
  `accepted-but-unverified` means the provider accepted a request field; it is
  not proof that the model actually reasoned. Generation receipts separately
  record requested effort, provider-reported reasoning tokens, summary/text/
  opaque state, and the Anthropic thinking presentation.
- Provider adapters translate a selected control to the highest documented wire
  value when a provider uses a smaller vocabulary. OpenCode Go accepts `xhigh`
  but not `max`; FCC preserves the client request as `max` and records the
  upstream effective value as `xhigh`. Muse rejects `effort=none`, so an
  explicit `off` request is sent as Muse's lowest supported `minimal` effort;
  FCC still suppresses provider reasoning blocks and records the original
  `off` control in the receipt.

## Routing isolation

FCC owns the Claude gateway variables. Do not put
`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, or `ANTHROPIC_API_KEY` in active
Claude `settings.json` environment blocks, project settings, local settings, or
`--settings` overlays. The Claude launcher checks those sources and fails closed
with the conflicting source/key names. Unrelated settings remain allowed.

For strict OpenCode Go sessions, the configured provider transport is authorized
before network I/O. Forbidden Anthropic/OpenAI/Codex/ChatGPT families are blocked
instead of becoming implicit fallbacks, and each allowed or blocked decision is
recorded as metadata-only `provider.egress.decision` trace evidence. This does
not claim that optional browser, computer-use, or vision helpers are enabled.

Image/document blocks are never silently discarded. Image requests require
confirmed vision metadata; models with explicit non-vision metadata or missing
vision confirmation are rejected at ingress. Provider adapters also fail before
network I/O when their native protocol cannot consume the attachment. Text and
tool requests do not require visual capability metadata. Conflicting explicit
vision claims in a provider model-list response are rejected instead of being
merged permissively; an unclaimed capability remains unknown.
Native Anthropic Messages preserves structured media inside a tool result. The
OpenAI Chat and Responses bridges reject image/document blocks inside
`tool_result` before upstream I/O because their converted tool-output shape is
text-only; this is fail-closed behavior, not silent media loss.

The application also records a deterministic required-capability set for
Messages requests. The strict capability policy is controller-preserving and
has no implicit helper or controller-failover path; smart-local, smart-Go, and
custom helper plans require an explicit helper allowlist and produce separate
metadata-only route receipts. Helper execution is not enabled by the terminal
Muse release path. The server captures the provider/helper policy at generation
and managed-session start. `FCC_PROVIDER_POLICY_MODE` defaults to `strict`,
`FCC_CAPABILITY_ROUTING_MODE` defaults to `strict`, and
`FCC_PAID_FALLBACK` defaults to `false`. `FCC_ALLOWED_HELPERS` accepts
comma- or newline-separated IDs from the explicit startup registry; installed
helpers and unrelated credentials never authorize a route. Changes to these
four values require a server restart so existing sessions keep one policy for
their full lifetime. The terminal control center's `P` command prints the
live metadata-only policy and egress receipt.

Provider fault-attribution receipts also record `duration_ms` and
`time_to_first_token_ms` when a provider stream is attempted. The first is the
logical stream duration (including any retry/backoff); the second is the delay
until the first non-empty streamed output. Either value is `null` when that
measurement is not available. They are metadata-only and do not include prompt,
response, tool, or media payloads. They also record `media_count` and an
ordered `media_type_hash` for image/document blocks, including nested tool
results. See [terminal diagnostics](DIAGNOSTICS.md).

## Local state

| Path | Purpose |
| --- | --- |
| `~/.fcc/.env` | Managed provider and server configuration |
| `~/.fcc/logs/server.log` | FCC server log |
| `~/.fcc/usage.db` | Metadata-only usage ledger |
| `~/.fcc/codex-model-catalog.json` | Generated client-visible model catalog |
| `~/.fcc/learning/` | Local memory, skill, and bounded learning queue state |
| `~/.claude/CLAUDE.md` | Optional managed context-discipline block |

## Terminal-only policy

`fcc-server --terminal` and `fcc-server --no-browser` are accepted explicit
terminal-only flags. Browser-opening flags and the retired presentation
variables are rejected or ignored by design. The `/admin` URL printed at
startup is not an instruction to open a browser; it is a local endpoint for an
explicit client or API request.
