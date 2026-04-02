"""Build-mode routes — terminal proxy and app preview proxy."""

from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, Request
from fastapi.responses import HTMLResponse, Response

from ..proxy import http_proxy, ws_proxy

router = APIRouter(prefix="/build")

# ---------------------------------------------------------------------------
# Build UI placeholder (issue #6 will flesh this out)
# ---------------------------------------------------------------------------

_BUILD_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Build: {team}/{app_slug}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0; background: #111; color: #eee; }}
    .header {{ padding: 1rem; background: #1a1a2e; border-bottom: 1px solid #333; }}
    .panes {{ display: flex; height: calc(100vh - 56px); }}
    .terminal, .preview {{ flex: 1; border: 1px solid #333; margin: 4px; display: flex;
      align-items: center; justify-content: center; font-size: 1.2rem; color: #888; }}
  </style>
</head>
<body>
  <div class="header">Build mode: {team}/{app_slug}</div>
  <div class="panes">
    <div class="terminal">[terminal placeholder]</div>
    <div class="preview">[preview placeholder]</div>
  </div>
</body>
</html>
"""


@router.get("/{team}/{app_slug}", response_class=HTMLResponse)
async def build_ui(team: str, app_slug: str) -> HTMLResponse:
    """Placeholder build UI page."""
    html = _BUILD_HTML_TEMPLATE.format(team=team, app_slug=app_slug)
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# WebSocket proxy — browser <-> build pod terminal
# ---------------------------------------------------------------------------


@router.websocket("/{team}/{app_slug}/ws")
async def build_ws(
    websocket: WebSocket,
    team: str,
    app_slug: str,
    pod_ip: str = Query(..., alias="pod_ip"),
) -> None:
    """Proxy WebSocket traffic to the build pod's Claude Code terminal.

    The *pod_ip* query parameter is required for now; real pod lookup will be
    wired in once the pod lifecycle manager (issue #4) is integrated.
    """
    await ws_proxy(websocket, pod_ip=pod_ip, pod_port=8080)


# ---------------------------------------------------------------------------
# HTTP proxy — app preview iframe
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}/preview/{path:path}")
async def build_preview(
    request: Request,
    team: str,
    app_slug: str,
    path: str,
    pod_ip: str = Query(..., alias="pod_ip"),
) -> Response:
    """Proxy HTTP requests to the build pod's app preview server."""
    return await http_proxy(
        request,
        pod_ip=pod_ip,
        pod_port=3000,
        path=f"/{path}",
    )
