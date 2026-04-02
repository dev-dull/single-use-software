"""SUS Landing Page — FastAPI application."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .catalog import all_tags, scan_apps
from .cleanup import start_cleanup_loop
from .config import create_identity_provider, load_config
from .identity import IdentityProvider, UserIdentity
from .pods import BuildPodManager
from .analytics import AnalyticsTracker
from .middleware import AnalyticsMiddleware
from .routes.analytics import router as analytics_router
from .routes.auth import router as auth_router
from .routes.build import router as build_router
from .routes.mcp import router as mcp_router
from .routes.run import router as run_router
from .routes.sessions import router as sessions_router
from .sessions import SessionStore

# ---------------------------------------------------------------------------
# Application & templates
# ---------------------------------------------------------------------------

app = FastAPI(title="SUS Landing Page", version="0.1.0")
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(build_router)
app.include_router(mcp_router)
app.include_router(run_router)
app.include_router(sessions_router)

# Analytics middleware — tracks page views automatically.
_analytics_tracker = AnalyticsTracker()
app.add_middleware(AnalyticsMiddleware, tracker=_analytics_tracker)


@app.on_event("startup")
async def _start_cleanup_task() -> None:
    """Launch the background cleanup loop when the app starts."""
    pod_manager = BuildPodManager()
    session_store = SessionStore()
    asyncio.create_task(
        start_cleanup_loop(pod_manager, session_store),
    )

_templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# Identity dependency
# ---------------------------------------------------------------------------

_identity_provider: IdentityProvider = create_identity_provider(load_config())


def get_identity_provider() -> IdentityProvider:
    """Return the active identity provider (swappable at startup)."""
    return _identity_provider


async def resolve_identity(
    request: Request,
    provider: IdentityProvider = Depends(get_identity_provider),
) -> UserIdentity:
    """Dependency that resolves the calling user's identity."""
    return await provider.resolve(request)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/healthz", status_code=200)
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz", status_code=200)
async def readyz() -> dict[str, str]:
    """Readiness probe."""
    return {"status": "ok"}


@app.get("/api/catalog")
async def api_catalog(
    identity: UserIdentity = Depends(resolve_identity),
    q: str | None = None,
    tags: list[str] = Query(default=[]),
) -> list[dict[str, Any]]:
    """Return the discovered app catalog as JSON."""
    return scan_apps(
        user_groups=list(identity.groups) if identity.groups else None,
        query=q or None,
        tags=tags or None,
    )


@app.get("/api/catalog/html", response_class=HTMLResponse)
async def api_catalog_html(
    request: Request,
    identity: UserIdentity = Depends(resolve_identity),
    q: str | None = None,
    tags: list[str] = Query(default=[]),
) -> HTMLResponse:
    """Return just the catalog card grid as an HTML fragment for HTMX."""
    catalog = scan_apps(
        user_groups=list(identity.groups) if identity.groups else None,
        query=q or None,
        tags=tags or None,
    )
    return templates.TemplateResponse(
        request,
        "catalog_cards.html",
        context={"catalog": catalog},
    )


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    identity: UserIdentity = Depends(resolve_identity),
    q: str | None = None,
    tags: list[str] = Query(default=[]),
) -> HTMLResponse:
    """Render the landing page with the app catalog."""
    catalog = scan_apps(
        user_groups=list(identity.groups) if identity.groups else None,
        query=q or None,
        tags=tags or None,
    )
    available_tags = all_tags()
    return templates.TemplateResponse(
        request,
        "index.html",
        context={
            "identity": identity,
            "catalog": catalog,
            "available_tags": available_tags,
            "active_tags": tags or [],
            "query": q or "",
        },
    )
