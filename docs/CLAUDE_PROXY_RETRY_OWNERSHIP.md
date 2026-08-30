# Claude proxy retry ownership

Claude Code owns the agent loop. AgentSwitchboard owns retries at the proxy/provider transport boundary.

For an FCC-routed session, a request that may already have produced provider-visible output or tool intent must not be invisibly replayed through a second client-side transport mode. FCC/provider adapters already track committed output, tool-call completion, retryability, and fault attribution; that is the layer that can decide whether a retry is safe.

The managed Claude environment therefore disables Claude Code's stream-to-nonstream fallback and lets a streaming failure surface to FCC instead of causing an independent client replay.

This rule does not change direct/native Claude launches that do not use the FCC proxy.

Tracks #181.
