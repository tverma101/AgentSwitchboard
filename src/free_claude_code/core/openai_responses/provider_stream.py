"""Translate upstream OpenAI Responses events into Anthropic Messages SSE."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from free_claude_code.core.anthropic.openai_tool_names import OpenAIToolNameCodec
from free_claude_code.core.anthropic.streaming import AnthropicStreamLedger


class ResponsesStreamFailure(RuntimeError):
    """An upstream Responses stream reported a terminal failure."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(slots=True)
class _ToolState:
    tool_index: int
    call_id: str
    name: str
    started: bool = False
    received_delta: bool = False
    stopped: bool = False
    argument_parts: list[str] | None = None
    arguments_emitted: bool = False
    arguments_complete: bool = False
    valid_arguments: bool = False


_MAX_TOOL_ARGUMENT_BYTES = 65_536


class ResponsesProviderStream:
    """Stateful one-way adapter for one upstream response."""

    def __init__(
        self,
        *,
        message_id: str,
        model: str,
        input_tokens: int,
        log_raw_events: bool = False,
        tool_names: OpenAIToolNameCodec | None = None,
    ) -> None:
        self.ledger = AnthropicStreamLedger(
            message_id,
            model,
            input_tokens,
            log_raw_events=log_raw_events,
        )
        self.completed = False
        self.generated_output = False
        self.upstream_response_id: str | None = None
        self.terminal_event: str | None = None
        self.usage_input_tokens: int | None = None
        self.usage_cache_read_tokens: int | None = None
        self.usage_cache_write_tokens: int | None = None
        self.usage_output_tokens: int | None = None
        self.usage_reasoning_tokens: int | None = None
        self.effective_reasoning_effort: str | None = None
        self.provider_reasoning_item = False
        self.provider_visible_reasoning_summary = False
        self.provider_visible_reasoning_summary_length: int | None = None
        self.provider_reasoning_text = False
        self.provider_opaque_reasoning = False
        self.opaque_reasoning_hash: str | None = None
        self.harness_thinking_block = False
        self.harness_thinking_delta = False
        self._tool_names = tool_names or OpenAIToolNameCodec.from_names(())
        self._tools: dict[str, _ToolState] = {}
        self._tool_items_by_call_id: dict[str, str] = {}
        self._duplicate_tool_item_ids: set[str] = set()
        self._encrypted_reasoning: dict[str, str] = {}

    def start(self) -> list[str]:
        """Return the Anthropic message_start event."""

        return [self.ledger.message_start()]

    def feed(self, event_type: str, data: dict[str, Any]) -> list[str]:
        """Consume one Responses event and return zero or more Anthropic events."""

        if self.completed:
            return []
        if event_type == "response.output_item.added":
            return self._item_added(data)
        if event_type == "response.reasoning_text.delta":
            return self._reasoning_delta(data, summary=False)
        if event_type == "response.reasoning_summary_text.delta":
            return self._reasoning_delta(data, summary=True)
        if event_type == "response.output_text.delta":
            return self._text_delta(data)
        if event_type == "response.function_call_arguments.delta":
            return self._tool_delta(data)
        if event_type == "response.function_call_arguments.done":
            return self._tool_arguments_done(data)
        if event_type == "response.output_item.done":
            return self._item_done(data)
        if event_type in {"response.completed", "response.incomplete"}:
            return self._finish(
                data,
                incomplete=event_type == "response.incomplete",
                terminal_event=event_type,
            )
        if event_type in {"response.failed", "error", "response.error"}:
            raise _stream_failure(data)
        return []

    def _item_added(self, data: dict[str, Any]) -> list[str]:
        item = data.get("item")
        if not isinstance(item, dict):
            return []
        item_id = _string(item.get("id"))
        if item.get("type") == "function_call" and item_id:
            call_id = _string(item.get("call_id")) or item_id
            name = self._tool_names.decode(_string(item.get("name")))
            existing_item_id = self._tool_items_by_call_id.get(call_id)
            if existing_item_id is not None and existing_item_id != item_id:
                self._duplicate_tool_item_ids.add(item_id)
                return []
            self._tool_items_by_call_id[call_id] = item_id
            state = self._tools.get(item_id)
            if state is None:
                self._tools[item_id] = _ToolState(
                    tool_index=len(self._tools),
                    call_id=call_id,
                    name=name,
                )
            else:
                if state.call_id == item_id and call_id != item_id:
                    state.call_id = call_id
                if not state.name and name:
                    state.name = name
        if item.get("type") == "reasoning":
            self.provider_reasoning_item = True
        if item.get("type") == "reasoning" and item_id:
            encrypted = item.get("encrypted_content")
            if isinstance(encrypted, str) and encrypted:
                self._remember_opaque_reasoning(item_id, encrypted)
        return []

    def _reasoning_delta(self, data: dict[str, Any], *, summary: bool) -> list[str]:
        delta = data.get("delta")
        if not isinstance(delta, str) or not delta:
            return []
        self.provider_reasoning_item = True
        if summary:
            self.provider_visible_reasoning_summary = True
            self.provider_visible_reasoning_summary_length = (
                self.provider_visible_reasoning_summary_length or 0
            ) + len(delta)
        else:
            self.provider_reasoning_text = True
        events = list(self.ledger.ensure_thinking_block())
        self.harness_thinking_block = True
        events.append(self.ledger.emit_thinking_delta(delta))
        self.harness_thinking_delta = True
        self.generated_output = True
        return events

    def _remember_opaque_reasoning(self, item_id: str, encrypted: str) -> None:
        self.provider_reasoning_item = True
        self.provider_opaque_reasoning = True
        self._encrypted_reasoning[item_id] = encrypted
        self.opaque_reasoning_hash = hashlib.sha256(
            encrypted.encode("utf-8")
        ).hexdigest()

    def _text_delta(self, data: dict[str, Any]) -> list[str]:
        delta = data.get("delta")
        if not isinstance(delta, str) or not delta:
            return []
        events = list(self.ledger.ensure_text_block())
        events.append(self.ledger.emit_text_delta(delta))
        self.generated_output = True
        return events

    def _tool_delta(self, data: dict[str, Any]) -> list[str]:
        item_id = _string(data.get("item_id"))
        delta = data.get("delta")
        if not item_id or not isinstance(delta, str):
            return []
        if item_id in self._duplicate_tool_item_ids:
            return []
        state = self._tools.get(item_id)
        if state is None:
            state = _ToolState(
                tool_index=len(self._tools),
                call_id=item_id,
                name="",
            )
            self._tools[item_id] = state
        if state.argument_parts is None:
            state.argument_parts = []
        if delta:
            next_size = sum(
                len(part.encode("utf-8", errors="replace"))
                for part in state.argument_parts
            ) + len(delta.encode("utf-8", errors="replace"))
            if next_size > _MAX_TOOL_ARGUMENT_BYTES:
                raise ResponsesStreamFailure(
                    "OpenAI function-call arguments exceeded the safety limit.",
                    code="tool_arguments_too_large",
                )
        events = list(self.ledger.close_content_blocks())
        events.extend(self._ensure_tool_started(state))
        if delta:
            events.append(self.ledger.emit_tool_delta(state.tool_index, delta))
            state.argument_parts.append(delta)
            state.received_delta = True
            self.generated_output = True
        return events

    def _tool_arguments_done(self, data: dict[str, Any]) -> list[str]:
        item_id = _string(data.get("item_id"))
        arguments = data.get("arguments")
        if not item_id or not isinstance(arguments, str):
            return []
        if item_id in self._duplicate_tool_item_ids:
            return []
        state = self._tools.get(item_id)
        if state is None:
            state = _ToolState(
                tool_index=len(self._tools),
                call_id=item_id,
                name="",
            )
            self._tools[item_id] = state
        if len(arguments.encode("utf-8", errors="replace")) > _MAX_TOOL_ARGUMENT_BYTES:
            raise ResponsesStreamFailure(
                "OpenAI function-call arguments exceeded the safety limit.",
                code="tool_arguments_too_large",
            )
        if state.argument_parts is None:
            state.argument_parts = []
        if not state.received_delta:
            state.argument_parts = [arguments]
        state.arguments_complete = True
        events: list[str] = []
        if not state.arguments_emitted:
            events.extend(self.ledger.close_content_blocks())
            events.extend(self._ensure_tool_started(state))
            if arguments and not state.received_delta:
                events.append(self.ledger.emit_tool_delta(state.tool_index, arguments))
                state.arguments_emitted = True
                self.generated_output = True
        self._validate_tool_arguments(state)
        return events

    def _item_done(self, data: dict[str, Any]) -> list[str]:
        item = data.get("item")
        if not isinstance(item, dict):
            return []
        item_type = item.get("type")
        item_id = _string(item.get("id"))
        if item_type == "function_call":
            if item_id in self._duplicate_tool_item_ids:
                return []
            state = self._tools.get(item_id)
            if state is None:
                state = _ToolState(
                    tool_index=len(self._tools),
                    call_id=_string(item.get("call_id")) or item_id,
                    name=self._tool_names.decode(_string(item.get("name"))),
                )
                self._tools[item_id] = state
            if not state.name:
                state.name = self._tool_names.decode(_string(item.get("name")))
            events = list(self.ledger.close_content_blocks())
            events.extend(self._ensure_tool_started(state))
            arguments = item.get("arguments")
            if (
                not state.received_delta
                and not state.arguments_emitted
                and isinstance(arguments, str)
                and arguments
            ):
                if (
                    len(arguments.encode("utf-8", errors="replace"))
                    > _MAX_TOOL_ARGUMENT_BYTES
                ):
                    raise ResponsesStreamFailure(
                        "OpenAI function-call arguments exceeded the safety limit.",
                        code="tool_arguments_too_large",
                    )
                state.argument_parts = [arguments]
                events.append(self.ledger.emit_tool_delta(state.tool_index, arguments))
                state.arguments_emitted = True
                self.generated_output = True
            state.arguments_complete = True
            self._validate_tool_arguments(state)
            if not state.stopped:
                events.append(self.ledger.stop_tool_block(state.tool_index))
                state.stopped = True
                self.ledger.blocks.tool_states[state.tool_index].started = False
            return events
        if item_type == "reasoning":
            encrypted = item.get("encrypted_content")
            if not isinstance(encrypted, str) or not encrypted:
                encrypted = self._encrypted_reasoning.get(item_id)
            if isinstance(encrypted, str) and encrypted:
                self._remember_opaque_reasoning(item_id, encrypted)
                events = list(self.ledger.close_content_blocks())
                index = self.ledger.blocks.allocate_index()
                events.append(
                    self.ledger.content_block_start(
                        index, "redacted_thinking", data=encrypted
                    )
                )
                events.append(self.ledger.content_block_stop(index))
                self.generated_output = True
                self.harness_thinking_block = True
                return events
        return []

    def _ensure_tool_started(self, state: _ToolState) -> list[str]:
        if state.started:
            return []
        state.started = True
        self.generated_output = True
        return [
            self.ledger.start_tool_block(
                state.tool_index,
                state.call_id,
                state.name,
            )
        ]

    def _validate_tool_arguments(self, state: _ToolState) -> None:
        arguments = "".join(state.argument_parts or [])
        if not arguments:
            raise ResponsesStreamFailure(
                "OpenAI function-call arguments were missing.",
                code="invalid_tool_arguments",
            )
        try:
            parsed = json.loads(arguments)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ResponsesStreamFailure(
                "OpenAI function-call arguments were not valid JSON.",
                code="invalid_tool_arguments",
            ) from exc
        if not isinstance(parsed, dict):
            raise ResponsesStreamFailure(
                "OpenAI function-call arguments must be a JSON object.",
                code="invalid_tool_arguments",
            )
        state.arguments_complete = True
        state.valid_arguments = True

    def _finish(
        self,
        data: dict[str, Any],
        *,
        incomplete: bool,
        terminal_event: str,
    ) -> list[str]:
        response = data.get("response")
        response = response if isinstance(response, dict) else {}
        self.upstream_response_id = _string(response.get("id")) or None
        self.terminal_event = terminal_event
        for state in self._tools.values():
            self._validate_tool_arguments(state)
            if not state.stopped:
                raise ResponsesStreamFailure(
                    "OpenAI completed a function call without its output-item terminal.",
                    code="missing_tool_terminal",
                )
        events = list(self.ledger.close_all_blocks())
        if not self.generated_output or not self.ledger.has_content_block():
            raise ResponsesStreamFailure(
                "OpenAI completed a Responses stream without output.",
                code="empty_completed_response",
            )
        usage = response.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        input_tokens = _non_negative_integer(usage.get("input_tokens"))
        output_tokens = _non_negative_integer(usage.get("output_tokens"))
        details = usage.get("input_tokens_details")
        details = details if isinstance(details, dict) else {}
        output_details = usage.get("output_tokens_details")
        output_details = output_details if isinstance(output_details, dict) else {}
        cached_tokens = _non_negative_integer(details.get("cached_tokens"))
        if cached_tokens is not None and input_tokens is not None:
            if cached_tokens <= input_tokens:
                # OpenAI-style Responses counts cached reads inside input_tokens;
                # Anthropic's input_tokens bucket is disjoint from cache reads.
                input_tokens -= cached_tokens
            else:
                # An impossible provider breakdown is less useful than omitting
                # the suspect cache field and preserving the reported total.
                cached_tokens = None
        elif cached_tokens is not None:
            # Without a valid total, the ledger's input estimate already covers
            # the prompt. Retaining cached reads would double-count that input.
            cached_tokens = None
        cache_write_tokens = _non_negative_integer(
            details.get("cache_write_tokens", usage.get("cache_write_tokens"))
        )
        if cache_write_tokens is None:
            cache_write_tokens = _non_negative_integer(
                usage.get("cache_creation_input_tokens")
            )
        self.usage_input_tokens = input_tokens
        self.usage_cache_read_tokens = cached_tokens
        self.usage_cache_write_tokens = cache_write_tokens
        self.usage_output_tokens = output_tokens
        self.usage_reasoning_tokens = _non_negative_integer(
            output_details.get("reasoning_tokens", usage.get("reasoning_tokens"))
        )
        reasoning = response.get("reasoning")
        reasoning = reasoning if isinstance(reasoning, dict) else {}
        effective_effort = reasoning.get("effort", response.get("reasoning_effort"))
        self.effective_reasoning_effort = (
            effective_effort.strip()
            if isinstance(effective_effort, str) and effective_effort.strip()
            else None
        )
        usage_fields: dict[str, int] = {}
        if cached_tokens is not None:
            usage_fields["cache_read_input_tokens"] = cached_tokens
        if cache_write_tokens is not None:
            usage_fields["cache_creation_input_tokens"] = cache_write_tokens
        stop_reason = "max_tokens" if incomplete else "end_turn"
        events.append(
            self.ledger.message_delta(
                self.ledger.final_stop_reason(stop_reason),
                output_tokens
                if output_tokens is not None
                else self.ledger.estimate_output_tokens(),
                input_tokens=input_tokens,
                usage_fields=usage_fields or None,
            )
        )
        events.append(self.ledger.message_stop())
        self.completed = True
        return events

    @property
    def tool_call_count(self) -> int:
        return len(self._tools)

    @property
    def complete_tool_calls(self) -> bool | None:
        if not self._tools:
            return None
        return all(
            state.arguments_complete and state.stopped for state in self._tools.values()
        )

    @property
    def valid_tool_json(self) -> bool | None:
        if not self._tools:
            return None
        return all(state.valid_arguments for state in self._tools.values())


def _stream_failure(data: dict[str, Any]) -> ResponsesStreamFailure:
    response = data.get("response")
    response = response if isinstance(response, dict) else {}
    error = response.get("error", data.get("error"))
    error = error if isinstance(error, dict) else {}
    message = error.get("message")
    code = error.get("code", error.get("type"))
    return ResponsesStreamFailure(
        message if isinstance(message, str) and message else "OpenAI response failed.",
        code=code if isinstance(code, str) else None,
    )


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _non_negative_integer(value: Any) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )
