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
shows the primary provider/model, explicit helper/local-tool allowances, and
forbidden fallback families. `fallback_decision` and `would_be_fallback` are
`blocked` under the default strict policy; the diagnostic does not authorize a
request or instantiate a provider.

Runtime egress traces use `provider.egress.decision` for pre-network admission
and `provider.egress.usage` for sanitized per-session totals. Receipts retain
hashed session identifiers plus request/category, token, cache, image, and
retry counters. A blocked policy decision is attributed to `harness_bridge`;
it is not retried or converted into an implicit provider fallback.

Useful synthetic shapes include `text`, `tools`, `parallel-tools`, `vision`,
`image-tool-result`, `reasoning`, `structured`, `browser`, `macos`, and
`screenshot`. Multiple shapes can be comma-separated. The command is intended
for terminal workflows and is independent of the local Admin UI.

## Provider attempt receipts

OpenCode Go provider traces emit `provider.fault_attribution` as metadata-only
receipts. In addition to route, protocol, token, cache, tool, retry, and fault
fields, each stream receipt includes media and timing metadata:

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
