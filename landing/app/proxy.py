"""WebSocket and HTTP reverse proxy for build pod connections."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Hop-by-hop headers that must NOT be forwarded through an HTTP proxy.
_HOP_BY_HOP = frozenset(
    h.lower()
    for h in (
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    )
)


# ---------------------------------------------------------------------------
# WebSocket reverse proxy
# ---------------------------------------------------------------------------


async def ws_proxy(
    websocket: WebSocket,
    pod_ip: str,
    pod_port: int = 8080,
) -> None:
    """Bidirectional WebSocket proxy between the browser and a build pod.

    Accepts *websocket* from the browser, opens a second WebSocket to the
    build pod at ``ws://{pod_ip}:{pod_port}``, and relays messages in both
    directions until either side closes or an error occurs.
    """
    # Accept with the subprotocol the browser requested (e.g. "tty" for ttyd).
    requested_protocols = websocket.headers.get("sec-websocket-protocol", "").split(",")
    requested_protocols = [p.strip() for p in requested_protocols if p.strip()]
    accept_protocol = requested_protocols[0] if requested_protocols else None
    await websocket.accept(subprotocol=accept_protocol)

    backend_url = f"ws://{pod_ip}:{pod_port}/ws"
    backend_ws: Any = None

    try:
        backend_ws = await websockets.connect(
            backend_url,
            subprotocols=requested_protocols or None,
        )
    except Exception:
        logger.exception("Failed to connect to backend at %s", backend_url)
        await websocket.close(code=1011, reason="backend unavailable")
        return

    async def _browser_to_pod() -> None:
        """Relay messages from the browser to the build pod."""
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if "text" in msg:
                    await backend_ws.send(msg["text"])
                elif "bytes" in msg:
                    await backend_ws.send(msg["bytes"])
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("Error relaying browser -> pod")

    async def _pod_to_browser() -> None:
        """Relay messages from the build pod to the browser."""
        try:
            async for raw in backend_ws:
                if isinstance(raw, bytes):
                    await websocket.send_bytes(raw)
                else:
                    await websocket.send_text(raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception:
            logger.exception("Error relaying pod -> browser")

    browser_task = asyncio.create_task(_browser_to_pod())
    pod_task = asyncio.create_task(_pod_to_browser())

    try:
        # Wait for either direction to finish — then tear down the other.
        _done, pending = await asyncio.wait(
            {browser_task, pod_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        # Best-effort cleanup of both connections.
        try:
            await backend_ws.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HTTP reverse proxy
# ---------------------------------------------------------------------------


async def http_proxy(
    request: Request,
    pod_ip: str,
    pod_port: int = 3000,
    path: str = "/",
) -> Response:
    """Forward an HTTP request to the build pod's app preview server.

    Proxies the incoming *request* to ``http://{pod_ip}:{pod_port}{path}``
    preserving method, headers, query string, and body.  Returns the
    upstream response with the same status, headers, and body.
    """
    target_url = f"http://{pod_ip}:{pod_port}{path}"
    if request.url.query:
        # Strip our own query params (pod_ip) before forwarding — but for
        # simplicity we forward the full query string for now.
        target_url = f"{target_url}?{request.url.query}"

    # Build outbound headers, stripping hop-by-hop and encoding headers.
    # We strip Accept-Encoding so the backend sends uncompressed content,
    # avoiding Content-Length mismatches from httpx auto-decompression.
    _STRIP_REQUEST = _HOP_BY_HOP | {"host", "accept-encoding"}
    out_headers: dict[str, str] = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _STRIP_REQUEST
    }

    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            upstream = await client.request(
                method=request.method,
                url=target_url,
                headers=out_headers,
                content=body,
            )
        except httpx.RequestError:
            logger.exception("HTTP proxy request to %s failed", target_url)
            return Response(
                content="Bad Gateway",
                status_code=502,
            )

    # Filter hop-by-hop and encoding headers from upstream response.
    # Content-Length may be stale if httpx decompressed, so we let
    # Starlette recalculate it from the actual body.
    _STRIP_RESPONSE = _HOP_BY_HOP | {"content-length", "content-encoding"}
    resp_headers: dict[str, str] = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _STRIP_RESPONSE
    }

    # Disable browser caching on all proxied responses.
    resp_headers["cache-control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp_headers["pragma"] = "no-cache"
    resp_headers["expires"] = "0"

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=resp_headers,
    )
