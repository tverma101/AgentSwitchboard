"""Fail-closed public Responses stream adapter.

The historical provider-stream implementation accepts provider snapshots from a
few compatibility variants. This guard keeps that compatibility for valid
append-only snapshots while preventing divergent terminal replacements and
unknown incomplete reasons from being presented as successful Anthropic turns.
"""

from . import provider_stream

_BaseResponsesProviderStream = provider_stream.ResponsesProviderStream
ResponsesStreamFailure = provider_stream.ResponsesStreamFailure

_MAX_TOKEN_INCOMPLETE_REASONS = frozenset({"max_output_tokens", "max_tokens"})


class ResponsesProviderStream(_BaseResponsesProviderStream):
    """Responses stream adapter with strict terminal lifecycle semantics."""

    def _emit_reasoning_text(
        self,
        text: str,
        *,
        summary: bool,
        identity: str,
        index: int,
        final: bool,
    ) -> list[str]:
        if final:
            key = ("summary" if summary else "text", identity, index)
            existing = self._reasoning_text_by_key.get(key, "")
            if _terminal_continuation_suffix(existing, text) is None:
                raise ResponsesStreamFailure(
                    "OpenAI terminal reasoning snapshot diverged from streamed content.",
                    code="divergent_terminal_snapshot",
                )
        return super()._emit_reasoning_text(
            text,
            summary=summary,
            identity=identity,
            index=index,
            final=final,
        )

    def _emit_visible_text(
        self,
        text: str,
        *,
        kind: str,
        identity: str,
        index: int,
        final: bool,
    ) -> list[str]:
        if final:
            stores = {
                "text": self._output_text_by_key,
                "refusal": self._refusal_text_by_key,
            }
            existing = stores[kind].get((kind, identity, index), "")
            if _terminal_continuation_suffix(existing, text) is None:
                raise ResponsesStreamFailure(
                    f"OpenAI terminal {kind} snapshot diverged from streamed content.",
                    code="divergent_terminal_snapshot",
                )
        return super()._emit_visible_text(
            text,
            kind=kind,
            identity=identity,
            index=index,
            final=final,
        )

    def _terminal_stop_reason(self, *, incomplete: bool) -> str:
        if (
            incomplete
            and not self.provider_refusal
            and self.incomplete_reason not in _MAX_TOKEN_INCOMPLETE_REASONS
        ):
            reason = self.incomplete_reason or "unknown"
            raise ResponsesStreamFailure(
                "OpenAI response was incomplete for a reason that cannot be mapped "
                f"safely to Anthropic stop semantics: {reason}.",
                code="incomplete_response",
            )
        return super()._terminal_stop_reason(incomplete=incomplete)


def _terminal_continuation_suffix(existing: str, candidate: str) -> str | None:
    """Return the suffix of a full terminal snapshot that extends streamed bytes.

    Responses ``*.done`` events are full snapshots, not arbitrary continuation
    chunks. Once bytes have escaped to the Anthropic client, accepting a merely
    overlapping replacement can duplicate or corrupt output. Therefore a final
    snapshot is valid only when it contains the entire streamed prefix.
    """

    existing = existing or ""
    candidate = candidate or ""
    if not candidate:
        return "" if not existing else None
    if not existing:
        return candidate
    if candidate.startswith(existing):
        return candidate[len(existing) :]
    return None


__all__ = ["ResponsesProviderStream", "ResponsesStreamFailure"]
