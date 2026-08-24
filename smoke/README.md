# Product E2E Smoke Tests

`smoke/` is local-only. It can launch subprocesses, call real providers, touch
local model servers, and optionally send/delete bot messages. Hermetic contracts
belong under `tests/` and must stay green with plain `uv run pytest`.

## Taxonomy

- `smoke/prereq/`: liveness checks that prove the server, routes, auth, CLI
  scripts, provider pings, local `/models`, and bot permissions are reachable.
  These are prerequisites only.
- `smoke/product/`: end-to-end product scenarios. Feature smoke coverage comes
  from these tests, not from route/header/provider pings.
- `smoke/features.py`: source-of-truth feature map:
  feature -> subfeature -> scenario -> env -> expected behavior -> failure class.

## Required Local Commands

```powershell
uv run pytest smoke --collect-only -q
uv run pytest smoke -n 0 -s --tb=short
```

The second command skips everything unless `FCC_LIVE_SMOKE=1` is set, but still
writes skip entries to `.smoke-results/`.

## Product Smoke Run

```powershell
$env:FCC_LIVE_SMOKE = "1"
uv run pytest smoke -n 0 -s --tb=short
```

Provider smoke scenarios can run providers in parallel while preserving
sequential execution within each provider:

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_TARGETS = "providers"
uv run pytest smoke -n auto --dist=loadgroup -s --tb=short
```

Provider product E2E runs once per configured provider, independent of `MODEL`,
`MODEL_FABLE`, `MODEL_OPUS`, `MODEL_SONNET`, and `MODEL_HAIKU`. Defaults come from the provider
catalog/docs and can be overridden with `FCC_SMOKE_MODEL_<PROVIDER>`, for example
`FCC_SMOKE_MODEL_DEEPSEEK=deepseek-v4-pro` (or `deepseek-v4-flash`). If no provider smoke model is
configured, live product smoke fails as `missing_env` unless you explicitly set
`FCC_ALLOW_NO_PROVIDER_SMOKE=1`.

## Targets

Default targets do not send real bot messages or load voice backends:

| Target | Product scenarios | Required environment |
| --- | --- | --- |
| `api` | messages, count_tokens full payload, errors, `/stop`, optimizations | configured provider only for streaming messages |
| `auth` | canonical bearer auth, conflicting legacy headers, invalid/missing auth | none; test sets an isolated token |
| `cli` | server entrypoint, Claude CLI adaptive thinking, session cleanup | Claude CLI binary and provider only for real CLI |
| `clients` | VS Code and JetBrains protocol payloads | configured provider |
| `config` | env precedence, removed-env migration, proxy/timeouts | none |
| `extensibility` | provider runtime and platform factory construction | none |
| `messaging` | fake Discord/Telegram full flow, literal clear scopes, trees, persistence, voice cancel | none |
| `providers` | multi-turn text, adaptive thinking history, tools, disconnect, errors | configured providers, optional `FCC_SMOKE_MODEL_*` |
| `tools` | forced tool_use and tool_result continuation | tool-capable configured provider |
| `rate_limit` | disconnect cleanup and follow-up request | configured provider |
| `lmstudio` | local `/models` plus OpenAI-chat-backed Messages through proxy | running LM Studio server |
| `llamacpp` | local `/models` plus OpenAI-chat-backed Messages through proxy | running llama-server |
| `ollama` | local `/v1/models` plus OpenAI-chat-backed Messages through proxy | running Ollama server |

The `cli` target also includes the zero-provider thinking characterization
fixture from #55. It launches the literal installed Claude executable through
FCC and serves synthetic Anthropic Messages SSE from a loopback OpenCode Go
endpoint. The fixture records only structural follow-up request receipts and
never calls Anthropic, OpenAI, or OpenCode Go. Run it with:

```bash
FCC_LIVE_SMOKE=1 FCC_SMOKE_TARGETS=cli uv run pytest \
  smoke/product/test_claude_synthetic_thinking_product_live.py -n 0 -s --tb=short
```

The checked-in fixture matrix covers visible summaries and thinking, empty and
usage-only responses, text-only unsupported reasoning, redacted thinking,
interleaved thinking, late/malformed signatures, additive deltas, and plain,
thinking, interleaved, or opaque-state tool continuations. The installed-client
canary runs the client-safe summary, empty, unsupported, usage-only, redacted,
and tool-roundtrip cases; expected client rendering/rejection is recorded in
`.smoke-results/` rather than treated as Muse/provider evidence.

The provider-independent reasoning capability/observability corpus is
[`reasoning-observability-matrix-v1.json`](fixtures/reasoning-observability-matrix-v1.json).
It is synthetic-only: accepted, unsupported, unknown, and skipped capability
rows are not provider-generation receipts, and opaque/empty/tool-order rows do
not claim current Muse behavior. See
[reasoning observability](../docs/REASONING_OBSERVABILITY.md) for the receipt
fields and evidence boundary.

Heavy/side-effectful targets are opt-in:

| Target | Product scenarios | Required environment |
| --- | --- | --- |
| `nvidia_nim_cli` | Claude Code CLI feature matrix across NIM models | `NVIDIA_NIM_API_KEY`, Claude CLI |
| `openrouter_free_cli` | Claude Code CLI feature matrix across OpenRouter free models | `OPENROUTER_API_KEY`, Claude CLI |
| `telegram` | getMe, send, edit, delete, optional manual inbound | token and chat/user ID |
| `discord` | channel access, send, edit, delete, optional manual inbound | token and channel ID |
| `voice` | generated WAV through local Whisper or NVIDIA NIM transcription | `VOICE_NOTE_ENABLED=true`, `FCC_SMOKE_RUN_VOICE=1` |

## Examples

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_PROVIDER_MATRIX = "open_router,nvidia_nim,deepseek,lmstudio,llamacpp,ollama"
uv run pytest smoke/product -n 0 -s --tb=short
```

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_TARGETS = "ollama"
$env:OLLAMA_BASE_URL = "http://localhost:11434"
uv run pytest smoke/prereq smoke/product -n 0 -s --tb=short
```

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_TARGETS = "telegram,discord,voice"
$env:FCC_SMOKE_RUN_VOICE = "1"
uv run pytest smoke/product -n 0 -s --tb=short
```

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_TARGETS = "nvidia_nim_cli"
$env:FCC_SMOKE_NIM_MODELS = "z-ai/glm-5.2,moonshotai/kimi-k2.6,minimaxai/minimax-m2.7,minimaxai/minimax-m3,nvidia/nemotron-3-super-120b-a12b,deepseek-ai/deepseek-v4-pro,deepseek-ai/deepseek-v4-flash"
uv run pytest smoke/product -n 0 -s --tb=short
```

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_TARGETS = "openrouter_free_cli"
$env:FCC_SMOKE_OPENROUTER_FREE_MODELS = "nvidia/nemotron-3-super-120b-a12b:free,openai/gpt-oss-120b:free,poolside/laguna-m.1:free"
uv run pytest smoke/product -n 0 -s --tb=short
```

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_TARGETS = "messaging,config,extensibility"
uv run pytest smoke/product -n 0 -s --tb=short
```

## Environment

- `FCC_ENV_FILE`: explicit dotenv path for startup/config scenarios.
- `FCC_LIVE_SMOKE=1`: enables live smoke execution.
- `FCC_ALLOW_NO_PROVIDER_SMOKE=1`: permits no-provider live smoke for harness work.
- `FCC_SMOKE_TARGETS`: comma-separated targets, or `all`.
- `FCC_SMOKE_PROVIDER_MATRIX`: comma-separated provider prefixes to require.
- `FCC_SMOKE_MODEL_<PROVIDER>`: optional per-provider smoke model override.
  Use the uppercase provider ID, such as `FCC_SMOKE_MODEL_KILO`; the complete
  variable inventory is in [.env.example](../.env.example). Values may include
  the provider prefix or just the model name for that provider.
- `FCC_SMOKE_MODEL_MISTRAL_REASONING`: optional override for the dedicated
  Mistral native reasoning smoke, default `mistral/mistral-medium-3-5`.
- `FCC_SMOKE_NIM_MODELS`: optional comma-separated NVIDIA NIM CLI matrix models
  that replace the default characterization set.
- `FCC_SMOKE_NIM_EXTRA_MODELS`: optional comma-separated NVIDIA NIM CLI matrix
  models appended to the default or replacement set.
- `FCC_SMOKE_OPENROUTER_FREE_MODELS`: optional comma-separated OpenRouter free
  CLI matrix models that replace the default characterization set.
- `FCC_SMOKE_OPENROUTER_FREE_EXTRA_MODELS`: optional comma-separated OpenRouter
  free CLI matrix models appended to the default or replacement set.
- `FCC_SMOKE_TIMEOUT_S`: per-request/subprocess timeout, default `45`.
- `FCC_SMOKE_CLAUDE_BIN`: Claude CLI executable name, default `claude`.
- `FCC_SMOKE_AUTO_COMPACT_MODEL`: optional provider/model reference for the
  real automatic-compaction/resume gate; the gate is opt-in and uses a
  metadata-only report. Its `token_evidence` also summarizes structured
  provider-attribution records (provider/protocol, completed turns, attempts,
  HTTP errors, request/prefix hash counts, TTFT, and duration) without retaining
  request or response payloads.
- `FCC_SMOKE_REASONING_MATRIX=1`: opt-in live matrix for Claude's `low`,
  `medium`, `high`, `xhigh`, and `max` effort levels.
- `FCC_SMOKE_REASONING_MODEL`: optional provider/model reference for that
  reasoning matrix; otherwise the first configured provider model is used.
- `FCC_SMOKE_REASONING_BOUNDARIES=1`: opt-in direct Messages boundary for
  explicit `off` and `minimal` reasoning controls through an isolated Muse
  route. The probe uses the shared 4,096-token safety budget so hidden
  reasoning cannot manufacture a false `response.incomplete` result.
- `FCC_SMOKE_REASONING_BOUNDARY_MODEL`: optional provider/model reference for
  that boundary; otherwise it uses `opencode_go/muse-spark-1.2-contributor`.
- `FCC_SMOKE_SUBAGENT=1`: opt-in foreground Claude `Agent`/subagent probe.
- `FCC_SMOKE_SUBAGENT_MODEL`: optional provider/model reference for that probe.
- `FCC_SMOKE_BACKGROUND_SUBAGENT=1`: opt-in background Claude `Agent`/subagent
  probe; it requires an explicit `run_in_background=true` event in the
  metadata-only gateway trace.
- `FCC_SMOKE_BACKGROUND_SUBAGENT_MODEL`: optional provider/model reference for
  the background probe; otherwise `FCC_SMOKE_SUBAGENT_MODEL` is reused.
- `FCC_SMOKE_MANAGED_MODEL`: optional provider/model reference for the live
  managed-Claude fresh/resume/fork route check; the check uses an isolated temporary
  Claude config and never changes the user's settings or sessions.
- `FCC_SMOKE_TELEGRAM_CHAT_ID`: Telegram chat/user ID for send/edit/delete.
- `FCC_SMOKE_DISCORD_CHANNEL_ID`: Discord channel ID for send/edit/delete.
- `FCC_SMOKE_INTERACTIVE=1`: enables manual inbound Telegram/Discord checks.
- `FCC_SMOKE_RUN_VOICE=1`: allows voice transcription backends to load/run.

The checked-in
[Claude compatibility matrix](receipts/claude-compatibility-matrix-2026-08-24.json)
maps the current fresh, resume, fork, compact-resume, foreground-subagent,
wrapper, background, and upgrade surfaces. It is deliberately explicit about
`unverified` and `skipped` boundaries; a receipt row is not a claim that the
underlying client surface is certified unless its status is `passed`.

The metadata-only [media conformance corpus](fixtures/media-conformance-v1.json)
enumerates the supported image/tool-result protocol boundaries, deterministic
rejection cases, retry identity, and native/provider route pairs. It contains
no image bytes or prompt payloads. The corpus is a contract inventory; live
vision and computer-use round trips remain explicitly separate acceptance gates.

## OpenCode Go transport benchmark

The synthetic benchmark isolates FCC transport overhead with a local keep-alive
SSE upstream and writes a metadata-only receipt containing raw latency/TTFT
samples, RSS snapshots, CPU time, observed chunk size, connection reuse,
request-body sizes, retry amplification, and the configured output-token budget.

```powershell
uv run python scripts/benchmark_opencode_go_transport.py --mode synthetic --model qwen3.7-plus --samples 1,100,1000
```

Use `--model muse-spark-1.2-contributor` or a Chat model to exercise the other
native routes. The benchmark defaults to `--max-tokens 4096`, which gives Muse
enough reasoning budget to emit visible output instead of manufacturing an
`response.incomplete` terminal event. Override it explicitly for a different
workload. Live mode is deliberately gated because it can consume Go quota and
requires real credentials:

```powershell
$env:FCC_OPENCODE_GO_BENCHMARK_LIVE = "1"
$env:OPENCODE_API_KEY = "..."
uv run python scripts/benchmark_opencode_go_transport.py --mode live --model muse-spark-1.2-contributor --samples 1,10,100 --max-tokens 4096
```

Live receipts prove the configured integration only; native OpenCode reference
comparison and cache-dollar parity require a separately captured reference
receipt. Benchmark artifacts must not contain prompt bodies or credentials.

## Windows / nested `uv run`

Run smoke the same way you run tests (`uv run pytest smoke` from the repo). Child
processes use the **same Python interpreter** as the test runner, not nested
`uv run`, so Windows does not try to replace `fcc-server.exe` while it is
locked.

## OpenCode Go economic receipts

Use the evaluator for redacted JSONL receipts captured from the native OpenCode
reference and FCC bridge. The first line of each receipt should contain
`{"_receipt":{"commit_sha":"...","model":"...","protocol":"..."}}`;
remaining rows contain disjoint `uncached_input_tokens`, `cache_read_tokens`,
`cache_write_tokens`, and `output_tokens` plus optional attempt and stable-prefix
hash fields:

```powershell
uv run python smoke/opencode_go_economics.py --native native.jsonl --fcc fcc.jsonl
```

The evaluator applies the source-stamped fixture at
[`smoke/fixtures/opencode_go_pricing.json`](fixtures/opencode_go_pricing.json),
reports cache share, token amplification, retry amplification, prefix-match
rate, and estimated cost regression, and exits nonzero when the default 5%
cost-regression gate or native-relative cache gate fails. By default, the cache
gate is relative to the native receipt: FCC may not trail native by more than 3
percentage points. Use `--min-cache-read-share` only as an explicit legacy
absolute override. It never stores or requires prompt content. Native-reference
and live Go receipts remain opt-in human-supplied artifacts; deterministic unit
tests cover the bridge-side serialization guard and reject native/FCC receipts
with mismatched row counts, model sequences, phase sequences, or compact-boundary
shape.

Compaction-boundary rows may additionally include `phase` (`pre_compact`,
`compact_turn`, `post_compact`, or `resume`) and a metadata-only
`compact_boundary_hash`. `summarize_phases()` keeps those economics separate so
the compaction turn and resume turn cannot hide a post-compact token increase.
The deterministic semantic gate in
[`smoke/lib/compaction_continuity.py`](lib/compaction_continuity.py) records
provider/model/protocol, system/tool and message-shape hashes, tool/result ids,
session relationship, reasoning-state type/hash, media type/count, memory/skill
ids, committed tool ids, and attempts. It rejects prompt, image, tool-result,
and reasoning payload fields before a receipt can be written.
The checked-in [synthetic continuity receipt](receipts/compaction-continuity-synthetic.json)
is a schema/regression fixture, not live provider evidence.
The checked-in
[synthetic native compaction fixture](fixtures/opencode_go_compaction_native.sample.jsonl)
and
[synthetic FCC compaction fixture](fixtures/opencode_go_compaction_fcc.sample.jsonl)
exercise the phase economics thresholds without claiming a live native-vs-FCC
measurement. Live economic receipts still require an explicitly captured native
reference and FCC run.

## Failure Classes

Smoke artifacts are written to `.smoke-results/` and redact env values whose
names contain `KEY`, `TOKEN`, `SECRET`, `WEBHOOK`, or `AUTH`.

- `missing_env`: required credentials, binary, provider config, local provider
  server/model, or opt-in flag is absent.
- `upstream_unavailable`: a real provider or bot API is not reachable.
- `probe_timeout`: the smoke driver reached the target, but the CLI/probe did
  not complete within the smoke timeout.
- `product_failure`: the app accepted the scenario but returned the wrong shape,
  crashed, leaked state, or violated the product contract.
- `harness_bug`: the smoke test or driver made an invalid assumption.
- `target_disabled`: skipped because `FCC_SMOKE_TARGETS` intentionally selected
  a different target.

`product_failure` and `harness_bug` are failures. `missing_env`,
`upstream_unavailable`, and `probe_timeout` are skips except when the user
explicitly selected a provider in `FCC_SMOKE_PROVIDER_MATRIX`;
selected-but-missing providers fail.
