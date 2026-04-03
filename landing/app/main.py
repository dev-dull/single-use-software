"""SUS Landing Page — FastAPI application."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, Query, Request
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
from .routes.skills import router as skills_router
from .routes.debug import router as debug_router
from .routes.secrets import router as secrets_router
from .routes.setup import router as setup_router
from .routes.versions import router as versions_router
from .sessions import SessionStore

# ---------------------------------------------------------------------------
# Application & templates
# ---------------------------------------------------------------------------

app = FastAPI(title="SUS Landing Page", version="0.1.0")
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(build_router)
app.include_router(debug_router)
app.include_router(mcp_router)
app.include_router(run_router)
app.include_router(secrets_router)
app.include_router(sessions_router)
app.include_router(setup_router)
app.include_router(skills_router)
app.include_router(versions_router)

# Analytics middleware — tracks page views automatically.
_analytics_tracker = AnalyticsTracker()
app.add_middleware(AnalyticsMiddleware, tracker=_analytics_tracker)


# No-cache middleware — disable browser caching on all responses.
from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path not in ("/healthz", "/readyz"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)


@app.on_event("startup")
async def _start_background_tasks() -> None:
    """Launch background tasks when the app starts."""
    # Repo sync — clone/pull the monorepo for the catalog.
    from .repo_sync import start_sync_loop
    asyncio.create_task(start_sync_loop())

    # Idle pod cleanup.
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


# ---------------------------------------------------------------------------
# New app creation
# ---------------------------------------------------------------------------

@app.get("/new", response_class=HTMLResponse)
async def new_app_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "new_app.html", context={})


@app.post("/new", response_model=None)
async def new_app_create(
    request: Request,
    app_name: str = Form(...),
    app_description: str = Form(""),
):
    import re
    from fastapi.responses import RedirectResponse

    name = app_name.strip()
    if not name:
        return templates.TemplateResponse(request, "new_app.html",
            context={"error": "App name is required.", "app_name": name, "app_description": app_description})

    # Generate a slug from the name.
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    if not slug:
        return templates.TemplateResponse(request, "new_app.html",
            context={"error": "Invalid app name.", "app_name": name, "app_description": app_description})

    # Use "apps" as the team for user-created apps.
    team = "apps"

    # Redirect to the build page — the build pod will create the app directory.
    return RedirectResponse(
        url=f"/build/{team}/{slug}",
        status_code=303,
    )


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

    # Check setup status for the banner.
    setup_complete = False
    try:
        from .api_key import APIKeyManager
        from .git_token import GitTokenManager
        setup_complete = APIKeyManager().is_configured() and GitTokenManager().is_configured()
    except Exception:
        pass

    return templates.TemplateResponse(
        request,
        "index.html",
        context={
            "identity": identity,
            "catalog": catalog,
            "available_tags": available_tags,
            "active_tags": tags or [],
            "query": q or "",
            "setup_complete": setup_complete,
        },
    )
