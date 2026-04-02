"""Session management routes — list, get, and delete build sessions."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..pods import BuildPodManager
from ..sessions import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions")

# ---------------------------------------------------------------------------
# Lazy-initialised singletons
# ---------------------------------------------------------------------------

_session_store: Optional[SessionStore] = None
_pod_manager: Optional[BuildPodManager] = None


def _get_session_store() -> SessionStore:
    global _session_store  # noqa: PLW0603
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


def _get_pod_manager() -> BuildPodManager:
    global _pod_manager  # noqa: PLW0603
    if _pod_manager is None:
        _pod_manager = BuildPodManager()
    return _pod_manager


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_sessions(
    user_id: str = Query(None, alias="user_id"),
) -> JSONResponse:
    """List all sessions, optionally filtered by user_id."""
    store = _get_session_store()
    sessions = store.list_sessions(user_id=user_id)
    return JSONResponse({"sessions": sessions})


@router.get("/{user_id}/{app_slug}")
async def get_session(user_id: str, app_slug: str) -> JSONResponse:
    """Get a specific session by user_id and app_slug."""
    store = _get_session_store()
    session = store.get(user_id, app_slug)
    if session is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return JSONResponse({"session": session})


@router.delete("/{user_id}/{app_slug}")
async def delete_session(user_id: str, app_slug: str) -> JSONResponse:
    """End a session — delete the pod and remove the session record."""
    store = _get_session_store()
    pod_mgr = _get_pod_manager()

    session = store.get(user_id, app_slug)
    if session is None:
        return JSONResponse({"error": "session not found"}, status_code=404)

    # Delete the pod first, then the session record.
    try:
        pod_mgr.delete_build_pod(session["pod_name"])
    except Exception:
        logger.exception("Failed to delete pod %s", session["pod_name"])

    store.delete(user_id, app_slug)
    return JSONResponse({"status": "deleted"})
