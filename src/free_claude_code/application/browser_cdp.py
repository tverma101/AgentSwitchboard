"""Local-only Chrome/Chromium CDP browser bridge."""

import asyncio
import ipaddress
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

import aiohttp
import httpx

from .tool_planes import BrowserBridgePort, LocalToolError

_LOOPBACK_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_MAX_DOM_ELEMENTS = 80
_MAX_QUERY_ELEMENTS = 20
_MAX_TEXT_LENGTH = 160
_MAX_TYPE_LENGTH = 10_000
_MAX_SCROLL_DELTA = 100_000
_CDP_TIMEOUT_SECONDS = 10.0


class BrowserCdpError(LocalToolError):
    """Raised when a local CDP request is rejected or unavailable."""


class CdpAction(StrEnum):
    """The intentionally narrow deterministic action surface."""

    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    QUERY = "query"


class CdpConnection(Protocol):
    """Minimal serialized CDP connection used by the bridge."""

    async def call(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]: ...

    async def close(self) -> None: ...


CdpConnectionFactory = Callable[[str], Awaitable[CdpConnection]]


@dataclass(frozen=True, slots=True)
class _Tab:
    tab_id: str
    websocket_url: str
    title: str
    url: str


class ChromeCdpBrowserBridge(BrowserBridgePort):
    """Implement the BrowserBridgePort contract over a local CDP endpoint.

    The adapter only attaches to an already-running browser. Because a CDP
    endpoint exposes the browser session that owns it, callers must explicitly
    pass ``allow_existing_session=True``. This class never launches a browser,
    selects a profile, or makes a model/provider request.
    """

    def __init__(
        self,
        cdp_url: str,
        *,
        allow_existing_session: bool = False,
        http_client: httpx.AsyncClient | None = None,
        connection_factory: CdpConnectionFactory | None = None,
        timeout_seconds: float = _CDP_TIMEOUT_SECONDS,
    ) -> None:
        self._cdp_url = _validate_cdp_http_url(cdp_url)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number")
        self._allow_existing_session = allow_existing_session
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._connection_factory = connection_factory or self._connect_aiohttp
        self._ws_session: aiohttp.ClientSession | None = None
        self._tabs: dict[str, _Tab] = {}
        self._connections: dict[str, CdpConnection] = {}
        self._closed = False

    async def list_tabs(self) -> Sequence[Mapping[str, object]]:
        """List page targets without exposing raw CDP endpoint metadata."""

        self._ensure_ready()
        self._ensure_existing_session_opt_in()
        payload = await self._discover_tabs()
        tabs: dict[str, _Tab] = {}
        public_tabs: list[Mapping[str, object]] = []
        for item in payload:
            if not isinstance(item, Mapping) or item.get("type") != "page":
                continue
            tab_id = item.get("id")
            websocket_url = item.get("webSocketDebuggerUrl")
            if not isinstance(tab_id, str) or not tab_id.strip():
                continue
            if not isinstance(websocket_url, str) or not websocket_url.strip():
                raise BrowserCdpError("CDP page target has no WebSocket endpoint")
            safe_websocket_url = _validate_cdp_websocket_url(websocket_url)
            title = _bounded_public_text(item.get("title"))
            url = _safe_page_url(item.get("url"))
            tab = _Tab(tab_id, safe_websocket_url, title, url)
            tabs[tab_id] = tab
            public_tabs.append(
                {
                    "tab_id": tab_id,
                    "title": title,
                    "url": url,
                    "type": "page",
                }
            )

        for tab_id in set(self._connections) - set(tabs):
            await self._close_connection(tab_id)
        self._tabs = tabs
        return tuple(public_tabs)

    async def snapshot_dom(self, tab_id: str) -> Mapping[str, object]:
        """Return a bounded interactive DOM description, never raw HTML."""

        self._ensure_ready()
        self._ensure_existing_session_opt_in()
        tab = await self._tab(tab_id)
        result = await self._evaluate(
            tab_id,
            _DOM_SNAPSHOT_EXPRESSION,
        )
        return {
            "tab_id": tab.tab_id,
            "url": tab.url,
            "elements": result.get("elements", []),
            "truncated": bool(result.get("truncated", False)),
        }

    async def perform(
        self,
        tab_id: str,
        action: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Perform one deterministic browser action without arbitrary JS."""

        self._ensure_ready()
        self._ensure_existing_session_opt_in()
        try:
            selected_action = CdpAction(action.strip().lower())
        except (AttributeError, ValueError) as exc:
            supported = ", ".join(item.value for item in CdpAction)
            raise BrowserCdpError(
                f"unsupported browser action; supported actions: {supported}"
            ) from exc

        tab = await self._tab(tab_id)
        if selected_action is CdpAction.NAVIGATE:
            return await self._navigate(tab, arguments)
        if selected_action is CdpAction.CLICK:
            return await self._click(tab, arguments)
        if selected_action is CdpAction.TYPE:
            return await self._type(tab, arguments)
        if selected_action is CdpAction.SCROLL:
            return await self._scroll(tab, arguments)
        return await self._query(tab, arguments)

    async def aclose(self) -> None:
        """Close local CDP connections and clients owned by this adapter."""

        if self._closed:
            return
        self._closed = True
        for tab_id in tuple(self._connections):
            await self._close_connection(tab_id)
        if self._ws_session is not None:
            await self._ws_session.close()
            self._ws_session = None
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _discover_tabs(self) -> list[Mapping[str, object]]:
        client = self._get_http_client()
        try:
            response = await client.get(
                _json_list_url(self._cdp_url),
                timeout=self._timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise BrowserCdpError("local CDP tab discovery failed") from exc
        if not isinstance(payload, list):
            raise BrowserCdpError("local CDP tab discovery returned an invalid list")
        return [item for item in payload if isinstance(item, Mapping)]

    async def _tab(self, tab_id: str) -> _Tab:
        if not isinstance(tab_id, str) or not tab_id.strip():
            raise BrowserCdpError("tab_id must be a non-empty string")
        tab = self._tabs.get(tab_id)
        if tab is None:
            await self.list_tabs()
            tab = self._tabs.get(tab_id)
        if tab is None:
            raise BrowserCdpError("requested browser tab was not found")
        return tab

    async def _connection(self, tab: _Tab) -> CdpConnection:
        connection = self._connections.get(tab.tab_id)
        if connection is not None:
            return connection
        try:
            connection = await self._connection_factory(tab.websocket_url)
            await connection.call("Page.enable")
            await connection.call("Runtime.enable")
        except BrowserCdpError:
            raise
        except Exception as exc:
            if connection is not None:
                await connection.close()
            raise BrowserCdpError("local CDP WebSocket connection failed") from exc
        self._connections[tab.tab_id] = connection
        return connection

    async def _call(
        self,
        tab: _Tab,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        connection = await self._connection(tab)
        try:
            return await connection.call(method, params)
        except BrowserCdpError:
            raise
        except Exception as exc:
            await self._close_connection(tab.tab_id)
            raise BrowserCdpError(f"local CDP method {method!r} failed") from exc

    async def _evaluate(
        self,
        tab_id: str,
        expression: str,
    ) -> Mapping[str, object]:
        tab = await self._tab(tab_id)
        payload = await self._call(
            tab,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": False,
            },
        )
        if payload.get("exceptionDetails") is not None:
            raise BrowserCdpError("browser DOM evaluation failed")
        remote_result = payload.get("result")
        if not isinstance(remote_result, Mapping):
            raise BrowserCdpError("browser DOM evaluation returned no result")
        value = remote_result.get("value")
        if not isinstance(value, Mapping):
            raise BrowserCdpError("browser DOM evaluation returned invalid data")
        if value.get("ok") is False:
            error_code = value.get("error")
            if isinstance(error_code, str) and error_code in {
                "element_not_found",
                "invalid_selector",
                "not_editable",
            }:
                raise BrowserCdpError(f"browser action failed: {error_code}")
            raise BrowserCdpError("browser DOM action failed")
        return {str(key): item for key, item in value.items()}

    async def _navigate(
        self,
        tab: _Tab,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        url = _required_string(arguments, "url")
        safe_url = _validate_navigation_url(url)
        result = await self._call(tab, "Page.navigate", {"url": safe_url})
        if isinstance(result.get("errorText"), str) and result["errorText"]:
            raise BrowserCdpError("browser navigation failed")
        frame_id = result.get("frameId")
        response: dict[str, object] = {
            "tab_id": tab.tab_id,
            "action": CdpAction.NAVIGATE.value,
            "url": _safe_page_url(safe_url),
        }
        if isinstance(frame_id, str) and frame_id:
            response["frame_id"] = frame_id
        return response

    async def _click(
        self,
        tab: _Tab,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        selector = _required_string(arguments, "selector")
        result = await self._evaluate(tab.tab_id, _click_expression(selector))
        return {
            "tab_id": tab.tab_id,
            "action": CdpAction.CLICK.value,
            "selector": selector,
            "tag": result.get("tag", ""),
        }

    async def _type(
        self,
        tab: _Tab,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        selector = _required_string(arguments, "selector")
        text = arguments.get("text")
        if not isinstance(text, str):
            raise BrowserCdpError("browser type argument 'text' must be a string")
        if len(text) > _MAX_TYPE_LENGTH:
            raise BrowserCdpError("browser type text exceeds the bounded limit")
        await self._evaluate(tab.tab_id, _type_expression(selector, text))
        return {
            "tab_id": tab.tab_id,
            "action": CdpAction.TYPE.value,
            "selector": selector,
            "characters": len(text),
        }

    async def _scroll(
        self,
        tab: _Tab,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        delta_x = _bounded_number(arguments.get("delta_x", 0), "delta_x")
        delta_y = _bounded_number(arguments.get("delta_y", 0), "delta_y")
        selector = arguments.get("selector")
        if selector is not None and not isinstance(selector, str):
            raise BrowserCdpError("browser scroll argument 'selector' must be a string")
        result = await self._evaluate(
            tab.tab_id,
            _scroll_expression(selector, delta_x, delta_y),
        )
        response: dict[str, object] = {
            "tab_id": tab.tab_id,
            "action": CdpAction.SCROLL.value,
            "delta_x": delta_x,
            "delta_y": delta_y,
        }
        for key in ("scroll_x", "scroll_y"):
            if isinstance(result.get(key), int | float) and not isinstance(
                result.get(key), bool
            ):
                response[key] = result[key]
        return response

    async def _query(
        self,
        tab: _Tab,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        selector = _required_string(arguments, "selector")
        result = await self._evaluate(tab.tab_id, _query_expression(selector))
        return {
            "tab_id": tab.tab_id,
            "action": CdpAction.QUERY.value,
            "selector": selector,
            "count": result.get("count", 0),
            "elements": result.get("elements", []),
            "truncated": bool(result.get("truncated", False)),
        }

    async def _close_connection(self, tab_id: str) -> None:
        connection = self._connections.pop(tab_id, None)
        if connection is not None:
            await connection.close()

    async def _connect_aiohttp(self, websocket_url: str) -> CdpConnection:
        session = await self._get_ws_session()
        try:
            websocket = await session.ws_connect(
                websocket_url,
                timeout=aiohttp.ClientWSTimeout(
                    **{"ws_receive": self._timeout_seconds}
                ),
                autoping=True,
                autoclose=True,
                max_msg_size=2 * 1024 * 1024,
            )
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise BrowserCdpError("local CDP WebSocket connection failed") from exc
        return _AiohttpCdpConnection(websocket, self._timeout_seconds)

    async def _get_ws_session(self) -> aiohttp.ClientSession:
        if self._ws_session is None:
            self._ws_session = aiohttp.ClientSession()
        return self._ws_session

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(follow_redirects=False)
        return self._http_client

    def _ensure_ready(self) -> None:
        if self._closed:
            raise BrowserCdpError("browser CDP bridge is closed")

    def _ensure_existing_session_opt_in(self) -> None:
        if not self._allow_existing_session:
            raise BrowserCdpError(
                "existing browser sessions require explicit opt-in: "
                "allow_existing_session=True"
            )


class _AiohttpCdpConnection:
    """Serialize CDP calls over one aiohttp WebSocket per page target."""

    def __init__(self, websocket: aiohttp.ClientWebSocketResponse, timeout: float):
        self._websocket = websocket
        self._timeout = timeout
        self._next_id = 0
        self._lock = asyncio.Lock()

    async def call(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        async with self._lock:
            self._next_id += 1
            request_id = self._next_id
            try:
                await self._websocket.send_json(
                    {
                        "id": request_id,
                        "method": method,
                        "params": dict(params or {}),
                    }
                )
                while True:
                    message = await self._websocket.receive(timeout=self._timeout)
                    if message.type is aiohttp.WSMsgType.TEXT:
                        payload = json.loads(message.data)
                        if not isinstance(payload, Mapping):
                            raise BrowserCdpError("CDP returned an invalid message")
                        if payload.get("id") != request_id:
                            continue
                        error = payload.get("error")
                        if error is not None:
                            raise BrowserCdpError(f"CDP method {method!r} failed")
                        result = payload.get("result", {})
                        if not isinstance(result, Mapping):
                            raise BrowserCdpError("CDP returned an invalid result")
                        return {str(key): item for key, item in result.items()}
                    if message.type in {
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.ERROR,
                    }:
                        raise BrowserCdpError("CDP WebSocket closed unexpectedly")
                    if message.type is aiohttp.WSMsgType.BINARY:
                        raise BrowserCdpError("CDP returned a binary message")
            except BrowserCdpError:
                raise
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as exc:
                raise BrowserCdpError(f"CDP method {method!r} failed") from exc

    async def close(self) -> None:
        await self._websocket.close()


def _validate_cdp_http_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("CDP URL must be a non-empty string")
    parsed = urlsplit(url)
    _validate_url_parts(parsed, schemes={"http", "https"}, label="CDP")
    if parsed.query or parsed.fragment:
        raise ValueError("CDP URL cannot contain a query or fragment")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _validate_cdp_websocket_url(url: str) -> str:
    parsed = urlsplit(url)
    try:
        _validate_url_parts(parsed, schemes={"ws", "wss"}, label="CDP WebSocket")
    except ValueError as exc:
        raise BrowserCdpError(str(exc)) from exc
    if parsed.query or parsed.fragment:
        raise BrowserCdpError("CDP WebSocket URL cannot contain a query or fragment")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def _validate_url_parts(parsed: SplitResult, *, schemes: set[str], label: str) -> None:
    if parsed.scheme not in schemes or not parsed.hostname:
        raise ValueError(f"{label} URL must use a supported scheme and host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} URL cannot contain credentials")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} URL has an invalid port") from exc
    if not _is_loopback_host(parsed.hostname):
        raise ValueError(f"{label} URL must target loopback")


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized in _LOOPBACK_HOST_NAMES:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _json_list_url(cdp_url: str) -> str:
    parsed = urlsplit(cdp_url)
    path = f"{parsed.path.rstrip('/')}/json/list"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _safe_page_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        if parsed.scheme == "about":
            return f"about:{parsed.path}" if parsed.path else "about"
        return parsed.scheme if parsed.scheme in {"chrome", "file"} else ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    netloc = host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _bounded_public_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:_MAX_TEXT_LENGTH]


def _validate_navigation_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme in {"http", "https"}:
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise BrowserCdpError("browser navigation URL must not contain credentials")
        return url
    if url in {"about:blank", "about:srcdoc"}:
        return url
    raise BrowserCdpError("browser navigation supports only http(s) or about pages")


def _required_string(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise BrowserCdpError(
            f"browser action argument {name!r} must be a non-empty string"
        )
    return value


def _bounded_number(value: object, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BrowserCdpError(f"browser scroll argument {name!r} must be numeric")
    if not math.isfinite(value) or abs(value) > _MAX_SCROLL_DELTA:
        raise BrowserCdpError(
            f"browser scroll argument {name!r} exceeds the bounded limit"
        )
    return value


def _js_literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _click_expression(selector: str) -> str:
    return f"""
(() => {{
  const element = document.querySelector({_js_literal(selector)});
  if (!element) return {{ok: false, error: "element_not_found"}};
  element.click();
  return {{ok: true, tag: element.tagName.toLowerCase()}};
}})()
/* fcc-browser-click */
"""


def _type_expression(selector: str, text: str) -> str:
    return f"""
(() => {{
  const element = document.querySelector({_js_literal(selector)});
  if (!element) return {{ok: false, error: "element_not_found"}};
  if (!("value" in element) && !element.isContentEditable) {{
    return {{ok: false, error: "not_editable"}};
  }}
  if (element.isContentEditable) {{
    element.textContent = {_js_literal(text)};
  }} else {{
    const prototype = Object.getPrototypeOf(element);
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (descriptor && descriptor.set) descriptor.set.call(element, {_js_literal(text)});
    else element.value = {_js_literal(text)};
  }}
  element.dispatchEvent(new Event("input", {{bubbles: true}}));
  element.dispatchEvent(new Event("change", {{bubbles: true}}));
  return {{ok: true}};
}})()
/* fcc-browser-type */
"""


def _scroll_expression(
    selector: str | None,
    delta_x: int | float,
    delta_y: int | float,
) -> str:
    target = (
        "window"
        if selector is None
        else "document.querySelector(" + _js_literal(selector) + ")"
    )
    return f"""
(() => {{
  const target = {target};
  if (!target) return {{ok: false, error: "element_not_found"}};
  if (target === window) window.scrollBy({_js_literal(delta_x)}, {_js_literal(delta_y)});
  else target.scrollBy({_js_literal(delta_x)}, {_js_literal(delta_y)});
  return {{ok: true, scroll_x: target === window ? window.scrollX : target.scrollLeft,
    scroll_y: target === window ? window.scrollY : target.scrollTop}};
}})()
/* fcc-browser-scroll */
"""


def _query_expression(selector: str) -> str:
    return _element_query_expression(selector, _MAX_QUERY_ELEMENTS, "query")


def _element_query_expression(selector: str, limit: int, marker: str) -> str:
    return f"""
(() => {{
  const selector = {_js_literal(selector)};
  let nodes;
  try {{
    nodes = Array.from(document.querySelectorAll(selector));
  }} catch (_) {{
    return {{ok: false, error: "invalid_selector"}};
  }}
  const bounded = nodes.slice(0, {limit});
  const cssPath = (element) => {{
    if (element.id && window.CSS && CSS.escape) return "#" + CSS.escape(element.id);
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && current !== document.body) {{
      let index = 1;
      let sibling = current;
      while ((sibling = sibling.previousElementSibling)) {{
        if (sibling.tagName === current.tagName) index += 1;
      }}
      parts.unshift(current.tagName.toLowerCase() + ":nth-of-type(" + index + ")");
      current = current.parentElement;
    }}
    return parts.length ? parts.join(" > ") : "body";
  }};
  const describe = (element) => {{
    const tag = element.tagName.toLowerCase();
    const formControl = /^(input|textarea|select)$/.test(tag) || element.isContentEditable;
    const text = formControl ? "" : (element.innerText || element.textContent || "")
      .replace(/\\s+/g, " ").trim().slice(0, {_MAX_TEXT_LENGTH});
    return {{
      selector: cssPath(element),
      tag,
      role: element.getAttribute("role") || "",
      type: element.getAttribute("type") || "",
      label: (element.getAttribute("aria-label") || element.getAttribute("title") || "")
        .slice(0, {_MAX_TEXT_LENGTH}),
      text,
    }};
  }};
  return {{ok: true, count: nodes.length, truncated: nodes.length > {limit},
    elements: bounded.map(describe)}};
}})()
/* fcc-browser-{marker} */
"""


_DOM_SNAPSHOT_EXPRESSION = _element_query_expression(
    "a,button,input,textarea,select,summary,[role='button'],[role='link'],[contenteditable='true']",
    _MAX_DOM_ELEMENTS,
    "snapshot",
)
