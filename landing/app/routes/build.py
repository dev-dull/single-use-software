"""Build-mode routes — terminal proxy and app preview proxy."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from ..proxy import http_proxy, ws_proxy

router = APIRouter(prefix="/build")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# Build UI
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}", response_class=HTMLResponse)
async def build_ui(
    request: Request,
    team: str,
    app_slug: str,
    pod_ip: str = Query("", alias="pod_ip"),
) -> HTMLResponse:
    """Render the build-mode UI with terminal and preview panes."""
    return _templates.TemplateResponse(
        "build.html",
        {
            "request": request,
            "team": team,
            "app_slug": app_slug,
            "pod_ip": pod_ip,
        },
    )


# ---------------------------------------------------------------------------
# Heartbeat, Save, Publish
# ---------------------------------------------------------------------------


@router.post("/{team}/{app_slug}/heartbeat")
async def build_heartbeat(
    team: str,
    app_slug: str,
    pod_ip: str = Query("", alias="pod_ip"),
) -> JSONResponse:
    """Heartbeat endpoint to keep the build pod alive."""
    # TODO: wire to BuildPodManager.heartbeat(pod_name) once integrated
    return JSONResponse({"status": "ok"})


@router.post("/{team}/{app_slug}/save")
async def build_save(
    team: str,
    app_slug: str,
    pod_ip: str = Query("", alias="pod_ip"),
) -> JSONResponse:
    """Placeholder save endpoint."""
    return JSONResponse({"status": "saved"})


@router.post("/{team}/{app_slug}/publish")
async def build_publish(
    team: str,
    app_slug: str,
    pod_ip: str = Query("", alias="pod_ip"),
) -> JSONResponse:
    """Placeholder publish endpoint."""
    return JSONResponse({"status": "published"})


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
