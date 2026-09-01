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

The command opens the native Rust/Ratatui control center. Use Tab or
Shift-Tab (or the sidebar with the mouse) to move between Dashboard, Providers,
Models, Routing, Context, Local Setup, Settings, Usage, and Diagnostics. `R`
refreshes the current server snapshot; `C` launches `fcc-claude`; `!` launches
`fccdanger`; and `Q` exits. Providers support status, tests, connected-account
actions, and custom-provider CRUD. Models show the complete catalog plus
routable status; `/` filters and `D/F/O/S/H` assign the selected routable model
to the default or Claude tier route. Settings and local/provider fields use
the canonical Admin API, and blank configured secret/proxy edits preserve the
existing value. If FCC is already healthy, the control center attaches without
claiming its lifecycle. Use `fcc-tui` from another terminal to attach directly,
or `fcc-server --headless` for a blocking server-only process.

Repository selection is a separate `fcc-repos` picker. It shows existing local
checkout folders only when their live Git metadata has a configured GitHub
remote, excludes linked worktrees, and does not require GitHub CLI login. Use
`fcc-repos --refresh --root ~/src` to rescan a specific root.

The native shell loads one server snapshot at startup and does not re-query on
every redraw. Press `R` when an updated provider/model/usage/diagnostic snapshot
is needed; mutations and diagnostics remain explicit Admin API actions.

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
BAI_API_KEY=""
BAI_BASE_URL="https://api.b.ai/v1"
```

Aliases are client-facing names only. Receipts, provider dispatch, and upstream
requests retain the exact provider/model reference. `MODEL_CATALOG_MODE=all`
exposes discovered models; `curated` applies the exact references and wildcard
rules in [model_visibility.py](../src/free_claude_code/config/model_visibility.py).

The loopback Admin model picker keeps the full cached discovery inventory
separate from the client-visible list. It never treats every discovered model
as user-selected: checkboxes are pending selections for the explicit
allowlist, and `Enable selected`/`Disable selected` change only those rows.
`Disable all` writes an empty curated allowlist while retaining the cached
inventory, so disabled discoveries remain available to search and re-enable.
Search and price/provider filters operate on that in-memory inventory without
re-querying providers; use the page's `Refresh` action when a new discovery
snapshot is wanted. The same response carries a sanitized provider-status
inventory, so a registered provider remains visible in the filter before its
first discovery completes and its empty state points to `Refresh`.
The Models page also provides `Free first`, `Free only`, and `All prices`
views. Free/paid state comes from explicit provider or catalog pricing; an
OpenRouter `:free` variant is the narrow fallback when no price map is
available. Missing pricing stays unknown and is never treated as free. These
views only filter or order the display; they do not enable models or change
the allowlist.

B.AI uses `BAI_API_KEY` and the OpenAI-compatible `https://api.b.ai/v1`
endpoint. Its `/v1/models` response is the source of truth for exact model
IDs. B.AI may return model IDs without optional pricing or capability fields;
those models remain `PRICE?`/unknown and are excluded from `Free only` until
explicit zero-price or `is_free` metadata is available. Current promotional
offers are not hardcoded because they can expire or vary by eligibility.

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
claims, pricing/free-state metadata, and provenance. It is a metadata source
only: it does not authorize a provider, reveal credentials, or make a hidden
model visible to clients.

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
- `fcc-claude` sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to FCC's bounded context window (`256000`
  by default). FCC does not inject a default `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`;
  Claude Code owns its internal compaction reserve and trigger inside that
  window. An explicit user-supplied percentage override is preserved. FCC
  removes inherited `DISABLE_COMPACT` and `DISABLE_AUTO_COMPACT`, and does not
  disable Claude Code's unknown-model compaction safety path.
- `fcc-claude` supplies Claude Code's `MAX_MCP_OUTPUT_TOKENS=12000` by
  default, unless that public Claude setting is already present in the
  environment. An explicit value is preserved so a user-owned MCP server can
  opt into a different result budget.
- `fcc-claude` supplies Claude Code's `ENABLE_TOOL_SEARCH=true` by default so
  MCP definitions are deferred from the client's rendered context. An
  explicit `false`, `auto`, or `auto:N` value is preserved. FCC removes only
  Anthropic's search-controller definitions and reference blocks before
  OpenAI-compatible provider conversion; every ordinary named MCP tool stays
  available for direct calls.
- `REASONING_POLICY=client` preserves the effort requested by the client.
  `off`, `low`, `medium`, `high`, `xhigh`, and `max` are explicit overrides.
- `fcc-learning context-policy install` adds advisory tool-output discipline to
  the global Claude instructions. It does not replace the launcher context
  cap or provide a hard runtime tool-result governor.
- `FCC_CONTEXT_GOVERNOR_ENABLED` defaults to `true`. At the Messages/Responses
  ingress boundary, oversized text-only `tool_result` content is redirected to
  a local `0600` artifact and replaced with a bounded head/tail locator.
- `FCC_CONTEXT_GOVERNOR_PRESERVE_MEDIA` defaults to `true`. After model
  routing and visual-capability validation, complete image/document blocks are
  preserved for vision-capable routes. Unknown capability metadata is also
  preserved so FCC does not destroy an image before the provider can decide;
  an explicit non-vision model is rejected before provider I/O.
- `FCC_CONTEXT_GOVERNOR_TOOL_RESULT_MAX_BYTES` defaults to `16384` and accepts
  `512` through `1000000`. `FCC_CONTEXT_GOVERNOR_ARTIFACT_DIR` optionally
  selects the private artifact directory; the default is
  `~/.fcc/context-artifacts`. Complete media blocks and opaque reasoning state
  are never truncated when media preservation is enabled. If a tool result
  contains only direct text and media blocks, oversized direct text is
  redirected while the media remains intact; arbitrary oversized structured
  values still fail explicitly. Redirect receipts include byte, line, and
  estimated-token counts. The same governance runs before
  `/v1/messages/count_tokens`, keeping the context estimate aligned with the
  governed `/v1/messages` payload. Retrieve more
  text only through a bounded terminal slice rooted to that directory:

  ```bash
  fcc-learning context-artifact slice /path/from-the-locator.txt \
    --start-line 1 --line-count 80 --max-bytes 16384
  ```

  The command verifies the resolved path stays inside the configured artifact
  directory and reports the full-artifact SHA-256 without placing the full
  artifact back into context.

  Repeated token-count probes reuse bounded in-process estimates. Fingerprinting
  and tokenization are capped at two concurrent probes so large Computer Use
  screenshots cannot fan out into unbounded CPU work.
  Provider completion receipts use the same governed input estimate and
  reconcile input, cache-read, and cache-write buckets so gateway-specific
  usage denominators cannot inflate the Claude context meter.
- FCC's Claude launcher pins the installed executable to the known-good
  `2.1.228` receipt by default. A newer or unparseable binary is quarantined
  before launch. After a version quarantine, FCC first checks
  `FCC_CLAUDE_KNOWN_GOOD_BINARY`, PATH, and its private versioned install. If
  no exact known-good executable is present, it may restore that exact version
  from npm's local offline cache without changing the global `claude` command.
  `FCC_CLAUDE_KNOWN_GOOD_BINARY` may point to an existing exact executable.
  Set `FCC_CLAUDE_ALLOW_UNCERTIFIED=1` only for an explicit canary. The
  launcher installs a private absolute
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

Image/document blocks are never silently discarded. Image requests with
explicit non-vision metadata are rejected at ingress. Vision-capable and
unknown routes preserve the complete media block; provider adapters still fail
before network I/O when their native protocol cannot consume the attachment.
Text and tool requests do not require visual capability metadata. Conflicting
explicit vision claims in a provider model-list response are rejected instead
of being merged permissively; an unclaimed capability remains unknown.
Native Anthropic Messages preserves structured media inside a tool result. The
OpenAI Chat bridge still rejects image/document blocks inside `tool_result`
before upstream I/O because its converted tool-output shape is text-only. The
Responses bridge preserves supported Anthropic image blocks as native
`function_call_output.output` content parts (`input_text`/`input_image`), so
Computer Use screenshots reach a vision-capable model without flattening or
truncation. Unsupported nested media shapes and document sources still fail
closed before upstream I/O rather than being silently serialized as text.

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

`FCC_COMPUTER_USE_APPROVAL` controls the native Codex app-access form used by
the Computer Use bridge. It defaults to `auto`, but the MCP process accepts the
form only when `codex-computer-use` is also present in `FCC_ALLOWED_HELPERS`.
Set it to `decline` to keep native app access fail-closed. This setting is
captured at server/session startup and requires a restart.

When `codex-computer-use` is explicitly allow-listed, `fcc-claude` validates
the signed Codex Computer Use installation, exposes the official Computer Use
skill through the active `CLAUDE_CONFIG_DIR`, and registers the fixed
`fcc-codex-computer-use` stdio MCP name to the Python FCC module
(`free_claude_code.cli.codex_computer_use_mcp`) before starting Claude. The
server launches the signed Codex `app-server`, configures the official bundled
Computer Use plugin launcher, waits for the ten native tools, preserves native
JSON-RPC results including screenshots, and handles the app-access elicitation
handshake. Read-only list/state calls can recover once from a lost native
connection; mutating calls are never replayed after an uncertain result.
Registration is idempotent, migrates FCC-owned raw-bridge/direct-launcher
entries, and refuses to overwrite a different user or project entry. The
native host remains lazy and starts only when Claude calls a Computer Use tool;
launch setup does not capture the screen. If setup fails, the launch is blocked
with the reason and exact config/project locations instead of returning an
unexplained status code.

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
| `~/.fcc/usage.db` | Metadata-only FCC proxy usage ledger with provider/model, wire-API, source, and privacy-preserving account labels |
| `~/.fcc/codex-model-catalog.json` | Generated client-visible model catalog |
| `~/.fcc/learning/` | Local memory, skill, and bounded learning queue state |
| `~/.claude/CLAUDE.md` | Optional managed context-discipline block |

## Terminal-only policy

`fcc-server --terminal` and `fcc-server --no-browser` are accepted explicit
terminal-only flags. Browser-opening flags and the retired presentation
variables are rejected or ignored by design. The `/admin` URL printed at
startup is not an instruction to open a browser; it is a local endpoint for an
explicit client or API request.

### Parent model inheritance for subagents

`FCC_SUBAGENT_MODEL_INHERIT=true` is the safe default. Claude Code can use a
different logical model name for a child agent, but FCC keeps that child on the
parent request's resolved provider/model when the client supplies a stable
session header. The retained route is bounded and scoped to the active
provider generation, so a configuration restart cannot reuse an old route.

The first logical parent request still uses its matching `MODEL_*` mapping. If
a client does not send a session header, later logical model names use that
normal tier resolution because FCC cannot identify the parent safely. Set
`FCC_SUBAGENT_MODEL_INHERIT=false` only to deliberately let a child use its
independent `MODEL_FABLE`, `MODEL_OPUS`, `MODEL_SONNET`, or `MODEL_HAIKU`
mapping even when a parent route is available. Direct `provider/model` requests
and configured model aliases remain explicit overrides.
