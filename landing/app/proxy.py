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

from .identity import UserIdentity

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

# Identity headers are never forwarded verbatim: the ingress-injected values
# (Remote-*/X-Forwarded-*) are only trustworthy at the landing pod itself, and
# a caller that bypassed the ingress could forge them. The proxy strips all of
# these and instead injects verified X-SUS-* headers from the identity the
# landing app resolved (trusted-proxy check included).
_IDENTITY_HEADERS = frozenset(
    h.lower()
    for h in (
        "remote-user",
        "remote-groups",
        "remote-name",
        "remote-email",
        "x-forwarded-user",
        "x-forwarded-groups",
        "x-forwarded-name",
        "x-forwarded-email",
        "x-sus-user",
        "x-sus-groups",
        "x-sus-name",
        "x-sus-email",
    )
)


def build_proxy_headers(
    request_headers: Any,
    identity: UserIdentity | None = None,
) -> dict[str, str]:
    """Build outbound proxy headers: strip hop-by-hop, encoding, and all
    inbound identity headers; inject verified ``X-SUS-*`` identity.

    Apps behind the proxy read ``X-SUS-User`` (and ``-Groups``/``-Name``/
    ``-Email``) to personalise per-viewer. When no identity is supplied the
    guest values are injected so apps always see a consistent contract.
    """
    strip = _HOP_BY_HOP | {"host", "accept-encoding"} | _IDENTITY_HEADERS
    out: dict[str, str] = {
        k: v for k, v in request_headers.items() if k.lower() not in strip
    }
    out["X-SUS-User"] = identity.id if identity else "guest"
    out["X-SUS-Name"] = identity.display_name if identity else "Guest"
    groups = list(identity.groups or []) if identity else ["guest"]
    out["X-SUS-Groups"] = ",".join(groups)
    return out


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
    identity: UserIdentity | None = None,
) -> Response:
    """Forward an HTTP request to the build pod's app preview server.

    Proxies the incoming *request* to ``http://{pod_ip}:{pod_port}{path}``
    preserving method, headers, query string, and body.  Returns the
    upstream response with the same status, headers, and body.

    Inbound identity headers are always stripped; pass *identity* to inject
    the verified ``X-SUS-*`` headers so the app can personalise per-viewer.
    """
    target_url = f"http://{pod_ip}:{pod_port}{path}"
    if request.url.query:
        # Strip our own query params (pod_ip) before forwarding — but for
        # simplicity we forward the full query string for now.
        target_url = f"{target_url}?{request.url.query}"

    # Accept-Encoding is stripped so the backend sends uncompressed content,
    # avoiding Content-Length mismatches from httpx auto-decompression.
    out_headers = build_proxy_headers(request.headers, identity)

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
