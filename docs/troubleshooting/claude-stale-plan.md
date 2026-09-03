# Claude Code stale `ExitPlanMode` payload

## Structured record

- `scope`: Claude Code session `c2be2eec-c11c-4d70-9659-2c6c434bb924`, with FCC's `/v1/messages` gateway and local Codex Responses-Lite compatibility path inspected; the uncertified FCC context intervention was subsequently disabled in source and local FCC state.
- `project`: `tverma101/AgentSwitchboard`
- `status`: ownership narrowed; client/model-side stale-plan cause is most likely, and FCC's uncertified context intervention is now disabled in both source and local FCC state.
- `canonical_doc`: `docs/codex/turn-log.md`
- `last_verified`: `2026-09-02`
- `symptoms`: after a compaction and a new plan-mode entry for an Ultracode request, Claude Code displayed the new Ultracode plan in text but emitted an `ExitPlanMode` tool call containing the earlier server-lifecycle plan. The persisted Claude plan file also still contained the earlier plan.
- `root_cause`: no FCC source path inspected here owns Claude plan files or recognizes `EnterPlanMode`, `ExitPlanMode`, or `planFilePath`. FCC's request converter carries prior assistant tool calls into Responses as `function_call` items without changing their JSON, and the response adapter forwards upstream function-call argument deltas without cross-request reuse. The strongest attribution is Claude Code's plan/client state or model-generated tool arguments after compaction/re-entry, not an FCC plan substitution.
- `validation`: the focused converter/provider suite passed 162 tests before the follow-up change; the follow-up FCC boundary suite passed 376 tests. Synthetic input conversion preserved an old plan argument exactly, and a synthetic upstream stream containing current plan text plus old tool arguments emitted both values exactly. Source tracing covered `MessagesHandler`, context governance, provider request construction, Codex provider retry state, streaming tool state, launcher environment, learning hooks, and the local native Codex CLI catalog. The live and sandbox FCC wrapper artifacts now run without context variables.
- `residual_gap`: FCC had no raw inbound/provider body or upstream response capture for this incident. The server access log records only a successful request. A clean reproduction with sanitized correlation/digests is required to classify the first boundary conclusively.
- `rollout_refs`: Claude transcript path `/Users/tejas/.claude/projects/-Users-tejas-Projects-AgentSwitchboard/c2be2eec-c11c-4d70-9659-2c6c434bb924.jsonl`; persisted plan path `/Users/tejas/.claude/plans/nested-finding-matsumoto.md`.

## What FCC can affect

The stale plan finding and the broader “the model follows the user less often” concern must be separated.

In local Responses-Lite mode, FCC adds a short Codex base-instructions developer message and a namespaced `additional_tools` item, then preserves the full Claude system context. Native Codex's local catalog contains a much larger mutable instruction template, so this is a real prompt-parity difference and a plausible source of general behavior drift. An earlier FCC source version also set Claude's context and auto-compact environment; that intervention is now disabled in standard mode and remains a narrow 256K exception in the sandbox launcher. Neither mechanism has code that can select an old Claude plan file or rewrite only an `ExitPlanMode` argument.

The optional FCC learning hook is SessionStart-only and was disabled in the inspected runtime. The configured Claude hooks did not show an FCC hook injecting project memory into this session. Claude Code `2.1.258` was marked forward-compatible rather than certified in FCC's compatibility records; that is a validation risk, not proof of this defect.

## Next discriminating experiment

Run one clean, sandbox-only reproduction with bounded, sanitized correlation at three points:

1. FCC's accepted Anthropic request before conversion.
2. FCC's outbound Responses request before the provider HTTP call.
3. The upstream Responses events before Anthropic SSE reconstruction.

Compare the digest and tool-argument payload at each point. If the old argument is already present at (1), FCC did not introduce it. If it changes between (1) and (2), the converter is responsible. If it changes only at (3), investigate the upstream model/backend. If (3) is current but Claude's transcript is stale, investigate Claude Code response/tool-state handling.
