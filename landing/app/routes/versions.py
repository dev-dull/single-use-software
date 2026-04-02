"""Version management routes — history view and rollback."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..run_pods import RunPodManager
from ..versions import VersionTracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/versions")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

_tracker = VersionTracker()


# ---------------------------------------------------------------------------
# HTML — version history page
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}", response_class=HTMLResponse)
async def version_history(request: Request, team: str, app_slug: str) -> HTMLResponse:
    """Render the version history page for an app."""
    versions = _tracker.get_versions(team, app_slug)
    return templates.TemplateResponse(
        request,
        "versions.html",
        context={
            "team": team,
            "app_slug": app_slug,
            "versions": versions,
        },
    )


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


@router.get("/api/{team}/{app_slug}")
async def api_versions(team: str, app_slug: str) -> JSONResponse:
    """Return version list as JSON."""
    versions = _tracker.get_versions(team, app_slug)
    return JSONResponse(content=versions)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


@router.post("/{team}/{app_slug}/rollback/{version}")
async def rollback(team: str, app_slug: str, version: int) -> JSONResponse:
    """Roll back to a specific version.

    1. Look up the version record to get the image_tag.
    2. Delete the current run pod.
    3. Create a new run pod with the old image.
    4. Update the active version in the tracker.
    """
    target = _tracker.get_version(team, app_slug, version)
    if target is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Version {version} not found for {team}/{app_slug}"},
        )

    image_tag = target["image_tag"]
    logger.info(
        "Rolling back %s/%s to version %d (image: %s)",
        team,
        app_slug,
        version,
        image_tag,
    )

    try:
        rpm = RunPodManager()

        # Tear down existing run pod.
        existing = rpm.find_run_pod(team, app_slug)
        if existing:
            logger.info("Deleting current run pod %s", existing["name"])
            rpm.delete_run_pod(existing["name"])

        # Create a new run pod with the rollback image.
        pod_info = rpm.create_run_pod(team=team, app_slug=app_slug, image=image_tag)

        # Mark this version as active.
        _tracker.set_active(team, app_slug, version)

        logger.info(
            "Rollback complete — %s/%s now at version %d, pod %s",
            team,
            app_slug,
            version,
            pod_info["name"],
        )

        return JSONResponse(
            content={
                "status": "rolled_back",
                "version": version,
                "pod_name": pod_info["name"],
                "image": image_tag,
            }
        )
    except Exception as exc:
        logger.exception("Rollback failed for %s/%s to version %d", team, app_slug, version)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )
