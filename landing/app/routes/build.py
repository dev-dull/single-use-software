"""Build-mode routes — terminal proxy and app preview proxy."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from ..deps import get_identity_provider, resolve_identity
from ..git_workflow import GitWorkflowManager
from ..identity import UserIdentity
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
    app_name: str = Query("", alias="app_name"),
    app_description: str = Query("", alias="app_description"),
    identity: UserIdentity = Depends(resolve_identity),
) -> HTMLResponse:
    """Render the build-mode UI with terminal and preview panes.

    Starts (or resumes) a session so a build pod is spinning up, then renders
    immediately. The page shows a loading overlay and polls ``/status`` until
    the terminal is actually serving, so we never block the request on pod
    readiness and never bake a (soon-stale) pod IP into the page.
    """
    try:
        wf = _get_workflow()
        wf.start_session(
            user_id=identity.id, team=team, app_slug=app_slug,
            app_name=app_name, app_description=app_description,
        )
    except Exception:
        logger.exception("Failed to start build session for %s/%s", team, app_slug)

    return _templates.TemplateResponse(
        request,
        "build.html",
        context={
            "team": team,
            "app_slug": app_slug,
        },
    )


@router.get("/{team}/{app_slug}/status")
async def build_status(
    team: str,
    app_slug: str,
    identity: UserIdentity = Depends(resolve_identity),
) -> JSONResponse:
    """Report whether the session's build pod terminal is ready to display.

    ``ready`` is true only when the pod is running *and* ttyd answers on its
    terminal port. The pod IP is intentionally never returned — the front-end
    addresses the pod only through server-resolved proxy routes (see #80).
    """
    wf = _get_workflow()
    pod_ip = wf.resolve_pod_ip(identity.id, app_slug)
    if not pod_ip:
        return JSONResponse({"ready": False, "phase": "starting"})
    ready = await asyncio.to_thread(wf.is_terminal_ready, pod_ip)
    return JSONResponse({"ready": ready, "phase": "running" if ready else "starting"})


# ---------------------------------------------------------------------------
# Heartbeat, Save, Publish, Stop
# ---------------------------------------------------------------------------


@router.post("/{team}/{app_slug}/heartbeat")
async def build_heartbeat(
    team: str,
    app_slug: str,
    identity: UserIdentity = Depends(resolve_identity),
) -> JSONResponse:
    """Heartbeat endpoint to keep the build pod alive."""
    try:
        wf = _get_workflow()
        user_id = identity.id
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
    identity: UserIdentity = Depends(resolve_identity),
) -> JSONResponse:
    """Trigger a named save (git commit) in the build pod."""
    try:
        wf = _get_workflow()
        user_id = identity.id
        result = wf.save(user_id=user_id, team=team, app_slug=app_slug)
        return JSONResponse(result)
    except Exception:
        logger.exception("Save failed for %s/%s", team, app_slug)
        return JSONResponse({"status": "error"}, status_code=500)


@router.post("/{team}/{app_slug}/publish")
async def build_publish(
    team: str,
    app_slug: str,
    identity: UserIdentity = Depends(resolve_identity),
) -> JSONResponse:
    """Trigger a publish (PR creation) in the build pod."""
    try:
        wf = _get_workflow()
        user_id = identity.id
        result = wf.publish(user_id=user_id, team=team, app_slug=app_slug)
        return JSONResponse(result)
    except Exception:
        logger.exception("Publish failed for %s/%s", team, app_slug)
        return JSONResponse({"status": "error"}, status_code=500)


@router.post("/{team}/{app_slug}/stop")
async def build_stop(
    team: str,
    app_slug: str,
    identity: UserIdentity = Depends(resolve_identity),
) -> JSONResponse:
    """End the build session — delete the pod and clean up."""
    try:
        wf = _get_workflow()
        user_id = identity.id
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


async def _resolve_pod_ip_ws(websocket: WebSocket, app_slug: str) -> str | None:
    """Resolve the session's current pod IP for a WebSocket request.

    ``resolve`` only reads ``.headers``/``.client``, both of which a Starlette
    ``WebSocket`` provides, so the same identity provider works here.
    """
    identity = await get_identity_provider().resolve(websocket)
    return _get_workflow().resolve_pod_ip(identity.id, app_slug)


async def _proxy_terminal_ws(websocket: WebSocket, app_slug: str) -> None:
    pod_ip = await _resolve_pod_ip_ws(websocket, app_slug)
    if not pod_ip:
        # Pod not ready / gone — reject with "try again later" so the client
        # can reconnect once /status reports ready.
        await websocket.close(code=1013)
        return
    await ws_proxy(websocket, pod_ip=pod_ip, pod_port=8080)


@router.websocket("/{team}/{app_slug}/ws")
async def build_ws(websocket: WebSocket, team: str, app_slug: str) -> None:
    """Proxy WebSocket traffic to ttyd running in the build pod."""
    await _proxy_terminal_ws(websocket, app_slug)


@router.websocket("/{team}/{app_slug}/terminal/ws")
async def build_terminal_ws(websocket: WebSocket, team: str, app_slug: str) -> None:
    """Proxy ttyd WebSocket (ttyd JS connects to basePath/ws)."""
    await _proxy_terminal_ws(websocket, app_slug)


# ---------------------------------------------------------------------------
# Terminal proxy — ttyd HTTP assets and API
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}/terminal/token")
async def build_terminal_token(
    request: Request,
    team: str,
    app_slug: str,
    identity: UserIdentity = Depends(resolve_identity),
) -> Response:
    """Proxy ttyd token endpoint."""
    pod_ip = _get_workflow().resolve_pod_ip(identity.id, app_slug)
    if not pod_ip:
        return Response(status_code=503, content="build pod not ready")
    return await http_proxy(request, pod_ip=pod_ip, pod_port=8080, path="/token")


@router.get("/{team}/{app_slug}/terminal/{path:path}")
async def build_terminal(
    request: Request,
    team: str,
    app_slug: str,
    path: str,
    identity: UserIdentity = Depends(resolve_identity),
) -> Response:
    """Proxy HTTP requests to ttyd's web UI (HTML, JS, CSS assets)."""
    pod_ip = _get_workflow().resolve_pod_ip(identity.id, app_slug)
    if not pod_ip:
        return Response(status_code=503, content="build pod not ready")
    return await http_proxy(
        request,
        pod_ip=pod_ip,
        pod_port=8080,
        path=f"/{path}" if path else "/",
    )


# ---------------------------------------------------------------------------
# HTTP proxy — app preview iframe
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}/preview-hash")
async def build_preview_hash(
    team: str,
    app_slug: str,
    identity: UserIdentity = Depends(resolve_identity),
) -> JSONResponse:
    """Return a hash of the preview content for change detection."""
    import hashlib
    pod_ip = _get_workflow().resolve_pod_ip(identity.id, app_slug)
    if not pod_ip:
        return JSONResponse({"hash": ""})
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://{pod_ip}:3000/")
            if resp.status_code == 200:
                h = hashlib.md5(resp.content).hexdigest()[:12]
                return JSONResponse({"hash": h})
    except Exception:
        pass
    return JSONResponse({"hash": ""})


@router.api_route("/{team}/{app_slug}/preview/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def build_preview(
    request: Request,
    team: str,
    app_slug: str,
    path: str,
    identity: UserIdentity = Depends(resolve_identity),
) -> Response:
    """Proxy HTTP requests to the build pod's app preview server."""
    pod_ip = _get_workflow().resolve_pod_ip(identity.id, app_slug)
    if pod_ip:
        resp = await http_proxy(
            request, pod_ip=pod_ip, pod_port=3000, path=f"/{path}",
            identity=identity,
        )
        if resp.status_code != 502:
            return resp

    # Show a spinner while waiting for the app server to start.
    return HTMLResponse(
        content="""<!DOCTYPE html>
<html><head><style>
  body { display:flex; align-items:center; justify-content:center; height:100vh; margin:0;
         font-family:system-ui,sans-serif; background:#fafafa; color:#888; }
  .wrap { text-align:center; }
  .spinner { width:32px; height:32px; border:3px solid #e0e0e0; border-top:3px solid #2563eb;
             border-radius:50%; animation:spin .8s linear infinite; margin:0 auto 1rem; }
  @keyframes spin { to { transform:rotate(360deg); } }
  p { font-size:.9rem; }
</style></head><body>
  <div class="wrap"><div class="spinner"></div><p>Loading preview...</p></div>
</body></html>""",
        status_code=200,
    )
