# Controller fallback policy harvest

AgentSwitchboard treats same-controller retry, capability helpers, and controller fallback
as different recovery paths. This note records the upstream concepts used by
`application/fallback_policy.py`; no upstream router runtime is imported.

## Pinned sources

- `musistudio/claude-code-router@99f24806c6a2c660b16e53e95211c517448a6c90`
  - MIT license.
  - Useful concepts: explicit routing/fallback configuration, ordered targets,
    request-aware routing metadata, and observable route choice.
  - Regression evidence additionally harvested from CCR #1615 and #1697.
- `BerriAI/litellm@ea6ac3dd99a8d9af6271e9784b1442030aead94a`
  - Repository content outside `enterprise/` is MIT; no enterprise code or
    implementation is copied.
  - Useful concepts: separate retry/fallback configuration, ordered fallback
    lists, context-window-specific fallback, and target eligibility metadata.

The AgentSwitchboard implementation is a native typed policy, not a port of either
runtime.

## Adapted policy shapes

- an empty fallback allowlist means **zero controller failover**;
- explicit ordered model refs are the only eligible controller targets;
- same-controller retry is classified independently from controller fallback;
- capability helpers continue to use `CapabilityRouter` and cannot become a
  controller fallback implicitly;
- any controller switch is forbidden after model output or tool execution has
  committed;
- every controller switch requires the original canonical request to remain
  available so the target request can be rebuilt for that provider;
- cross-protocol fallback is disabled unless explicitly enabled;
- the target must satisfy every required request capability;
- the request must fit the target context window;
- a context-window failure may use an explicitly configured larger target even
  though that source failure is not a same-controller retry;
- same-subscription fallback is the default boundary;
- decisions expose content-free provider/model/failure/reason receipts.

## Regression-derived invariants

### CCR #1615 — stale cross-protocol body

A fallback executor reused a request transformed for one protocol when trying a
second protocol. AgentSwitchboard policy therefore requires canonical controller input
for every target switch. Cross-protocol switching also needs a separate
explicit policy bit. A future executor must construct the target request from
that canonical input; it may not replay the previous provider body.

### CCR #1697 — provider transforms lost on fallback

Provider-specific header/request transforms were applied to the first route but
not correctly rebuilt for a later target. Requiring canonical input for *every*
controller switch, including same-protocol switches, prevents a target from
inheriting or losing a previous provider's transformed request state.

## Explicitly rejected upstream behavior

- silent fallback by default;
- health/provider discovery on the generation hot path;
- fallback solely because credentials or another provider happen to exist;
- cross-subscription fallback without explicit policy;
- post-commit replay onto another controller;
- treating a local capability helper as a controller replacement;
- reusing provider-shaped request bodies across targets;
- importing LiteLLM or CCR as a runtime dependency for this policy.

## Integration boundary

This policy does not execute controller fallback. Runtime integration must keep
fallback disabled unless a user-facing configuration explicitly supplies the
ordered allowlist. Provider/subscription policy from #22 must authorize the
selected target before network I/O, and any eventual execution path must emit
the policy receipt alongside attempt/final-route diagnostics.
