"""Run-mode routes — serve published apps via proxied run pods."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from ..proxy import http_proxy
from ..run_pods import RunPodManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/run")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# Lazy-initialised singleton
# ---------------------------------------------------------------------------

_run_pod_mgr: Optional[RunPodManager] = None


def _get_run_pod_mgr() -> RunPodManager:
    """Return the RunPodManager, creating it on first call."""
    global _run_pod_mgr  # noqa: PLW0603
    if _run_pod_mgr is None:
        _run_pod_mgr = RunPodManager()
    return _run_pod_mgr


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
    """Proxy HTTP requests to the run pod's app server.

    Looks up the run pod by team/app labels and forwards traffic to port 3000.
    Returns 503 if no run pod is available.
    """
    try:
        mgr = _get_run_pod_mgr()
        pod_info = mgr.find_run_pod(team, app_slug)
    except Exception:
        logger.exception("Failed to look up run pod for %s/%s", team, app_slug)
        return Response(content="Service Unavailable", status_code=503)

    if pod_info is None or not pod_info.get("pod_ip"):
        return Response(
            content="No run pod available for this application.",
            status_code=503,
        )

    return await http_proxy(
        request,
        pod_ip=pod_info["pod_ip"],
        pod_port=3000,
        path=f"/{path}" if path else "/",
    )
