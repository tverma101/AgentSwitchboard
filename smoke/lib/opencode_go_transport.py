"""Reproducible synthetic/live transport benchmark for OpenCode Go routes."""

import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from free_claude_code.config.provider_catalog import OPENCODE_GO_DEFAULT_BASE
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.opencode_go import (
    GoProtocol,
    OpenCodeGoProvider,
    build_native_messages_body,
    protocol_for_model,
)


@dataclass(frozen=True, slots=True)
class TransportBenchmarkConfig:
    """Benchmark inputs kept explicit so receipts are reproducible."""

    mode: str = "synthetic"
    model: str = "qwen3.7-plus"
    samples: tuple[int, ...] = (1, 100, 1000)
    response_bytes: int = 65_536
    output_path: Path = Path(".smoke-results/opencode-go-transport.json")
    base_url: str = OPENCODE_GO_DEFAULT_BASE
    proxy: str = ""


class SyntheticUpstream:
    """Small keep-alive HTTP/1.1 SSE server that isolates FCC transport cost."""

    def __init__(self, *, response_bytes: int) -> None:
        self.response_bytes = max(1, response_bytes)
        self.connections = 0
        self.requests = 0
        self.request_body_sizes: list[int] = []
        self._server: asyncio.Server | None = None

    @property
    def base_url(self) -> str:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("synthetic upstream is not running")
        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle,
            host="127.0.0.1",
            port=0,
        )

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.connections += 1
        try:
            while True:
                try:
                    header_bytes = await reader.readuntil(b"\r\n\r\n")
                except asyncio.IncompleteReadError, ConnectionError:
                    return
                if not header_bytes:
                    return
                header_lines = header_bytes.decode("latin-1").split("\r\n")
                request_line = header_lines[0].split(" ", 2)
                if len(request_line) != 3:
                    return
                path = request_line[1].split("?", 1)[0]
                headers = {
                    key.strip().lower(): value.strip()
                    for line in header_lines[1:]
                    if ":" in line
                    for key, value in (line.split(":", 1),)
                }
                content_length = int(headers.get("content-length", "0"))
                if content_length:
                    body = await reader.readexactly(content_length)
                else:
                    body = b""
                self.requests += 1
                self.request_body_sizes.append(len(body))
                response = self._response_body(path)
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"content-type: text/event-stream\r\n"
                    b"cache-control: no-cache\r\n"
                    b"transfer-encoding: chunked\r\n"
                    b"connection: keep-alive\r\n\r\n"
                )
                await writer.drain()
                for offset in range(0, len(response), 256):
                    chunk = response[offset : offset + 256]
                    writer.write(f"{len(chunk):x}\r\n".encode("ascii"))
                    writer.write(chunk)
                    writer.write(b"\r\n")
                    await writer.drain()
                writer.write(b"0\r\n\r\n")
                await writer.drain()
        except asyncio.IncompleteReadError, ConnectionError, BrokenPipeError:
            return
        finally:
            writer.close()
            await writer.wait_closed()

    def _response_body(self, path: str) -> bytes:
        text = "x" * self.response_bytes
        if path.endswith("/responses"):
            events = [
                _sse_frame(
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "item": {"type": "message", "id": "msg_synthetic"},
                    },
                ),
            ]
            events.extend(
                _sse_frame(
                    "response.output_text.delta",
                    {"type": "response.output_text.delta", "delta": part},
                )
                for part in _text_parts(text)
            )
            events.append(
                _sse_frame(
                    "response.completed",
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_synthetic",
                            "usage": {"input_tokens": 8, "output_tokens": 8},
                        },
                    },
                )
            )
        elif path.endswith("/chat/completions"):
            events = [_chat_frame(part) for part in _text_parts(text)]
            events.extend((_chat_frame("", finish_reason="stop"), "data: [DONE]\n\n"))
        else:
            events = [
                _sse_frame("message_start", {"type": "message_start"}),
            ]
            events.extend(
                _sse_frame(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": part},
                    },
                )
                for part in _text_parts(text)
            )
            events.append(_sse_frame("message_stop", {"type": "message_stop"}))
        return "".join(events).encode("utf-8")


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _chat_frame(text: str, *, finish_reason: str | None = None) -> str:
    payload = {
        "id": "chat_synthetic",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {"content": text},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _text_parts(text: str, size: int = 128) -> tuple[str, ...]:
    return tuple(text[offset : offset + size] for offset in range(0, len(text), size))


async def run_transport_benchmark(
    config: TransportBenchmarkConfig,
) -> dict[str, Any]:
    """Run one route benchmark and return a metadata-only JSON receipt."""

    if not config.samples or any(sample <= 0 for sample in config.samples):
        raise ValueError("samples must contain only positive counts")
    if sorted(config.samples) != list(config.samples):
        raise ValueError("samples must be sorted ascending")
    if config.mode not in {"synthetic", "live"}:
        raise ValueError("mode must be synthetic or live")
    if (
        config.mode == "live"
        and os.environ.get("FCC_OPENCODE_GO_BENCHMARK_LIVE") != "1"
    ):
        raise RuntimeError("live benchmark requires FCC_OPENCODE_GO_BENCHMARK_LIVE=1")
    if config.mode == "live" and not os.environ.get("OPENCODE_API_KEY"):
        raise RuntimeError("live benchmark requires OPENCODE_API_KEY")

    protocol = protocol_for_model(config.model)
    upstream: SyntheticUpstream | None = None
    base_url = config.base_url
    if config.mode == "synthetic":
        upstream = SyntheticUpstream(response_bytes=config.response_bytes)
        await upstream.start()
        base_url = upstream.base_url

    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key=os.environ.get("OPENCODE_API_KEY", "synthetic-key"),
            base_url=base_url,
            max_concurrency=2,
            proxy=config.proxy,
            http_read_timeout=30.0,
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_concurrency=2,
            base_delay=0.0,
            max_delay=0.0,
            jitter=0.0,
        ),
    )
    request = MessagesRequest.model_validate(
        {
            "model": config.model,
            "max_tokens": 128,
            "messages": [
                {
                    "role": "user",
                    "content": "synthetic transport benchmark request",
                }
            ],
        }
    )
    before_body = request.model_dump(mode="json", exclude_none=True)
    after_body = _route_body(provider, request, protocol)
    warmup_count = 2
    for sequence in range(1, warmup_count + 1):
        await _run_one(provider, request, sequence)
    idle_rss = _current_rss_bytes()
    baseline_requests = upstream.requests if upstream is not None else 0
    baseline_connections = upstream.connections if upstream is not None else 0
    baseline_body_count = (
        len(upstream.request_body_sizes) if upstream is not None else 0
    )
    samples: list[dict[str, Any]] = []
    rss_after: dict[str, int] = {}
    started_cpu = time.process_time()
    completed = 0
    try:
        for target in config.samples:
            while completed < target:
                completed += 1
                samples.append(
                    await _run_one(provider, request, warmup_count + completed)
                )
            rss_after[str(target)] = _current_rss_bytes()
    finally:
        await provider.cleanup()
        if upstream is not None:
            await upstream.close()
    cpu_seconds = max(0.0, time.process_time() - started_cpu)
    measured = samples
    requests = len(measured)
    if upstream is not None:
        connection_count = upstream.connections - baseline_connections
        upstream_requests = upstream.requests - baseline_requests
        connection_reuse = max(0, upstream_requests - connection_count)
        request_body_sizes = list(upstream.request_body_sizes[baseline_body_count:])
    else:
        connection_count = None
        upstream_requests = requests
        connection_reuse = None
        request_body_sizes = []
    raw_latencies = [sample["total_ms"] for sample in measured]
    raw_ttft = [sample["ttft_ms"] for sample in measured]
    peak_chunk = max((sample["max_chunk_bytes"] for sample in measured), default=0)
    receipt = {
        "schema_version": 1,
        "mode": config.mode,
        "commit_sha": _git_sha(),
        "environment": _environment_receipt(),
        "model": config.model,
        "protocol": protocol.value,
        "sample_counts": list(config.samples),
        "warmup_streams": warmup_count,
        "request_body_bytes_before": _json_size(before_body),
        "request_body_bytes_after": _json_size(after_body),
        "metrics": {
            "idle_rss_bytes": idle_rss,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": {
                key: value - idle_rss for key, value in rss_after.items()
            },
            "cpu_seconds": cpu_seconds,
            "cpu_seconds_per_measured_request": cpu_seconds / max(1, requests),
            "latency_ms": _summary(raw_latencies),
            "proxy_added_ttft_ms": _summary(raw_ttft),
            "peak_buffered_bytes_observed": peak_chunk,
            "full_success_response_buffered": False,
            "new_tcp_connections": connection_count,
            "connection_reuse_count": connection_reuse,
            "upstream_attempts": upstream_requests,
            "logical_requests": requests,
            "retry_amplification": upstream_requests / max(1, requests),
            "upstream_request_body_bytes": request_body_sizes,
        },
        "raw_samples": measured,
        "budgets": {
            "idle_rss_target_bytes": 100 * 1024 * 1024,
            "rss_growth_after_1000_target_bytes": 10 * 1024 * 1024,
            "local_ttft_p95_target_ms": 10.0,
            "healthy_retry_amplification": 1.0,
        },
        "command": "uv run python scripts/benchmark_opencode_go_transport.py",
    }
    return receipt


async def _run_one(
    provider: OpenCodeGoProvider,
    request: MessagesRequest,
    sequence: int,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    first_chunk_ns: int | None = None
    received_bytes = 0
    max_chunk_bytes = 0
    async for chunk in provider.stream_response(
        request,
        request_id=f"benchmark-{sequence}",
    ):
        now = time.perf_counter_ns()
        if first_chunk_ns is None:
            first_chunk_ns = now
        chunk_bytes = len(chunk.encode("utf-8", errors="replace"))
        received_bytes += chunk_bytes
        max_chunk_bytes = max(max_chunk_bytes, chunk_bytes)
    finished = time.perf_counter_ns()
    first = first_chunk_ns or finished
    return {
        "sequence": sequence,
        "ttft_ms": (first - started) / 1_000_000,
        "total_ms": (finished - started) / 1_000_000,
        "received_bytes": received_bytes,
        "max_chunk_bytes": max_chunk_bytes,
    }


def _route_body(
    provider: OpenCodeGoProvider,
    request: MessagesRequest,
    protocol: GoProtocol,
) -> dict[str, Any]:
    if protocol is GoProtocol.MESSAGES:
        return build_native_messages_body(request)
    if protocol is GoProtocol.RESPONSES:
        return provider._build_responses_body(
            request,
            reasoning=DEFAULT_REASONING_POLICY,
        )
    return provider._chat._build_request_body(request)


def write_receipt(receipt: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "raw": []}
    ordered = sorted(values)
    return {
        "count": len(values),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
        "raw": values,
    }


def _percentile(ordered: list[float], fraction: float) -> float:
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def _json_size(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except OSError, subprocess.CalledProcessError:
        return None


def _environment_receipt() -> dict[str, Any]:
    uv_version: str | None = None
    with suppress(OSError, subprocess.CalledProcessError):
        uv_version = subprocess.check_output(
            ["uv", "--version"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    return {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "ram_bytes": _ram_bytes(),
        "python": sys.version,
        "uv": uv_version,
    }


def _ram_bytes() -> int | None:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except AttributeError, OSError, ValueError:
        return None


def _current_rss_bytes() -> int:
    try:
        output = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return int(output.strip()) * 1024
    except OSError, ValueError, subprocess.CalledProcessError:
        return 0
