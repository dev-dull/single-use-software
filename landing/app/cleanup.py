"""Background cleanup task — removes idle build pods and their session records."""

from __future__ import annotations

import asyncio
import logging

from .pods import BuildPodManager
from .sessions import SessionStore

logger = logging.getLogger(__name__)


async def start_cleanup_loop(
    pod_manager: BuildPodManager,
    session_store: SessionStore,
    interval_minutes: int = 5,
    idle_timeout_minutes: int = 20,
) -> None:
    """Run an infinite loop that cleans up idle pods and their sessions.

    This is intended to be launched as an ``asyncio`` background task when the
    FastAPI application starts up.
    """
    while True:
        try:
            deleted = pod_manager.cleanup_idle_pods(idle_timeout_minutes)
            for pod_name in deleted:
                session = session_store.get_by_pod(pod_name)
                if session:
                    session_store.delete(session["user_id"], session["app_slug"])
                    logger.info(
                        "Cleaned up idle session for %s/%s (pod %s)",
                        session["user_id"],
                        session["app_slug"],
                        pod_name,
                    )
        except Exception:
            logger.exception("Error during cleanup loop iteration")

        await asyncio.sleep(interval_minutes * 60)
