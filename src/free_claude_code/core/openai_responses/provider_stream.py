"""Translate upstream OpenAI Responses events into Anthropic Messages SSE."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from free_claude_code.core.anthropic.openai_tool_names import OpenAIToolNameCodec
from free_claude_code.core.anthropic.streaming import AnthropicStreamLedger
from free_claude_code.core.anthropic.streaming.recovery import continuation_suffix
from free_claude_code.core.anthropic.usage import reconcile_input_usage
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy


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
_MAX_TOKEN_INCOMPLETE_REASONS = frozenset({"max_output_tokens", "max_tokens"})


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
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> None:
        self.ledger = AnthropicStreamLedger(
            message_id,
            model,
            input_tokens,
            log_raw_events=log_raw_events,
        )
        self._input_tokens = input_tokens
        self._reasoning_output_enabled = reasoning.output_enabled
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
        self.incomplete_reason: str | None = None
        self.provider_reasoning_item = False
        self.provider_visible_reasoning_summary = False
        self.provider_visible_reasoning_summary_length: int | None = None
        self.provider_reasoning_text = False
        self.provider_opaque_reasoning = False
        self.opaque_reasoning_hash: str | None = None
        self.provider_refusal = False
        self.provider_refusal_length: int | None = None
        self.harness_thinking_block = False
        self.harness_thinking_delta = False
        self._tool_names = tool_names or OpenAIToolNameCodec.from_names(())
        self._tools: dict[str, _ToolState] = {}
        self._tool_items_by_call_id: dict[str, str] = {}
        self._duplicate_tool_item_ids: set[str] = set()
        self._encrypted_reasoning: dict[str, str] = {}
        self._output_item_ids_by_index: dict[int, str] = {}
        self._reasoning_text_by_key: dict[tuple[str, str, int], str] = {}
        self._output_text_by_key: dict[tuple[str, str, int], str] = {}
        self._refusal_text_by_key: dict[tuple[str, str, int], str] = {}
        self._emitted_opaque_reasoning: set[tuple[str, str]] = set()

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
        if event_type == "response.reasoning_text.done":
            return self._reasoning_done(data, summary=False)
        if event_type == "response.reasoning_summary_text.done":
            return self._reasoning_done(data, summary=True)
        if event_type == "response.reasoning_summary_part.added":
            return self._reasoning_part(data, final=False)
        if event_type == "response.reasoning_summary_part.done":
            return self._reasoning_part(data, final=True)
        if event_type == "response.output_text.delta":
            return self._text_delta(data)
        if event_type == "response.output_text.done":
            return self._text_done(data)
        if event_type == "response.refusal.delta":
            return self._refusal_delta(data)
        if event_type == "response.refusal.done":
            return self._refusal_done(data)
        if event_type == "response.content_part.done":
            return self._content_part_done(data)
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
        self._remember_output_item(
            item_id,
            _non_negative_integer(data.get("output_index")),
        )
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
            return self._reasoning_item(
                item,
                identity=item_id or self._output_identity(data),
                include_opaque=False,
            )
        return []

    def _reasoning_delta(self, data: dict[str, Any], *, summary: bool) -> list[str]:
        delta = data.get("delta")
        if not isinstance(delta, str) or not delta:
            return []
        return self._emit_reasoning_text(
            delta,
            summary=summary,
            identity=self._reasoning_identity(data),
            index=self._reasoning_index(data, summary=summary),
            final=False,
        )

    def _reasoning_done(self, data: dict[str, Any], *, summary: bool) -> list[str]:
        text = data.get("text")
        if not isinstance(text, str) or not text:
            return []
        return self._emit_reasoning_text(
            text,
            summary=summary,
            identity=self._reasoning_identity(data),
            index=self._reasoning_index(data, summary=summary),
            final=True,
        )

    def _reasoning_part(self, data: dict[str, Any], *, final: bool) -> list[str]:
        part = data.get("part")
        if not isinstance(part, dict) or part.get("type") != "summary_text":
            return []
        text = part.get("text")
        if not isinstance(text, str) or not text:
            return []
        return self._emit_reasoning_text(
            text,
            summary=True,
            identity=self._reasoning_identity(data),
            index=self._reasoning_index(data, summary=True),
            final=final,
        )

    def _reasoning_item(
        self,
        item: dict[str, Any],
        *,
        identity: str,
        include_opaque: bool,
    ) -> list[str]:
        if item.get("type") != "reasoning":
            return []
        self.provider_reasoning_item = True
        events: list[str] = []
        content = item.get("content")
        if isinstance(content, list):
            for index, part in enumerate(content):
                if not isinstance(part, dict) or part.get("type") != "reasoning_text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    events.extend(
                        self._emit_reasoning_text(
                            text,
                            summary=False,
                            identity=identity,
                            index=index,
                            final=True,
                        )
                    )
        summary = item.get("summary")
        if isinstance(summary, list):
            for index, part in enumerate(summary):
                if not isinstance(part, dict) or part.get("type") != "summary_text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    events.extend(
                        self._emit_reasoning_text(
                            text,
                            summary=True,
                            identity=identity,
                            index=index,
                            final=True,
                        )
                    )
        encrypted = item.get("encrypted_content")
        if isinstance(encrypted, str) and encrypted:
            self._remember_opaque_reasoning(identity, encrypted)
            if include_opaque:
                events.extend(self._emit_opaque_reasoning(identity, encrypted))
        return events

    def _emit_reasoning_text(
        self,
        text: str,
        *,
        summary: bool,
        identity: str,
        index: int,
        final: bool,
    ) -> list[str]:
        self.provider_reasoning_item = True
        key = ("summary" if summary else "text", identity, index)
        existing = self._reasoning_text_by_key.get(key, "")
        if final:
            emitted = continuation_suffix(existing, text)
            if emitted is None:
                # A final snapshot is authoritative. A provider should send it
                # as the streamed prefix plus a suffix, but preserving a
                # divergent snapshot is safer than silently dropping it.
                emitted = text
            self._reasoning_text_by_key[key] = text
        else:
            emitted = text
            self._reasoning_text_by_key[key] = existing + text

        if summary:
            self._refresh_summary_telemetry()
        else:
            self.provider_reasoning_text = True
        if not self._reasoning_output_enabled:
            return []
        if not emitted:
            return []

        events = list(self.ledger.ensure_thinking_block())
        self.harness_thinking_block = True
        events.append(self.ledger.emit_thinking_delta(emitted))
        self.harness_thinking_delta = True
        self.generated_output = True
        return events

    def _refresh_summary_telemetry(self) -> None:
        summary_length = sum(
            len(text)
            for (kind, _identity, _index), text in self._reasoning_text_by_key.items()
            if kind == "summary" and text
        )
        if summary_length:
            self.provider_visible_reasoning_summary = True
            self.provider_visible_reasoning_summary_length = summary_length

    def _output_identity(self, data: dict[str, Any]) -> str:
        item_id = _string(data.get("item_id")) or _string(data.get("id"))
        if item_id:
            return item_id
        output_index = _non_negative_integer(data.get("output_index"))
        if output_index is not None:
            return self._output_item_ids_by_index.get(
                output_index, f"output:{output_index}"
            )
        return "response"

    def _reasoning_identity(self, data: dict[str, Any]) -> str:
        return self._output_identity(data)

    @staticmethod
    def _reasoning_index(data: dict[str, Any], *, summary: bool) -> int:
        field = "summary_index" if summary else "content_index"
        return _non_negative_integer(data.get(field)) or 0

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
        return self._emit_visible_text(
            delta,
            kind="text",
            identity=self._output_identity(data),
            index=self._content_index(data),
            final=False,
        )

    def _text_done(self, data: dict[str, Any]) -> list[str]:
        text = data.get("text")
        if not isinstance(text, str) or not text:
            return []
        return self._emit_visible_text(
            text,
            kind="text",
            identity=self._output_identity(data),
            index=self._content_index(data),
            final=True,
        )

    def _refusal_delta(self, data: dict[str, Any]) -> list[str]:
        delta = data.get("delta")
        if not isinstance(delta, str) or not delta:
            return []
        return self._emit_visible_text(
            delta,
            kind="refusal",
            identity=self._output_identity(data),
            index=self._content_index(data),
            final=False,
        )

    def _refusal_done(self, data: dict[str, Any]) -> list[str]:
        text = data.get("refusal", data.get("text"))
        if not isinstance(text, str) or not text:
            return []
        return self._emit_visible_text(
            text,
            kind="refusal",
            identity=self._output_identity(data),
            index=self._content_index(data),
            final=True,
        )

    def _content_part_done(self, data: dict[str, Any]) -> list[str]:
        part = data.get("part")
        if not isinstance(part, dict):
            return []
        part_type = part.get("type")
        if part_type == "output_text":
            text = part.get("text")
            kind = "text"
        elif part_type == "refusal":
            text = part.get("refusal", part.get("text"))
            kind = "refusal"
        else:
            return []
        if not isinstance(text, str) or not text:
            return []
        return self._emit_visible_text(
            text,
            kind=kind,
            identity=self._output_identity(data),
            index=self._content_index(data),
            final=True,
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
        stores = {
            "text": self._output_text_by_key,
            "refusal": self._refusal_text_by_key,
        }
        store = stores[kind]
        key = (kind, identity, index)
        existing = store.get(key, "")
        if final:
            emitted = continuation_suffix(existing, text)
            if emitted is None:
                emitted = text
            store[key] = text
        else:
            emitted = text
            store[key] = existing + text
        if kind == "refusal":
            self.provider_refusal = True
            self.provider_refusal_length = sum(
                len(value)
                for (
                    _kind,
                    _identity,
                    _index,
                ), value in self._refusal_text_by_key.items()
                if value
            )
        if not emitted:
            return []
        events = list(self.ledger.ensure_text_block())
        events.append(self.ledger.emit_text_delta(emitted))
        self.generated_output = True
        return events

    @staticmethod
    def _content_index(data: dict[str, Any]) -> int:
        return _non_negative_integer(data.get("content_index")) or 0

    def _remember_output_item(self, item_id: str, output_index: int | None) -> None:
        if output_index is None:
            return
        previous = self._output_item_ids_by_index.get(output_index)
        synthetic = f"output:{output_index}"
        previous_identity = previous or synthetic
        identity = item_id or previous_identity
        self._output_item_ids_by_index[output_index] = identity
        if item_id and previous_identity != item_id:
            self._rekey_output_identity(previous_identity, item_id)
            self._output_item_ids_by_index[output_index] = item_id
        if not item_id:
            self._rekey_output_identity("response", identity)

    def _rekey_output_identity(self, previous: str, current: str) -> None:
        if previous == current:
            return
        for store in (
            self._reasoning_text_by_key,
            self._output_text_by_key,
            self._refusal_text_by_key,
        ):
            for key, value in list(store.items()):
                kind, identity, index = key
                if identity != previous:
                    continue
                replacement = (kind, current, index)
                if replacement not in store:
                    store[replacement] = value
                del store[key]
        for store in (self._encrypted_reasoning,):
            if previous in store and current not in store:
                store[current] = store[previous]
            store.pop(previous, None)
        self._emitted_opaque_reasoning = {
            (current if identity == previous else identity, digest)
            for identity, digest in self._emitted_opaque_reasoning
        }

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
        output_index = _non_negative_integer(data.get("output_index"))
        self._remember_output_item(item_id, output_index)
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
            identity = item_id or self._output_identity(data)
            encrypted = item.get("encrypted_content")
            if not isinstance(encrypted, str) or not encrypted:
                encrypted = self._encrypted_reasoning.get(identity)
                if encrypted:
                    item = {**item, "encrypted_content": encrypted}
            return self._reasoning_item(
                item,
                identity=identity,
                include_opaque=True,
            )
        if item_type == "message":
            return self._message_item(item, output_index=output_index)
        return []

    def _emit_opaque_reasoning(self, item_id: str, encrypted: str) -> list[str]:
        digest = hashlib.sha256(encrypted.encode("utf-8")).hexdigest()
        marker = (item_id, digest)
        if marker in self._emitted_opaque_reasoning:
            return []
        self._emitted_opaque_reasoning.add(marker)
        if not self._reasoning_output_enabled:
            return []
        events = list(self.ledger.close_content_blocks())
        index = self.ledger.blocks.allocate_index()
        events.append(
            self.ledger.content_block_start(index, "redacted_thinking", data=encrypted)
        )
        events.append(self.ledger.content_block_stop(index))
        self.generated_output = True
        self.harness_thinking_block = True
        return events

    def _message_item(
        self,
        item: dict[str, Any],
        *,
        output_index: int | None,
    ) -> list[str]:
        item_id = _string(item.get("id"))
        identity_data: dict[str, Any] = {"id": item_id}
        if output_index is not None:
            identity_data["output_index"] = output_index
        identity = self._output_identity(identity_data)
        content = item.get("content")
        if isinstance(content, str):
            content_parts: list[tuple[int, dict[str, Any]]] = [
                (0, {"type": "output_text", "text": content})
            ]
        elif isinstance(content, list):
            content_parts = [
                (content_index, part)
                for content_index, part in enumerate(content)
                if isinstance(part, dict)
            ]
        else:
            return []
        events: list[str] = []
        for content_index, part in content_parts:
            part_type = part.get("type")
            if part_type == "output_text":
                text = part.get("text")
                kind = "text"
            elif part_type == "refusal":
                text = part.get("refusal", part.get("text"))
                kind = "refusal"
            else:
                continue
            if isinstance(text, str) and text:
                events.extend(
                    self._emit_visible_text(
                        text,
                        kind=kind,
                        identity=identity,
                        index=content_index,
                        final=True,
                    )
                )
        return events

    def _capture_response_output(self, response: dict[str, Any]) -> list[str]:
        output = response.get("output")
        if not isinstance(output, list):
            return []
        events: list[str] = []
        for output_index, candidate in enumerate(output):
            if not isinstance(candidate, dict):
                continue
            candidate = {str(key): value for key, value in candidate.items()}
            item_id = _string(candidate.get("id"))
            self._remember_output_item(item_id, output_index)
            identity = self._output_identity(
                {"id": item_id, "output_index": output_index}
            )
            item_type = candidate.get("type")
            if item_type == "reasoning":
                events.extend(
                    self._reasoning_item(
                        candidate,
                        identity=identity,
                        include_opaque=True,
                    )
                )
            elif item_type == "message":
                events.extend(self._message_item(candidate, output_index=output_index))
        return events

    def _terminal_stop_reason(self, *, incomplete: bool) -> str:
        if self.provider_refusal:
            return "end_turn"
        if incomplete and self.incomplete_reason in _MAX_TOKEN_INCOMPLETE_REASONS:
            return "max_tokens"
        return "end_turn"

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
        details = response.get("incomplete_details")
        if not isinstance(details, dict):
            details = data.get("incomplete_details")
        details = details if isinstance(details, dict) else {}
        reason = details.get("reason")
        self.incomplete_reason = reason if isinstance(reason, str) else None
        for state in self._tools.values():
            self._validate_tool_arguments(state)
            if not state.stopped:
                raise ResponsesStreamFailure(
                    "OpenAI completed a function call without its output-item terminal.",
                    code="missing_tool_terminal",
                )
        events = self._capture_response_output(response)
        events.extend(self.ledger.close_all_blocks())
        if not self.generated_output or not self.ledger.has_content_block():
            raise ResponsesStreamFailure(
                "OpenAI completed a Responses stream without output.",
                code="empty_completed_response",
            )
        usage = response.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        reported_input_tokens = _first_non_negative_integer(
            usage.get("input_tokens"),
            usage.get("prompt_tokens"),
        )
        output_tokens = _non_negative_integer(usage.get("output_tokens"))
        detail_mappings = _usage_detail_mappings(usage)
        output_details = usage.get("output_tokens_details")
        output_details = output_details if isinstance(output_details, dict) else {}
        cached_tokens = _first_usage_counter(
            usage,
            detail_mappings,
            "cached_tokens",
            "cache_read_input_tokens",
            "prompt_cache_hit_tokens",
        )
        cache_write_tokens = _first_usage_counter(
            usage,
            detail_mappings,
            "cache_write_tokens",
            "cache_creation_input_tokens",
            "prompt_cache_write_tokens",
            "prompt_cache_creation_tokens",
            "cache_creation_tokens",
        )
        if reported_input_tokens is not None:
            reported_input_tokens, cached_tokens, cache_write_tokens = (
                _partition_reported_input_tokens(
                    reported_input_tokens,
                    cached_tokens,
                    cache_write_tokens,
                )
            )
        self.usage_input_tokens = reported_input_tokens
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
        client_input_tokens, usage_fields = reconcile_input_usage(
            self._input_tokens,
            usage_fields,
            fallback_input_tokens=reported_input_tokens,
        )
        stop_reason = self._terminal_stop_reason(incomplete=incomplete)
        events.append(
            self.ledger.message_delta(
                self.ledger.final_stop_reason(stop_reason),
                output_tokens
                if output_tokens is not None
                else self.ledger.estimate_output_tokens(),
                input_tokens=client_input_tokens,
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


def _first_non_negative_integer(*values: Any) -> int | None:
    for value in values:
        normalized = _non_negative_integer(value)
        if normalized is not None:
            return normalized
    return None


def _usage_detail_mappings(usage: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return Responses and OpenAI-compatible prompt detail mappings in order."""

    details: list[dict[str, Any]] = []
    for field_name in ("input_tokens_details", "prompt_tokens_details"):
        value = usage.get(field_name)
        if isinstance(value, dict):
            details.append(value)
    return tuple(details)


def _first_usage_counter(
    usage: dict[str, Any],
    detail_mappings: tuple[dict[str, Any], ...],
    *field_names: str,
) -> int | None:
    for details in detail_mappings:
        for field_name in field_names:
            value = _non_negative_integer(details.get(field_name))
            if value is not None:
                return value
    return _first_non_negative_integer(*(usage.get(name) for name in field_names))


def _partition_reported_input_tokens(
    total_input_tokens: int,
    cached_tokens: int | None,
    cache_write_tokens: int | None,
) -> tuple[int, int | None, int | None]:
    """Convert an inclusive provider total into disjoint cache buckets.

    OpenAI Responses reports both cache counters inside ``input_tokens``. The
    Anthropic usage contract reports them separately, so ordinary input is the
    remaining total after each valid counter. An impossible counter is omitted
    instead of allowing a malformed provider response to inflate usage.
    """

    ordinary = total_input_tokens
    normalized_cache_read = cached_tokens
    normalized_cache_write = cache_write_tokens
    if normalized_cache_read is not None:
        if normalized_cache_read <= ordinary:
            ordinary -= normalized_cache_read
        else:
            normalized_cache_read = None
    if normalized_cache_write is not None:
        if normalized_cache_write <= ordinary:
            ordinary -= normalized_cache_write
        else:
            normalized_cache_write = None
    return ordinary, normalized_cache_read, normalized_cache_write
