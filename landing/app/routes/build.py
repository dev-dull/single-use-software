"""Build-mode routes — terminal proxy and app preview proxy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from ..git_workflow import GitWorkflowManager
from ..pods import BuildPodManager
from ..proxy import http_proxy, ws_proxy
from ..sessions import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/build")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# Lazy-initialised singletons
# ---------------------------------------------------------------------------

_workflow: Optional[GitWorkflowManager] = None


def _get_workflow() -> GitWorkflowManager:
    """Return the GitWorkflowManager, creating it on first call.

    BuildPodManager needs a working K8s config which may not be available at
    import time, so we defer initialisation until the first request.
    """
    global _workflow  # noqa: PLW0603
    if _workflow is None:
        pod_mgr = BuildPodManager()
        session_store = SessionStore()
        _workflow = GitWorkflowManager(pod_mgr, session_store)
    return _workflow


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
    """Render the build-mode UI with terminal and preview panes.

    If no *pod_ip* is provided, start (or resume) a session so the user always
    lands on a running build pod.
    """
    if not pod_ip:
        try:
            wf = _get_workflow()
            # TODO: replace hardcoded user_id with real auth
            user_id = "anonymous"
            info = wf.start_session(user_id=user_id, team=team, app_slug=app_slug)
            pod_ip = info.get("pod_ip") or ""
        except Exception:
            logger.exception("Failed to start build session for %s/%s", team, app_slug)
            pod_ip = ""

    return _templates.TemplateResponse(
        request,
        "build.html",
        context={
            "team": team,
            "app_slug": app_slug,
            "pod_ip": pod_ip,
        },
    )


# ---------------------------------------------------------------------------
# Heartbeat, Save, Publish, Stop
# ---------------------------------------------------------------------------


@router.post("/{team}/{app_slug}/heartbeat")
async def build_heartbeat(
    team: str,
    app_slug: str,
    pod_ip: str = Query("", alias="pod_ip"),
) -> JSONResponse:
    """Heartbeat endpoint to keep the build pod alive."""
    try:
        wf = _get_workflow()
        # TODO: replace hardcoded user_id with real auth
        user_id = "anonymous"
        session = wf._sessions.get(user_id, app_slug)
        if session:
            wf._pods.heartbeat(session["pod_name"])
    except Exception:
        logger.exception("Heartbeat failed for %s/%s", team, app_slug)
    return JSONResponse({"status": "ok"})


@router.post("/{team}/{app_slug}/save")
async def build_save(
    team: str,
    app_slug: str,
    pod_ip: str = Query("", alias="pod_ip"),
) -> JSONResponse:
    """Trigger a named save (git commit) in the build pod."""
    try:
        wf = _get_workflow()
        # TODO: replace hardcoded user_id with real auth
        user_id = "anonymous"
        result = wf.save(user_id=user_id, team=team, app_slug=app_slug)
        return JSONResponse(result)
    except Exception:
        logger.exception("Save failed for %s/%s", team, app_slug)
        return JSONResponse({"status": "error"}, status_code=500)


@router.post("/{team}/{app_slug}/publish")
async def build_publish(
    team: str,
    app_slug: str,
    pod_ip: str = Query("", alias="pod_ip"),
) -> JSONResponse:
    """Trigger a publish (PR creation) in the build pod."""
    try:
        wf = _get_workflow()
        # TODO: replace hardcoded user_id with real auth
        user_id = "anonymous"
        result = wf.publish(user_id=user_id, team=team, app_slug=app_slug)
        return JSONResponse(result)
    except Exception:
        logger.exception("Publish failed for %s/%s", team, app_slug)
        return JSONResponse({"status": "error"}, status_code=500)


@router.post("/{team}/{app_slug}/stop")
async def build_stop(
    team: str,
    app_slug: str,
) -> JSONResponse:
    """End the build session — delete the pod and clean up."""
    try:
        wf = _get_workflow()
        # TODO: replace hardcoded user_id with real auth
        user_id = "anonymous"
        wf.end_session(user_id=user_id, team=team, app_slug=app_slug)
        return JSONResponse({"status": "stopped"})
    except Exception:
        logger.exception("Stop failed for %s/%s", team, app_slug)
        return JSONResponse({"status": "error"}, status_code=500)


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
