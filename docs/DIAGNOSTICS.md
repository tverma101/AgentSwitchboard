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
