"""Setup routes — API key and Git token configuration."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..api_key import APIKeyManager
from ..git_token import GitTokenManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

_api_key_mgr: APIKeyManager | None = None
_git_token_mgr: GitTokenManager | None = None


def _get_api_key_mgr() -> APIKeyManager:
    global _api_key_mgr
    if _api_key_mgr is None:
        _api_key_mgr = APIKeyManager()
    return _api_key_mgr


def _get_git_token_mgr() -> GitTokenManager:
    global _git_token_mgr
    if _git_token_mgr is None:
        _git_token_mgr = GitTokenManager()
    return _git_token_mgr


def _get_status() -> dict:
    """Get configuration status for both keys."""
    api_configured = False
    git_configured = False
    try:
        api_configured = _get_api_key_mgr().is_configured()
    except Exception:
        pass
    try:
        git_configured = _get_git_token_mgr().is_configured()
    except Exception:
        pass
    return {
        "api_key_configured": api_configured,
        "git_token_configured": git_configured,
        "repo_url": os.environ.get("SUS_GIT_REPO_URL", "(not set)"),
    }


@router.get("", response_class=HTMLResponse)
async def setup_page(request: Request) -> HTMLResponse:
    status = _get_status()
    return _templates.TemplateResponse(request, "setup.html", context=status)


@router.post("/api-key", response_model=None)
async def set_api_key(request: Request, api_key: str = Form(...)):
    key = api_key.strip()
    if not key.startswith("sk-ant-"):
        status = _get_status()
        status["error"] = "Invalid API key. It should start with sk-ant-"
        return _templates.TemplateResponse(request, "setup.html", context=status)
    try:
        _get_api_key_mgr().set_key(key)
    except Exception:
        logger.exception("Failed to save API key")
        status = _get_status()
        status["error"] = "Failed to save API key. Check cluster permissions."
        return _templates.TemplateResponse(request, "setup.html", context=status)
    return RedirectResponse(url="/setup", status_code=303)


@router.post("/git-token", response_model=None)
async def set_git_token(request: Request, git_token: str = Form(...)):
    token = git_token.strip()
    if not token:
        status = _get_status()
        status["error"] = "Token cannot be empty."
        return _templates.TemplateResponse(request, "setup.html", context=status)
    try:
        _get_git_token_mgr().set_token(token)
        # Trigger a re-sync so the catalog updates with the new credentials.
        try:
            from ..repo_sync import clone_or_pull
            clone_or_pull()
        except Exception:
            pass
    except Exception:
        logger.exception("Failed to save Git token")
        status = _get_status()
        status["error"] = "Failed to save Git token. Check cluster permissions."
        return _templates.TemplateResponse(request, "setup.html", context=status)
    return RedirectResponse(url="/setup", status_code=303)


@router.get("/api/status")
async def status() -> JSONResponse:
    return JSONResponse(_get_status())
