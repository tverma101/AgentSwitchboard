"""Local Anthropic SSE fixtures for zero-provider Claude CLI smoke tests."""

import json
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class SyntheticThinkingFixture(StrEnum):
    """Thinking and continuation shapes served by the local fixture."""

    TEXT = "text"
    VISIBLE_SUMMARY = "visible_summary"
    VISIBLE_THINKING = "visible_thinking"
    EMPTY_THINKING = "empty_thinking"
    EMPTY_THINKING_SIGNATURE = "empty_thinking_signature"
    REDACTED_THINKING = "redacted_thinking"
    INTERLEAVED_THINKING = "interleaved_thinking"
    LATE_SIGNATURE = "late_signature"
    MALFORMED_SIGNATURE = "malformed_signature"
    UNKNOWN_DELTA = "unknown_delta"
    UNSUPPORTED_THINKING = "unsupported_thinking"
    USAGE_ONLY = "usage_only"
    TOOL_ROUNDTRIP = "tool_roundtrip"
    THINKING_TOOL_ROUNDTRIP = "thinking_tool_roundtrip"
    INTERLEAVED_TOOL_ROUNDTRIP = "interleaved_tool_roundtrip"
    OPAQUE_TOOL_ROUNDTRIP = "opaque_tool_roundtrip"


@dataclass(slots=True)
class SyntheticAnthropicGateway:
    """Serve deterministic Anthropic Messages SSE without external egress.

    The gateway intentionally stores only request bodies in memory while the
    context manager is active. ``request_receipts`` exposes structural fields
    and never returns prompt text, tool arguments, or opaque thinking data.
    """

    fixture: SyntheticThinkingFixture = SyntheticThinkingFixture.VISIBLE_THINKING
    requests: list[dict[str, Any]] = field(default_factory=list)
    _server: ThreadingHTTPServer | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def base_url(self) -> str:
        """Return the local provider root expected by the OpenCode adapter."""

        if self._server is None:
            raise RuntimeError("synthetic gateway is not running")
        port = int(self._server.server_address[1])
        return f"http://127.0.0.1:{port}/v1"

    def __enter__(self) -> SyntheticAnthropicGateway:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                if self.path.rstrip("/").endswith("/models"):
                    payload = {
                        "object": "list",
                        "data": [
                            {
                                "id": "minimax-m2.7",
                                "object": "model",
                                "owned_by": "synthetic-local",
                            }
                        ],
                    }
                    self._write_json(HTTPStatus.OK, payload)
                    return
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

            def do_POST(self) -> None:
                if not self.path.rstrip("/").endswith("/messages"):
                    self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                length = int(self.headers.get("content-length", "0"))
                raw_body = self.rfile.read(length)
                body = json.loads(raw_body) if raw_body else {}
                if not isinstance(body, dict):
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "request body must be an object"},
                    )
                    return
                with gateway._lock:
                    gateway.requests.append(body)
                    request_index = len(gateway.requests)
                self.send_response(HTTPStatus.OK)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "close")
                self.end_headers()
                try:
                    for event in gateway.events_for_request(request_index, body):
                        self.wfile.write(event.encode("utf-8"))
                        self.wfile.flush()
                except OSError:
                    return

            def _write_json(self, status: HTTPStatus, payload: object) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="fcc-synthetic-anthropic-gateway",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def events_for_request(
        self, request_index: int, request: dict[str, Any]
    ) -> tuple[str, ...]:
        """Return one deterministic SSE fixture without inspecting prompt text."""

        if (
            self.fixture
            in {
                SyntheticThinkingFixture.TOOL_ROUNDTRIP,
                SyntheticThinkingFixture.THINKING_TOOL_ROUNDTRIP,
                SyntheticThinkingFixture.INTERLEAVED_TOOL_ROUNDTRIP,
                SyntheticThinkingFixture.OPAQUE_TOOL_ROUNDTRIP,
            }
            and request_index == 1
            and not _contains_tool_result(request)
        ):
            if self.fixture is SyntheticThinkingFixture.OPAQUE_TOOL_ROUNDTRIP:
                return _opaque_tool_use_events()
            if self.fixture is SyntheticThinkingFixture.THINKING_TOOL_ROUNDTRIP:
                return _thinking_tool_use_events()
            if self.fixture is SyntheticThinkingFixture.INTERLEAVED_TOOL_ROUNDTRIP:
                return _interleaved_tool_use_events()
            return _tool_use_events()
        if self.fixture is SyntheticThinkingFixture.EMPTY_THINKING:
            return _empty_thinking_events()
        if self.fixture is SyntheticThinkingFixture.EMPTY_THINKING_SIGNATURE:
            return _empty_thinking_events(signature="synthetic-opaque-signature")
        if self.fixture is SyntheticThinkingFixture.REDACTED_THINKING:
            return _redacted_thinking_events()
        if self.fixture is SyntheticThinkingFixture.INTERLEAVED_THINKING:
            return _interleaved_thinking_events()
        if self.fixture is SyntheticThinkingFixture.LATE_SIGNATURE:
            return _thinking_text_events(signature="synthetic-signature")
        if self.fixture is SyntheticThinkingFixture.MALFORMED_SIGNATURE:
            return _thinking_text_events(signature="")
        if self.fixture is SyntheticThinkingFixture.UNKNOWN_DELTA:
            return _thinking_text_events(unknown_delta=True)
        if self.fixture is SyntheticThinkingFixture.VISIBLE_SUMMARY:
            return _thinking_text_events(
                thinking="synthetic visible summary",
                text="SYNTHETIC_SUMMARY_OK",
            )
        if self.fixture is SyntheticThinkingFixture.VISIBLE_THINKING:
            return _thinking_text_events()
        if self.fixture is SyntheticThinkingFixture.UNSUPPORTED_THINKING:
            return _text_events("SYNTHETIC_UNSUPPORTED_THINKING_OK")
        if self.fixture is SyntheticThinkingFixture.USAGE_ONLY:
            return _usage_only_events()
        return _text_events(
            "SYNTHETIC_TOOL_CONTINUATION"
            if self.fixture
            in {
                SyntheticThinkingFixture.TOOL_ROUNDTRIP,
                SyntheticThinkingFixture.THINKING_TOOL_ROUNDTRIP,
                SyntheticThinkingFixture.INTERLEAVED_TOOL_ROUNDTRIP,
                SyntheticThinkingFixture.OPAQUE_TOOL_ROUNDTRIP,
            }
            else "SYNTHETIC_TEXT"
        )

    def request_receipts(self) -> tuple[dict[str, object], ...]:
        """Return structural request evidence with all user values removed."""

        with self._lock:
            return tuple(_request_receipt(request) for request in self.requests)


def fixture_names() -> tuple[str, ...]:
    """Return stable CLI/report names for the complete synthetic matrix."""

    return tuple(fixture.value for fixture in SyntheticThinkingFixture)


def _event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _message_start() -> str:
    return _event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_synthetic_fixture",
                "type": "message",
                "role": "assistant",
                "model": "minimax-m2.7",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 3, "output_tokens": 0},
            },
        },
    )


def _message_end(stop_reason: str = "end_turn") -> tuple[str, ...]:
    return (
        _event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"input_tokens": 3, "output_tokens": 7},
            },
        ),
        _event("message_stop", {"type": "message_stop"}),
    )


def _text_events(text: str) -> tuple[str, ...]:
    return (
        _message_start(),
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        _event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        _event("content_block_stop", {"type": "content_block_stop", "index": 0}),
        *_message_end(),
    )


def _thinking_block_events(
    index: int,
    thinking: str,
    *,
    emit_delta: bool = True,
    signature: str | None = None,
    unknown_delta: bool = False,
) -> tuple[str, ...]:
    events = [
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "thinking", "thinking": ""},
            },
        )
    ]
    if emit_delta:
        events.append(
            _event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "thinking_delta", "thinking": thinking},
                },
            )
        )
    if signature is not None:
        events.append(
            _event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "signature_delta", "signature": signature},
                },
            )
        )
    if unknown_delta:
        events.append(
            _event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "synthetic_additive_delta", "value": "ignored"},
                },
            )
        )
    events.append(
        _event("content_block_stop", {"type": "content_block_stop", "index": index})
    )
    return tuple(events)


def _text_block_events(index: int, text: str) -> tuple[str, ...]:
    return (
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        _event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        _event("content_block_stop", {"type": "content_block_stop", "index": index}),
    )


def _tool_use_block_events(index: int) -> tuple[str, ...]:
    return (
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_synthetic_read",
                    "name": "Read",
                    "input": {},
                },
            },
        ),
        _event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"file_path":"synthetic-fixture.txt"}',
                },
            },
        ),
        _event("content_block_stop", {"type": "content_block_stop", "index": index}),
    )


def _thinking_text_events(
    *,
    thinking: str = "synthetic thought",
    text: str = "SYNTHETIC_THINKING_OK",
    signature: str | None = None,
    unknown_delta: bool = False,
) -> tuple[str, ...]:
    events = [_message_start()]
    events.extend(
        _thinking_block_events(
            0,
            thinking,
            emit_delta=bool(thinking),
            signature=signature,
            unknown_delta=unknown_delta,
        )
    )
    events.extend(_text_block_events(1, text))
    events.extend(_message_end())
    return tuple(events)


def _empty_thinking_events(*, signature: str | None = None) -> tuple[str, ...]:
    events = [_message_start()]
    events.extend(_thinking_block_events(0, "", emit_delta=False, signature=signature))
    events.extend(_text_block_events(1, "SYNTHETIC_EMPTY_THINKING_OK"))
    events.extend(_message_end())
    return tuple(events)


def _usage_only_events() -> tuple[str, ...]:
    return (
        _message_start(),
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        _event("content_block_stop", {"type": "content_block_stop", "index": 0}),
        *_message_end(),
    )


def _redacted_thinking_events() -> tuple[str, ...]:
    return (
        _message_start(),
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "redacted_thinking", "data": "opaque"},
            },
        ),
        _event("content_block_stop", {"type": "content_block_stop", "index": 0}),
        *_message_end(),
    )


def _interleaved_thinking_events() -> tuple[str, ...]:
    events: list[str] = [_message_start()]
    events.extend(_thinking_block_events(0, "first synthetic thought"))
    events.extend(_text_block_events(1, "SYNTHETIC_INTERLEAVE"))
    events.extend(_thinking_block_events(2, "second synthetic thought"))
    events.extend(_message_end())
    return tuple(events)


def _tool_use_events() -> tuple[str, ...]:
    return (
        _message_start(),
        *_tool_use_block_events(0),
        *_message_end("tool_use"),
    )


def _thinking_tool_use_events() -> tuple[str, ...]:
    return (
        _message_start(),
        *_thinking_block_events(0, "synthetic thought before tool"),
        *_tool_use_block_events(1),
        *_message_end("tool_use"),
    )


def _interleaved_tool_use_events() -> tuple[str, ...]:
    return (
        _message_start(),
        *_thinking_block_events(0, "first synthetic thought"),
        *_tool_use_block_events(1),
        *_thinking_block_events(2, "second synthetic thought"),
        *_message_end("tool_use"),
    )


def _opaque_tool_use_events() -> tuple[str, ...]:
    return (
        _message_start(),
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "redacted_thinking", "data": "opaque"},
            },
        ),
        _event("content_block_stop", {"type": "content_block_stop", "index": 0}),
        *_tool_use_block_events(1),
        *_message_end("tool_use"),
    )


def _contains_tool_result(request: MappingLike) -> bool:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for message in messages
        if isinstance(message, dict)
        for block in _content_blocks(message.get("content"))
    )


def _content_blocks(content: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(content, list):
        return ()
    return tuple(
        block
        for raw_block in content
        if (block := _coerce_block(raw_block)) is not None
    )


def _coerce_block(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    block: dict[str, Any] = {}
    for key, item in value.items():
        block[str(key)] = item
    return block


MappingLike = dict[str, Any]


def _request_receipt(request: MappingLike) -> dict[str, object]:
    messages = request.get("messages")
    roles: list[str] = []
    block_types: list[str] = []
    for message in messages if isinstance(messages, list) else ():
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if isinstance(role, str):
            roles.append(role)
        block_types.extend(
            block["type"]
            for block in _content_blocks(message.get("content"))
            if isinstance(block, dict) and isinstance(block.get("type"), str)
        )
    return {
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "roles": roles,
        "content_block_types": block_types,
        "tool_result_seen": "tool_result" in block_types,
        "thinking_history_seen": "thinking" in block_types
        or "redacted_thinking" in block_types,
        "tools_declared": isinstance(request.get("tools"), list)
        and bool(request["tools"]),
        "model": request.get("model")
        if isinstance(request.get("model"), str)
        else None,
    }


__all__ = [
    "SyntheticAnthropicGateway",
    "SyntheticThinkingFixture",
    "fixture_names",
]
