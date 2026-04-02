"""SUS Landing Page — FastAPI application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .catalog import scan_apps
from .identity import IdentityProvider, SingleUserProvider, UserIdentity

# ---------------------------------------------------------------------------
# Application & templates
# ---------------------------------------------------------------------------

app = FastAPI(title="SUS Landing Page", version="0.1.0")

_templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# Identity dependency
# ---------------------------------------------------------------------------

_identity_provider: IdentityProvider = SingleUserProvider()


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
) -> list[dict[str, Any]]:
    """Return the discovered app catalog as JSON."""
    return scan_apps()


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    identity: UserIdentity = Depends(resolve_identity),
) -> HTMLResponse:
    """Render the landing page with the app catalog."""
    catalog = scan_apps()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "identity": identity,
            "catalog": catalog,
        },
    )
