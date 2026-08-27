# Reviewer scar upstream notes

`free_claude_code.learning.reviewer_scars` is a small, local evidence registry
for parent/subagent review work. It stores only typed metadata and bounded
evidence references; it does not store transcripts, prompts, hidden reasoning,
credentials, or provider responses.

## Reference implementation

The review-pack and reflection ideas were compared with the Apache-2.0 Letta
Code reflection note at [b94afce3a9e57fec042c27bc6fb43c43e27c7774](https://github.com/letta-ai/letta-code/blob/b94afce3a9e57fec042c27bc6fb43c43e27c7774/src/agent/subagents/builtin/reflection.md).
Harness does not vendor that runtime or copy its transcript/memory behavior.

The local adaptation keeps only these ideas:

- choose the smallest review pack from explicit task signals;
- admit a scar only when a concrete prevented-pain class and evidence state are
  present;
- deduplicate by a semantic identifier and retain state history;
- inject a bounded, deterministic slice into a later review context.

The local contract deliberately excludes automatic background edits, broad
transcript persistence, implicit promotion, provider calls, and unbounded
context growth. A real parent/subagent integration and A/B canary remain
separate acceptance work; deterministic contracts must not be reported as that
live evidence.
