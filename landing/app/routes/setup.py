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
from ..repo_config import RepoConfigManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

_api_key_mgr: APIKeyManager | None = None
_git_token_mgr: GitTokenManager | None = None
_repo_config_mgr: RepoConfigManager | None = None


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


def _get_repo_config_mgr() -> RepoConfigManager:
    global _repo_config_mgr
    if _repo_config_mgr is None:
        _repo_config_mgr = RepoConfigManager()
    return _repo_config_mgr


def _get_status() -> dict:
    """Get configuration status for all settings."""
    api_configured = False
    git_configured = False
    repo_url = ""
    try:
        api_configured = _get_api_key_mgr().is_configured()
    except Exception:
        pass
    try:
        git_configured = _get_git_token_mgr().is_configured()
    except Exception:
        pass
    try:
        repo_url = _get_repo_config_mgr().get_url()
    except Exception:
        pass
    return {
        "api_key_configured": api_configured,
        "git_token_configured": git_configured,
        "repo_url": repo_url,
        "repo_configured": bool(repo_url),
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


@router.post("/repo-url", response_model=None)
async def set_repo_url(request: Request, repo_url: str = Form(...)):
    url = repo_url.strip()
    if not url:
        status = _get_status()
        status["error"] = "Repository URL cannot be empty."
        return _templates.TemplateResponse(request, "setup.html", context=status)
    if not (url.startswith("https://") or url.startswith("git@")):
        status = _get_status()
        status["error"] = "Repository URL must start with https:// or git@"
        return _templates.TemplateResponse(request, "setup.html", context=status)
    try:
        _get_repo_config_mgr().set_url(url)
        # Update the env var so repo_sync picks it up.
        os.environ["SUS_GIT_REPO_URL"] = url
        # Trigger a re-sync.
        try:
            from ..repo_sync import clone_or_pull
            clone_or_pull()
        except Exception:
            pass
    except Exception:
        logger.exception("Failed to save repo URL")
        status = _get_status()
        status["error"] = "Failed to save repo URL. Check cluster permissions."
        return _templates.TemplateResponse(request, "setup.html", context=status)
    return RedirectResponse(url="/setup", status_code=303)


@router.get("/api/status")
async def status() -> JSONResponse:
    return JSONResponse(_get_status())
