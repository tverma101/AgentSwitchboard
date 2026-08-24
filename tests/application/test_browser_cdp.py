import json
from collections.abc import Mapping

import aiohttp
import httpx
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from free_claude_code.application.browser_cdp import (
    BrowserCdpError,
    ChromeCdpBrowserBridge,
)


class FakeCdpConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.closed = False

    async def call(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        self.calls.append((method, dict(params or {})))
        if method in {"Page.enable", "Runtime.enable"}:
            return {}
        if method == "Page.navigate":
            return {"frameId": "frame-1"}
        if method == "Runtime.evaluate":
            expression = str(self.calls[-1][1]["expression"])
            if "fcc-browser-snapshot" in expression:
                value = {
                    "ok": True,
                    "truncated": False,
                    "elements": [
                        {
                            "selector": "#go",
                            "tag": "button",
                            "role": "",
                            "type": "",
                            "label": "Go",
                            "text": "Go",
                        }
                    ],
                }
            elif "fcc-browser-query" in expression:
                value = {
                    "ok": True,
                    "count": 1,
                    "truncated": False,
                    "elements": [],
                }
            elif "fcc-browser-scroll" in expression:
                value = {"ok": True, "scroll_x": 0, "scroll_y": 400}
            else:
                value = {"ok": True, "tag": "button"}
            return {"result": {"value": value}}
        raise AssertionError(f"unexpected CDP method: {method}")

    async def close(self) -> None:
        self.closed = True


def _http_client(payload: object) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://127.0.0.1:9222/json/list")
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_local_cdp_bridge_lists_safe_tabs_and_performs_bounded_actions() -> None:
    client = _http_client(
        [
            {
                "id": "tab-1",
                "type": "page",
                "title": " Demo   page ",
                "url": "https://example.test/path?token=secret#fragment",
                "webSocketDebuggerUrl": ("ws://127.0.0.1:9222/devtools/page/tab-1"),
                "cookie": "must-not-be-returned",
            },
            {"id": "worker-1", "type": "service_worker"},
        ]
    )
    connections: list[FakeCdpConnection] = []

    async def connection_factory(url: str) -> FakeCdpConnection:
        assert url == "ws://127.0.0.1:9222/devtools/page/tab-1"
        connection = FakeCdpConnection()
        connections.append(connection)
        return connection

    bridge = ChromeCdpBrowserBridge(
        "http://127.0.0.1:9222",
        allow_existing_session=True,
        http_client=client,
        connection_factory=connection_factory,
    )
    try:
        assert await bridge.list_tabs() == (
            {
                "tab_id": "tab-1",
                "title": "Demo page",
                "url": "https://example.test/path",
                "type": "page",
            },
        )

        assert await bridge.snapshot_dom("tab-1") == {
            "tab_id": "tab-1",
            "url": "https://example.test/path",
            "elements": [
                {
                    "selector": "#go",
                    "tag": "button",
                    "role": "",
                    "type": "",
                    "label": "Go",
                    "text": "Go",
                }
            ],
            "truncated": False,
        }
        assert await bridge.perform(
            "tab-1", "navigate", {"url": "https://example.test/next?secret=hidden"}
        ) == {
            "tab_id": "tab-1",
            "action": "navigate",
            "url": "https://example.test/next",
            "frame_id": "frame-1",
        }
        assert await bridge.perform("tab-1", "click", {"selector": "#go"}) == {
            "tab_id": "tab-1",
            "action": "click",
            "selector": "#go",
            "tag": "button",
        }
        assert await bridge.perform(
            "tab-1", "type", {"selector": "#name", "text": "secret-input"}
        ) == {
            "tab_id": "tab-1",
            "action": "type",
            "selector": "#name",
            "characters": 12,
        }
        assert await bridge.perform("tab-1", "scroll", {"delta_y": 400}) == {
            "tab_id": "tab-1",
            "action": "scroll",
            "delta_x": 0,
            "delta_y": 400,
            "scroll_x": 0,
            "scroll_y": 400,
        }
        assert await bridge.perform("tab-1", "query", {"selector": "button"}) == {
            "tab_id": "tab-1",
            "action": "query",
            "selector": "button",
            "count": 1,
            "elements": [],
            "truncated": False,
        }
        assert len(connections) == 1
        assert [method for method, _ in connections[0].calls] == [
            "Page.enable",
            "Runtime.enable",
            "Runtime.evaluate",
            "Page.navigate",
            "Runtime.evaluate",
            "Runtime.evaluate",
            "Runtime.evaluate",
            "Runtime.evaluate",
        ]
        assert "secret-input" not in repr(
            await bridge.perform("tab-1", "type", {"selector": "#name", "text": ""})
        )
    finally:
        await bridge.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_existing_session_requires_explicit_opt_in_before_discovery() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    bridge = ChromeCdpBrowserBridge(
        "http://127.0.0.1:9222",
        http_client=client,
    )
    try:
        with pytest.raises(BrowserCdpError, match="explicit opt-in"):
            await bridge.list_tabs()
        with pytest.raises(BrowserCdpError, match="explicit opt-in"):
            await bridge.snapshot_dom("tab-1")
        assert called is False
    finally:
        await bridge.aclose()
        await client.aclose()


def test_cdp_and_websocket_urls_are_loopback_only() -> None:
    with pytest.raises(ValueError, match="loopback"):
        ChromeCdpBrowserBridge(
            "https://remote.example:9222",
            allow_existing_session=True,
        )
    with pytest.raises(ValueError, match="credentials"):
        ChromeCdpBrowserBridge(
            "http://user:password@127.0.0.1:9222",
            allow_existing_session=True,
        )


@pytest.mark.asyncio
async def test_remote_websocket_target_and_unsafe_actions_fail_closed() -> None:
    client = _http_client(
        [
            {
                "id": "tab-1",
                "type": "page",
                "title": "Remote",
                "url": "https://example.test",
                "webSocketDebuggerUrl": "ws://192.0.2.10:9222/devtools/page/tab-1",
            }
        ]
    )
    bridge = ChromeCdpBrowserBridge(
        "http://127.0.0.1:9222",
        allow_existing_session=True,
        http_client=client,
    )
    try:
        with pytest.raises(BrowserCdpError, match="loopback"):
            await bridge.list_tabs()
        with pytest.raises(BrowserCdpError, match="unsupported"):
            await bridge.perform("tab-1", "execute_javascript", {})
    finally:
        await bridge.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_aiohttp_cdp_transport_reuses_one_local_tab_connection() -> None:
    methods: list[str] = []

    async def cdp_handler(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        async for message in websocket:
            if message.type is not aiohttp.WSMsgType.TEXT:
                continue
            request_payload = json.loads(message.data)
            method = request_payload["method"]
            methods.append(method)
            if method == "Runtime.evaluate":
                result: Mapping[str, object] = {
                    "result": {
                        "type": "object",
                        "value": {
                            "ok": True,
                            "truncated": False,
                            "elements": [],
                        },
                    }
                }
            elif method == "Page.navigate":
                result = {"frameId": "frame-1"}
            else:
                result = {}
            await websocket.send_json({"id": request_payload["id"], "result": result})
        return websocket

    app = web.Application()
    app.router.add_get("/devtools/page/tab-1", cdp_handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    assert server.port is not None
    client = _http_client(
        [
            {
                "id": "tab-1",
                "type": "page",
                "title": "Local",
                "url": "about:blank",
                "webSocketDebuggerUrl": (
                    f"ws://127.0.0.1:{server.port}/devtools/page/tab-1"
                ),
            }
        ]
    )
    bridge = ChromeCdpBrowserBridge(
        "http://127.0.0.1:9222",
        allow_existing_session=True,
        http_client=client,
    )
    try:
        await bridge.list_tabs()
        assert await bridge.snapshot_dom("tab-1") == {
            "tab_id": "tab-1",
            "url": "about:blank",
            "elements": [],
            "truncated": False,
        }
        assert await bridge.perform("tab-1", "navigate", {"url": "about:blank"}) == {
            "tab_id": "tab-1",
            "action": "navigate",
            "url": "about:blank",
            "frame_id": "frame-1",
        }
        assert methods == [
            "Page.enable",
            "Runtime.enable",
            "Runtime.evaluate",
            "Page.navigate",
        ]
    finally:
        await bridge.aclose()
        await client.aclose()
        await server.close()
