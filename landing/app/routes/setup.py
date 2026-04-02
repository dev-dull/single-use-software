"""Setup routes — API key configuration and onboarding."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..api_key import APIKeyManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

_api_key_mgr: APIKeyManager | None = None


def _get_api_key_mgr() -> APIKeyManager:
    global _api_key_mgr
    if _api_key_mgr is None:
        _api_key_mgr = APIKeyManager()
    return _api_key_mgr


@router.get("", response_class=HTMLResponse)
async def setup_page(request: Request) -> HTMLResponse:
    """Render the setup page."""
    try:
        mgr = _get_api_key_mgr()
        configured = mgr.is_configured()
    except Exception:
        logger.exception("Failed to check API key status")
        configured = False

    return _templates.TemplateResponse(
        request,
        "setup.html",
        context={"configured": configured},
    )


@router.post("/api-key", response_model=None)
async def set_api_key(
    request: Request,
    api_key: str = Form(...),
):
    """Save the Anthropic API key as a Kubernetes secret."""
    key = api_key.strip()
    if not key.startswith("sk-ant-"):
        return _templates.TemplateResponse(
            request,
            "setup.html",
            context={"configured": False, "error": "Invalid API key. It should start with sk-ant-"},
        )

    try:
        mgr = _get_api_key_mgr()
        mgr.set_key(key)
    except Exception:
        logger.exception("Failed to save API key")
        return _templates.TemplateResponse(
            request,
            "setup.html",
            context={"configured": False, "error": "Failed to save API key. Check cluster permissions."},
        )

    return RedirectResponse(url="/", status_code=303)


@router.get("/api/status")
async def api_key_status() -> JSONResponse:
    """Check if the API key is configured."""
    try:
        mgr = _get_api_key_mgr()
        return JSONResponse({"configured": mgr.is_configured()})
    except Exception:
        return JSONResponse({"configured": False})


@router.post("/api-key/delete")
async def delete_api_key() -> JSONResponse:
    """Delete the API key secret."""
    try:
        mgr = _get_api_key_mgr()
        mgr.delete_key()
        return JSONResponse({"status": "deleted"})
    except Exception:
        logger.exception("Failed to delete API key")
        return JSONResponse({"status": "error"}, status_code=500)
