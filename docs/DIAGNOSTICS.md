# Terminal diagnostics

`fcc-diagnose` explains a synthetic request shape using the configured model
router and capability policy. It never starts a provider, reads prompt content,
or makes a network request.

```bash
fcc-diagnose route --model opencode_go/muse-spark-1.2-contributor --shape text
fcc-diagnose route --model opencode_go/muse-spark-1.2-contributor \
  --shape vision --known vision_input --supported vision_input
```

The JSON output separates the requested model, resolved provider/model/protocol,
required capabilities, evidence state, policy, and the final primary/helper or
typed rejection decision. `--known` and `--supported` are explicit diagnostic
assertions; they do not query a provider catalog. Omit them to see the safe
unknown/strict rejection that applies when capability evidence is absent.

The `provider_isolation` section is a metadata-only launch-policy preview. It
shows the primary provider/model, local tool allowance, and forbidden fallback
families. `fallback_decision` is `blocked` under the default strict policy; the
diagnostic does not authorize a request or instantiate a provider.

Useful synthetic shapes include `text`, `tools`, `parallel-tools`, `vision`,
`image-tool-result`, `reasoning`, `structured`, `browser`, `macos`, and
`screenshot`. Multiple shapes can be comma-separated. The command is intended
for terminal workflows and is independent of the local Admin UI.

## Provider attempt receipts

OpenCode Go provider traces emit `provider.fault_attribution` as metadata-only
receipts. In addition to route, protocol, token, cache, tool, retry, and fault
fields, each stream receipt includes media and timing metadata:

The shared `provider.response.error` event emitted by the OpenAI-compatible and
ChatGPT/Codex provider paths carries the same `fault_domain`, `confidence`, and
non-empty `evidence_codes` fields. A transport or upstream error without enough
evidence remains `unknown`; the trace must not guess that the model or AgentSwitchboard
caused it.

- `media_count`: number of image/document blocks in the request, including
  nested tool results.
- `media_type_hash`: ordered one-way hash of media block type and declared media
  type. It is `null` when the request contains no media.
- `duration_ms`: elapsed time from the provider adapter entering the stream
  path through receipt emission. It includes any provider retry/backoff within
  that logical stream and is `null` only when no timing could be recorded.
- `time_to_first_token_ms`: elapsed time until the first non-empty streamed
  output or SSE payload, or `null` when no output arrived.

These fields are metadata only. Prompts, response text, tool arguments, media
bytes, and provider credentials are not placed in the receipt. Request-shape,
stable-prefix, tool-schema, and media-type hashes remain one-way identifiers for
comparing controlled runs without retaining payloads.

The API ingress emits `free_claude_code.api.visual_input.admitted` after image
validation and capability admission. Its receipt contains only image counts,
inline byte totals, validated attachment metadata, and the selected provider
reference; it never includes image URLs or base64 data. Invalid inline bytes,
unsupported source types, unsafe URL schemes, and explicit non-vision metadata
fail before provider construction. Unknown capability metadata is preserved for
the provider protocol to decide.
Request-shape and
stable-prefix hashes deliberately exclude `metadata` and the Responses
`prompt_cache_key`: those values partition cache state or carry client
bookkeeping, but are not logical prompt shape. This keeps session affinity from
making an otherwise identical native/AgentSwitchboard envelope appear different.

Responses cache affinity is conservative and metadata-only. A normalized
opaque caller key or persistent client session header may be forwarded when it
passes the identifier guard; prompt text, paths, timestamps, secrets, and
request-shaped identifiers are rejected. Keys longer than the provider's
64-character limit are deterministically domain-hashed after validation, so a
stable workspace/session identity keeps its affinity without making an invalid
request. This is a source-level invariant, not a native-vs-AgentSwitchboard
economic result: no cache-key promotion or parity claim is made without
comparable live receipts containing cache read/write, uncached input, cost,
TTFT, and retry evidence.

The OpenAI Codex adapter also marks the end of its collected system prefix with
the GPT-5.6 `prompt_cache_breakpoint` content-block field. It moves that prefix
from top-level `instructions` into a developer input message only when the
adapter capability is enabled; generic Responses callers and other providers
keep the existing shape. The capability is injectable so an endpoint that has
not verified this request field can disable it; the private Codex adapter keeps
it disabled by default until a live endpoint check proves support. The private
Codex path does not send `prompt_cache_options`, because the breakpoint-only
shape is the smallest compatible request and the option is not required for
cache reuse. A breakpoint and cache key are still only hints: the provider's
cache-read/write counters
remain the acceptance evidence, and compaction or upstream routing can reduce
reuse.

If the configured Codex-compatible endpoint explicitly rejects
`prompt_cache_breakpoint`, the adapter performs one bounded request-shape
correction: it removes the breakpoint, restores the previously accepted
top-level `instructions` form, and records a process-local capability
downgrade. It does not retry unrelated HTTP 400 responses or loop on the same
unsupported field. This preserves availability, but a successful fallback is
not evidence of an explicit cache hit; only upstream cache usage counters can
establish that result.
