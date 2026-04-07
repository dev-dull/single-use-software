"""Run-mode routes — serve published apps via proxied run pods."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from ..proxy import http_proxy
from ..published_apps import PublishedAppStore
from ..run_pods import RunPodManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/run")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# Lazy-initialised singleton
# ---------------------------------------------------------------------------

_run_pod_mgr: Optional[RunPodManager] = None
_published_store: Optional[PublishedAppStore] = None


def _get_run_pod_mgr() -> RunPodManager:
    global _run_pod_mgr
    if _run_pod_mgr is None:
        _run_pod_mgr = RunPodManager()
    return _run_pod_mgr


def _get_published_store() -> PublishedAppStore:
    global _published_store
    if _published_store is None:
        _published_store = PublishedAppStore()
    return _published_store


# ---------------------------------------------------------------------------
# Run UI
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}", response_class=HTMLResponse)
async def run_ui(
    request: Request,
    team: str,
    app_slug: str,
) -> HTMLResponse:
    """Render the run-mode page with the app in a full-page iframe."""
    return _templates.TemplateResponse(
        request,
        "run.html",
        context={
            "team": team,
            "app_slug": app_slug,
        },
    )


# ---------------------------------------------------------------------------
# HTTP proxy — run pod app traffic
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}/proxy/{path:path}")
async def run_proxy(
    request: Request,
    team: str,
    app_slug: str,
    path: str,
) -> Response:
    """Proxy HTTP requests to the published app.

    First checks the published apps store (MVP: proxies to the build pod).
    Falls back to looking for a dedicated run pod by labels.
    Returns 503 if no serving endpoint is available.
    """
    pod_ip = None

    # 1. Check published apps store (MVP: build pod as run target).
    try:
        store = _get_published_store()
        published = store.get(team, app_slug)
        if published:
            pod_ip = published.get("pod_ip")
    except Exception:
        logger.exception("Failed to check published store for %s/%s", team, app_slug)

    # 2. Fall back to dedicated run pod lookup.
    if not pod_ip:
        try:
            mgr = _get_run_pod_mgr()
            pod_info = mgr.find_run_pod(team, app_slug)
            if pod_info:
                pod_ip = pod_info.get("pod_ip")
        except Exception:
            logger.exception("Failed to look up run pod for %s/%s", team, app_slug)

    # Try proxying to the pod. If it fails (stale IP, deleted pod), clear
    # pod_ip and fall through to static file serving.
    if pod_ip:
        try:
            resp = await http_proxy(
                request,
                pod_ip=pod_ip,
                pod_port=3000,
                path=f"/{path}" if path else "/",
            )
            if resp.status_code != 502:
                return resp
            logger.warning("502 from pod_ip %s for %s/%s — falling through to static files", pod_ip, team, app_slug)
        except Exception:
            logger.warning("Stale pod_ip %s for %s/%s — falling through to static files", pod_ip, team, app_slug)

    # 3. Fall back to serving static files from the repo clone (for static apps).
    from ..repo_sync import get_apps_root
    app_dir = get_apps_root() / team / app_slug
    serve_path = path.strip("/") if path.strip("/") else "index.html"
    static_file = app_dir / serve_path
    if static_file.is_file():
        from fastapi.responses import FileResponse
        return FileResponse(static_file)

    # 4. App exists in the repo but no run pod and no static files —
    # auto-create a run pod from the build pod image.
    sus_json = app_dir / "sus.json"
    if sus_json.is_file():
        try:
            import os, asyncio
            mgr = _get_run_pod_mgr()
            build_image = os.environ.get("SUS_BUILD_IMAGE", "")
            if build_image:
                logger.info("Auto-creating run pod for %s/%s", team, app_slug)
                run_info = mgr.create_run_pod(team=team, app_slug=app_slug, image=build_image)
                run_pod_name = run_info["name"]
                # Wait for the pod to get an IP and be ready.
                for _ in range(15):
                    await asyncio.sleep(2)
                    info = mgr.get_run_pod(run_pod_name)
                    if info and info.get("pod_ip") and info.get("phase") == "Running":
                        pod_ip = info["pod_ip"]
                        break

                if pod_ip:
                    # Record in published store so subsequent requests skip auto-create.
                    try:
                        store = _get_published_store()
                        store.publish(
                            team=team, app_slug=app_slug,
                            pod_ip=pod_ip, pod_name=run_pod_name,
                            published_by="auto",
                        )
                    except Exception:
                        pass

                    # Give the app a moment to start serving.
                    for _ in range(10):
                        try:
                            resp = await http_proxy(
                                request, pod_ip=pod_ip, pod_port=3000,
                                path=f"/{path}" if path else "/",
                            )
                            if resp.status_code != 502:
                                return resp
                        except Exception:
                            pass
                        await asyncio.sleep(2)
        except Exception:
            logger.exception("Failed to auto-create run pod for %s/%s", team, app_slug)

    return Response(
        content="This app hasn't been published yet. Build it first!",
        status_code=503,
    )
