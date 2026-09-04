# AgentSwitchboard configuration

This is the configuration reference for the local AgentSwitchboard release. The
server reads the repository `.env` first, then the managed user file
`~/.fcc/.env`, and finally an explicitly selected `FCC_ENV_FILE` when set.
Later files override earlier files. Keep credentials in the managed file or an
explicit private file; do not commit them.

The `fcc*` commands, `FCC_*` environment variables, and `~/.fcc` paths are the
current legacy compatibility surface. They remain documented so existing
installations continue to work while AgentSwitchboard's public namespace is
migrated separately.

## Sandboxed test server

`t-fcc-server` starts the same server as `fcc-server` but fully isolated from
your live installation, so branch changes and configuration experiments cannot
touch it:

- State directory: `~/.fcc-sandbox` (override with `FCC_SANDBOX_DIR`).
- Port: `8083` unless `PORT` is already set (live defaults to `8082`).
- On first start it copies `~/.fcc/.env` into the sandbox so real providers
  work; after that the two files are independent — changes made through the
  sandbox admin UI stay in the sandbox.
- It does not copy FCC-owned ChatGPT credentials. To use an `openai/...` route,
  connect the account in the sandbox Admin UI at
  `http://127.0.0.1:8083/admin`; credentials are stored under the sandbox
  state's `auth/openai.json`, not reused from `~/.fcc/auth/openai.json`.
- The sandbox enables local A3S web search and local web tools by default. This
  is experimental and is used only when `a3s-search` is installed; live
  `fcc-server` keeps A3S disabled unless `ENABLE_LOCAL_A3S_SEARCH=true` is set.
  Install the optional backend with `cargo install a3s-search`.
- A3S runs with the explicit HTTP/RSS engines `ddg,wiki,bing`. If it is absent,
  unavailable, or returns invalid output, FCC falls back to its existing
  Firecrawl and DuckDuckGo search backends.

Run both servers at once to compare behavior, then apply whatever you want to
keep to the live configuration manually. The whole state root can also be
redirected for any command with `FCC_CONFIG_DIR` (used by `t-fcc-server`
internally; it never affects the live `~/.fcc`).

## Minimal OpenCode Go / Muse setup

```dotenv
OPENCODE_API_KEY=your-opencode-key
MODEL=opencode_go/muse-spark-1.2-contributor
ANTHROPIC_AUTH_TOKEN=freecc
REASONING_POLICY=client
```

Start the server in a terminal:

```bash
fcc-server
```

The command opens the native Rust/Ratatui control center. Use Tab or Shift-Tab
(or the sidebar with the mouse) to move between Dashboard, Repositories,
Providers, Models, Routing, Context, Local Setup, App Settings, Usage, and
Diagnostics. The Repositories page shows only live local checkout folders with
configured GitHub remotes; select one with Enter or `Use selected`, then `C` or
`Launch Claude` starts in that checkout. `R` refreshes
the current server snapshot; `C` or `Launch Claude` launches `fcc-claude`; the
visible `Danger launch` button or `!` launches `fccdanger`; and `Q` exits.
Providers support status, tests, connected-account
actions, and custom-provider CRUD. Models is a live catalog browser: `/` filters
the loaded snapshot instantly, `P` opens a finite list of registered providers,
and `F` limits the view to models with explicit FREE evidence. A plain click
selects a row; Shift/Ctrl/Option/Command-click or `Space` toggles its access.
`Enter` or `Use selected` makes the selected exact row the pending active model
(which also enables it), `A` disables the full curated catalog, and `I` switches
between active rows and the full cached catalog. `S` or `Ctrl-S` saves catalog
changes after Admin read-back of
`MODEL`, `MODEL_CATALOG_MODE`, and `MODEL_CATALOG_ALLOWLIST`. Disabled discovered
models stay available through `Show catalog`. Choose a model on Models, then use
the separate Routing page for tier assignments. `App Settings` contains
runtime/app fields only; provider credentials, provider endpoints, proxies, and
custom-provider registration are available only on Providers. All changes still
use the canonical Admin API.
If FCC is already healthy, the control center attaches without claiming its
lifecycle. Use `fcc-tui` from another terminal to attach directly, or
`fcc-server --headless` for a blocking server-only process.

`fcc-tui` also accepts bounded terminal-code-style workspace conveniences:
`[path]`, `--goto <file:line:col>`, `--diff <a> <b>`, `--review`,
`--split/--size`, `--theme`, `--timing`, `--shortcut-setup`, and
`--list-commands`. These are local terminal helpers only: they do not add a
browser/editor shell, and every control-center mutation still stays inside the
native UI and loopback Admin API. `--ssh` and extension-management verbs fail
closed with guidance. See [terminal-code transplant](TERMINAL_CODE_TRANSPLANT.md)
for the verified source pins and verb mapping.

On a cold start, `fcc-server` opens this control center before starting the
HTTP server. Discovery and repository inventory are prepared without a
listener; the Models and Repositories choices are written to a private result
file, validated, and read back by the Python owner. The server starts only
after `Start server` (or `C`/`!` in prelaunch mode) succeeds. `Q` still saves
pending model changes, but exits without starting the server. `fcc-tui` is the
attach-only command for an already-running server.

The direct Claude launchers use the same cold-start boundary. Running
`fcc-claude` or `fccdanger` starts the prelaunch control center when FCC is not
already healthy; the selected model and live GitHub-backed repository are
saved first, then FCC starts, then Claude is launched in that repository.
`fccdanger` keeps its explicit `--dangerously-skip-permissions` mode through
the handoff. If FCC is already healthy, the launcher attaches to that running
gateway and starts Claude directly. This keeps server lifecycle work in the
backend while leaving the user with one normal or dangerous Claude command.

Every built-in provider has a catalog-owned proxy setting, including
`DEEPSEEK_PROXY` and local `OLLAMA_PROXY`; the settings manifest, runtime
configuration, `.env.example`, and provider transport all derive from the same
provider descriptor. NVIDIA Kimi K3 is a provider-specific exception: its
upstream deployment requires immutable `top_p=0.95`, which FCC applies at the
NIM wire boundary for both normal and streamed Claude Messages requests.

The standalone `fcc-repos` picker remains available for shell workflows. It
uses the same live GitHub-remote and linked-worktree rules as the native page,
then launches normal `fcc-claude` in the exact checkout selected. Use
`fcc-repos --refresh --root ~/src` to rescan a specific root.

The native control center loads one server snapshot at startup and does not
re-query on every redraw. Press `R` when an updated provider/model/usage/
diagnostic snapshot is needed; mutations and diagnostics remain explicit Admin
API actions.

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

Manual per-model context windows use `MODEL_CONTEXT_WINDOWS` as JSON mapping
exact refs to tokens:

```dotenv
MODEL_CONTEXT_WINDOWS={"opencode_go/muse-spark-1.2-contributor": 1000000}
```

It applies when a request carries no explicit `[size]` suffix (for example
`MODEL=opencode_go/model[1m]`); an explicit suffix always wins, and inherited
subagent routes keep the parent window. The resolved window is surfaced in
routing diagnostics. Malformed JSON fails settings validation at startup. The native control center's
Context page can edit this map for the exact selected catalog model: choose a
preset, enter a custom value from 32K through 1M tokens, or clear that model's
override. Saved values are applied on the next Claude launch to both
`CLAUDE_CODE_MAX_CONTEXT_TOKENS` and `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; this
controls Claude Code's client context budget and does not create native
Claude Code `ultracode` entitlement or UI state.

The loopback Admin model picker keeps the full cached discovery inventory
separate from the client-visible list. It never treats every discovered model
as user-selected: access changes are pending until `Save`, and `Enable`/`Disable`
change only the selected row. `Disable all` writes an empty curated allowlist
while retaining the cached inventory, so disabled discoveries remain available
to search and re-enable; the explicit `MODEL` route is retained separately.
Search and price/provider filters operate on that in-memory inventory without
re-querying providers; use the page's `Refresh` action when a new discovery
snapshot is wanted. The same response carries a sanitized provider-status
inventory, so a registered provider remains visible in the filter before its
first discovery completes and its empty state points to `Refresh`.
Choose a model on `Models`, then use the separate `Routing` page to assign
`MODEL`, `MODEL_FABLE`, `MODEL_OPUS`, `MODEL_SONNET`, or `MODEL_HAIKU`; routing
buttons are not mixed into the catalog browser.
The Models page provides one explicit `Free only` view. Free/paid state comes
from explicit provider or catalog pricing; an OpenRouter `:free` variant is the
narrow fallback when no price map is available. Missing pricing is omitted from
the FREE view and is never treated as free. The view only filters the display;
it does not enable models or change the allowlist. Rows always show the exact
`provider/model` reference, with the active route and current row shown separately
above the list so a selection is not ambiguous.

The native Models page shows exact `provider/model` rows from the active FCC
inventory, keeps disabled-but-valid catalog rows available to re-enable, and
lets the user choose one registered provider at a time. Missing-key or
unregistered providers are not offered as filter choices even when stale rows
remain in the cached catalog. Model assignment is available from the separate
Routing page after selecting an exact reference on Models; route writes go
through the Admin API only after the explicit action. Disabling the active
route is refused until another model is explicitly used, so the UI never silently
chooses a replacement.
Provider filters keep
B.AI, Cline, and NVIDIA NIM separate; Cline is shown only when its FCC
custom-provider lane is enabled, not merely because the Cline client is
configured to call FCC.

B.AI uses `BAI_API_KEY` and the OpenAI-compatible `https://api.b.ai/v1`
endpoint. Its `/v1/models` response is the source of truth for exact model
IDs. B.AI may return model IDs without optional pricing or capability fields;
those models remain `PRICE?`/unknown and are excluded from `Free only` until
explicit zero-price or `is_free` metadata is available. Current promotional
offers are not hardcoded because they can expire or vary by eligibility.

NVIDIA NIM uses `NVIDIA_NIM_API_KEY` and the OpenAI-compatible
`https://integrate.api.nvidia.com/v1` endpoint. The enabled Kimi K3 route is
`nvidia_nim/moonshotai/kimi-k3`; its provider identity is NVIDIA NIM even though
the upstream model namespace is `moonshotai`. NVIDIA's official model page is
the [Kimi-K3 model card](https://build.nvidia.com/moonshotai/kimi-k3/modelcard).
The current live catalog reports explicit zero-price evidence for this route,
so it appears in `Free only` when the NVIDIA lane is configured and discovery
has completed.

## Cline CLI through local FCC

Cline and B.AI are separate provider lanes. B.AI is the upstream provider
configured in FCC; Cline is a separate provider/service and client harness.
There are two independent paths and they must not be conflated:

1. **Cline client → FCC → B.AI.** The setup below uses Cline's
   Anthropic-compatible client transport to call FCC at
   `http://127.0.0.1:8082/v1`, after which FCC routes to B.AI. It does not
   replace Cline's own `cline` provider or import Cline's hosted catalog into
   this path. Cline stores only the FCC `ANTHROPIC_AUTH_TOKEN` as its API key.
2. **FCC → Cline hosted provider.** An optional FCC custom provider with the
   exact ID `cline` can be registered separately in the Providers page.
   Its base URL is `https://api.cline.bot/api/v1`, its key is the existing
   Cline hosted credential entered write-only, and its model list is the exact
   current Cline model IDs. The free entries keep their `:free` suffix. This
   lane is enabled independently and is admitted by FCC's strict provider
   policy only when the custom provider is enabled.

When both paths are configured, Models shows `B.AI [bai]` and `Cline [cline]`
as separate provider filters. `Free only` recognizes explicit free evidence
and the scoped Cline `:free` convention; it never infers that B.AI is free from
missing pricing. The FCC provider/model reference must always be an exact
route such as `bai/deepseek-v4-flash`,
`cline/z-ai/glm-5.3-flash`, or `cline/moonshotai/kimi-k3`.

For the CLI-only Cline 3.x installation, the supported shortcut is:

```bash
fcc-cline
```

The launcher checks that FCC is healthy, preserves Cline's hosted `cline`
provider, and creates or updates only `providers.anthropic` in
`~/.cline/data/settings/providers.json`. It uses the configured FCC auth token,
local base URL, and exact `MODEL` route. Select another route with
`fcc-cline --fcc-model provider/model`; inspect the target without writing or
launching with `fcc-cline --fcc-dry-run`. A custom Cline `--provider` or
`--model` passed through to the launcher remains authoritative for that run.

The equivalent manual setup is to create or update the Cline provider with the
FCC proxy token:

```bash
cline auth --provider anthropic --apikey "$FCC_PROXY_TOKEN" \
  --modelid bai/deepseek-v4-flash
```

Then set the non-secret provider setting `baseUrl` in
`~/.cline/data/settings/providers.json` to `http://127.0.0.1:8082/v1` under
`providers.anthropic.settings`. Cline's CLI does not accept `--baseurl` for the
Anthropic provider, although the provider runtime supports the custom base
URL. Cline sends `x-api-key`; FCC validates that header against the same proxy
token used by bearer clients. Keep the existing `cline` provider entry; adding
`anthropic` does not replace it. The launcher bridges the Cline CLI only; an
installed Cline editor extension requires its own provider configuration and is
not transparently intercepted by FCC.

Use `MODEL_CATALOG_MODE=all` and the Admin Models `Refresh` action to expose
the complete current discovery inventory to FCC clients. The `Free only`
view remains evidence-based: explicit zero-price or `is_free` metadata is
required, while B.AI models with no pricing metadata remain unknown rather
than being mislabeled as free.

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

Go model protocols are locked to the docs endpoints table (2026-09-02):
Responses (`/responses`) for `grok-4.6`, `gpt-5.6-luna`,
`muse-spark-1.2/1.3-contributor`; Chat (`/chat/completions`) for `glm-*`,
`kimi-*`, `deepseek-*`, `mimo-*`, `longcat-2.0`, `hy*`; Messages (`/messages`,
Anthropic native) for `minimax-*` and `qwen3.*`. Unknown Go models fail closed
without probing billable endpoints. See
`tests/regressions/test_provider_wiring_parity.py` and
`src/free_claude_code/config/model_protocols.py`.

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
  `1000000`. Standard `fcc-claude` retains it only for old config-file
  compatibility and does not forward it to a Claude child process. The
  sandboxed `t-fcc-server` path intentionally forwards it as Claude's bounded
  context and auto-compact window for controlled testing.
- Standard `fcc-claude` does not set `CLAUDE_CODE_MAX_CONTEXT_TOKENS`,
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `MAX_MCP_OUTPUT_TOKENS`, or
  `ENABLE_TOOL_SEARCH`, and it does not remove user-owned compaction flags.
  Claude Code and the user's environment retain ownership of those policies.
- Sandbox sets only the two bounded window variables; MCP/tool-search policy
  and FCC ingress governance remain unchanged and client-owned.
- `FCC_CONTEXT_GOVERNOR_ENABLED` defaults to `false` while the FCC context
  intervention is uncertified. The underlying governor remains available for
  an explicit, separately validated opt-in; when disabled, Messages,
  Responses, and `count_tokens` requests pass through without FCC tool-result
  redirection or media-budget rejection.
- The local `ultracode` reasoning label is shown for every model route and maps
  to FCC's audited provider-neutral `xhigh` effort. It is accepted by both
  standard and sandbox Admin settings; FCC does not send a fabricated literal
  `ultra` value to providers.
- Standard `fcc-claude` launches default the child session to
  `CLAUDE_CODE_EFFORT_LEVEL=xhigh`, the strongest effort value supported by
  Claude Code's remote gateway transport. An explicit `--effort` argument or a
  nonblank `CLAUDE_CODE_EFFORT_LEVEL` value takes precedence. Native Claude Code
  `ultracode` is a separate client-only mode that adds dynamic workflow
  orchestration; FCC's Anthropic-compatible gateway cannot create that mode or
  its thinking-picker state. Native availability remains subject to Claude
  Code's entitlement, configuration, and model capability.
- The remaining governor settings below apply only when the explicitly
  disabled governor is turned on for a bounded experiment.
- `REASONING_POLICY=client` preserves the effort requested by the client.
  `off`, `low`, `medium`, `high`, `xhigh`, and `max` are explicit overrides.
- `fcc-learning context-policy install` is disabled by default and is a no-op,
  so FCC cannot add advisory instructions to the global Claude prompt surface.
  Only an explicitly isolated experiment with
  `FCC_CONTEXT_GOVERNOR_ENABLED=true` can exercise the retained reversible
  writer; `uninstall` remains available for removing an old FCC block.
- `FCC_CONTEXT_GOVERNOR_PRESERVE_MEDIA` defaults to `true` when the underlying
  governor is explicitly enabled. After model routing and visual-capability
  validation, complete image/document blocks are preserved for vision-capable
  routes. Unknown capability metadata is also preserved so FCC does not destroy
  an image before the provider can decide; an explicit non-vision model is
  rejected before provider I/O.
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
  The wrapper preserves arguments/environment, reasserts only FCC's loopback
  gateway discovery setting, and fails closed if the proxy URL or proxy auth is
  missing.
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

Direct `openai/...` requests always route to the ChatGPT/Codex provider and
use the root reasoning policy, independent of tier overrides. Example: with
`MODEL=openai/gpt-5.6-luna`, both `openai/gpt-5.6-luna` (Lite dialect) and
`openai/gpt-5.4` (generic Responses shape) resolve to `provider_id=openai`;
a `claude-3-haiku-*` child in the same session inherits the parent OpenAI
route when inheritance is enabled, preserving Codex thread affinity across
subagents and Claude-owned compaction turns. See
`tests/regressions/test_openai_routing_parity.py` for the locked contract.

Every advertised reasoning-capable model also has a
`claude-3-freecc-ultra/<provider>/<model>` variant that routes identically but
forces FCC's maximum provider-neutral `xhigh` reasoning, selectable from inside
Claude Code's model picker. This is separate from Claude Code's native
`ultracode`, which adds client-side dynamic workflow orchestration. FCC's gateway
can provide the remote `xhigh` effort and this server-side ultra variant, but it
cannot manufacture native ultracode or its thinking-picker state. Claude's own
"Thinking…" renderer remains client-owned and cannot be labeled by the proxy.
Upstream `<summary>...</summary>` thinking tags are stripped into the thinking
channel like `<think>` tags, so a stray `</summary>` can never leak into
visible answers (FCC never emits such tags itself).
