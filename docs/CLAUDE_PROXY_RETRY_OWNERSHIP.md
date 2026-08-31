# Claude proxy retry ownership

Claude Code owns the agent loop. AgentSwitchboard owns retries at the proxy/provider transport boundary.

For an FCC-routed session, a request that may already have produced provider-visible output or tool intent must not be invisibly replayed through a second client-side transport mode. FCC/provider adapters already track committed output, tool-call completion, retryability, and fault attribution; that is the layer that can decide whether a retry is safe.

The managed Claude environment therefore disables Claude Code's stream-to-nonstream fallback and lets a streaming failure surface to FCC instead of causing an independent client replay.

For the ChatGPT/Codex subscription bridge, FCC may briefly retain the initial Anthropic SSE frames so an immediate upstream cutoff can still be retried invisibly. That holdback is a real wall-clock boundary: after the upstream SSE request is accepted, FCC commits the buffered frames after 750 ms even when no additional upstream event arrives. Once committed, later SSE events are forwarded without FCC pacing or batching. An upstream Codex stall can still pause generation; FCC must not stretch that pause by waiting for another token to wake its own holdback timer.

This rule does not change direct/native Claude launches that do not use the FCC proxy.

This implemented boundary decision is retained as historical traceability for the proxy-retry work; the earlier issue reference is not an open-backlog claim.
