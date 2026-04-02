"""Analytics API and dashboard routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..analytics import AnalyticsTracker

router = APIRouter(prefix="/analytics")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# Shared tracker instance (same DB as middleware).
_tracker: AnalyticsTracker | None = None


def _get_tracker() -> AnalyticsTracker:
    global _tracker  # noqa: PLW0603
    if _tracker is None:
        _tracker = AnalyticsTracker()
    return _tracker


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def analytics_dashboard(request: Request) -> HTMLResponse:
    """Render the analytics dashboard page."""
    tracker = _get_tracker()
    summary = tracker.get_summary()
    events = tracker.get_events(limit=20)
    return _templates.TemplateResponse(
        request,
        "analytics.html",
        context={
            "summary": summary,
            "events": events,
        },
    )


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


@router.get("/api/summary")
async def api_summary() -> JSONResponse:
    """Return a JSON summary of analytics data."""
    tracker = _get_tracker()
    return JSONResponse(tracker.get_summary())


@router.get("/api/events")
async def api_events(
    event_type: str | None = Query(None),
    user_id: str | None = Query(None),
    since: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> JSONResponse:
    """Return a JSON list of analytics events."""
    tracker = _get_tracker()
    events = tracker.get_events(
        event_type=event_type,
        user_id=user_id,
        since=since,
        limit=limit,
    )
    return JSONResponse(events)


@router.get("/api/daily")
async def api_daily(
    days: int = Query(30, ge=1, le=365),
) -> JSONResponse:
    """Return JSON daily stats for the last N days."""
    tracker = _get_tracker()
    stats = tracker.get_daily_stats(days=days)
    return JSONResponse(stats)
