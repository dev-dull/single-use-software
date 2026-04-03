"""Build-mode routes — terminal proxy and app preview proxy."""

from __future__ import annotations

import asyncio
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
            user_id = "anonymous"
            info = wf.start_session(user_id=user_id, team=team, app_slug=app_slug)
            pod_ip = info.get("pod_ip") or ""

            # Pod may still be scheduling — poll briefly for an IP.
            if not pod_ip and info.get("pod_name"):
                for _ in range(10):
                    await asyncio.sleep(2)
                    pod_info = wf._pods.get_build_pod(info["pod_name"])
                    if pod_info and pod_info.get("pod_ip"):
                        pod_ip = pod_info["pod_ip"]
                        break
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
            wf._sessions.update_last_seen(session["pod_name"])
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


# ---------------------------------------------------------------------------
# Terminal proxy — ttyd WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/{team}/{app_slug}/ws")
async def build_ws(
    websocket: WebSocket,
    team: str,
    app_slug: str,
    pod_ip: str = Query(..., alias="pod_ip"),
) -> None:
    """Proxy WebSocket traffic to ttyd running in the build pod."""
    await ws_proxy(websocket, pod_ip=pod_ip, pod_port=8080)


@router.websocket("/{team}/{app_slug}/terminal/ws")
async def build_terminal_ws(
    websocket: WebSocket,
    team: str,
    app_slug: str,
    pod_ip: str = Query(..., alias="pod_ip"),
) -> None:
    """Proxy ttyd WebSocket (ttyd JS connects to basePath/ws)."""
    await ws_proxy(websocket, pod_ip=pod_ip, pod_port=8080)


# ---------------------------------------------------------------------------
# Terminal proxy — ttyd HTTP assets and API
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}/terminal/token")
async def build_terminal_token(
    request: Request,
    team: str,
    app_slug: str,
    pod_ip: str = Query(..., alias="pod_ip"),
) -> Response:
    """Proxy ttyd token endpoint."""
    return await http_proxy(request, pod_ip=pod_ip, pod_port=8080, path="/token")


@router.get("/{team}/{app_slug}/terminal/{path:path}")
async def build_terminal(
    request: Request,
    team: str,
    app_slug: str,
    path: str,
    pod_ip: str = Query(..., alias="pod_ip"),
) -> Response:
    """Proxy HTTP requests to ttyd's web UI (HTML, JS, CSS assets)."""
    return await http_proxy(
        request,
        pod_ip=pod_ip,
        pod_port=8080,
        path=f"/{path}" if path else "/",
    )


# ---------------------------------------------------------------------------
# HTTP proxy — app preview iframe
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}/preview/{path:path}")
async def build_preview(
    request: Request,
    team: str,
    app_slug: str,
    path: str,
    pod_ip: str = Query("", alias="pod_ip"),
) -> Response:
    """Proxy HTTP requests to the build pod's app preview server.

    Falls back to serving static files from the baked-in apps directory
    so the preview shows the current app version before a server starts.
    Once the build pod's server is running, it always takes priority.
    """
    import os
    from pathlib import Path
    from fastapi.responses import FileResponse

    # Try the build pod's live server first — this is the app being developed.
    if pod_ip:
        try:
            resp = await http_proxy(request, pod_ip=pod_ip, pod_port=3000, path=f"/{path}")
            # 502 means the server isn't up yet — fall through to static.
            # Any other response (200, 404, 500) means the server IS running.
            if resp.status_code != 502:
                return resp
        except Exception:
            pass

    # Fall back to static files from the baked-in apps directory.
    apps_root = Path(os.environ.get("SUS_APPS_ROOT", "/repo/apps"))
    serve_path = path.strip("/") if path.strip("/") else "index.html"
    static_file = apps_root / team / app_slug / serve_path
    if static_file.is_file():
        # Serve with a header so the auto-refresh JS knows this is a fallback.
        resp = FileResponse(static_file)
        resp.headers["X-SUS-Fallback"] = "true"
        return resp

    return Response(content="No preview available yet.", status_code=503)
