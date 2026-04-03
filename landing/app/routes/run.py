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

    # Check published apps store first (MVP: build pod as run target).
    try:
        store = _get_published_store()
        published = store.get(team, app_slug)
        if published:
            pod_ip = published.get("pod_ip")
    except Exception:
        logger.exception("Failed to check published store for %s/%s", team, app_slug)

    # Fall back to dedicated run pod lookup.
    if not pod_ip:
        try:
            mgr = _get_run_pod_mgr()
            pod_info = mgr.find_run_pod(team, app_slug)
            if pod_info:
                pod_ip = pod_info.get("pod_ip")
        except Exception:
            logger.exception("Failed to look up run pod for %s/%s", team, app_slug)

    if not pod_ip:
        return Response(
            content="This app hasn't been published yet. Build it first!",
            status_code=503,
        )

    return await http_proxy(
        request,
        pod_ip=pod_ip,
        pod_port=3000,
        path=f"/{path}" if path else "/",
    )
