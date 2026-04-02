"""Git workflow manager — coordinates build sessions and git operations with build pods."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .pods import BuildPodManager
from .publisher import Publisher
from .sessions import SessionStore

logger = logging.getLogger(__name__)


class GitWorkflowManager:
    """Orchestrates build sessions, save requests, and publish requests.

    The heavy git work (commits, PRs) happens *inside* the build pod where
    Claude Code runs.  This manager handles pod lifecycle and signalling.
    """

    def __init__(
        self,
        pod_manager: BuildPodManager,
        session_store: SessionStore,
        publisher: Publisher | None = None,
    ) -> None:
        self._pods = pod_manager
        self._sessions = session_store
        self._publisher = publisher

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_branch(user_id: str, app_slug: str) -> str:
        """Create a deterministic branch name for today's session."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{user_id}/{app_slug}/{date_str}"

    def _pod_is_running(self, pod_name: str) -> dict | None:
        """Return pod info dict if the pod exists and is Running, else None."""
        info = self._pods.get_build_pod(pod_name)
        if info is None:
            return None
        if info.get("phase") in ("Running", "Pending"):
            return info
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_session(self, user_id: str, team: str, app_slug: str) -> dict:
        """Start or resume a build session.

        Returns a dict with ``pod_name``, ``pod_ip``, and ``branch``.
        """
        existing = self._sessions.get(user_id, app_slug)

        if existing:
            pod_info = self._pod_is_running(existing["pod_name"])
            if pod_info:
                # Pod still alive — return it directly.
                return {
                    "pod_name": existing["pod_name"],
                    "pod_ip": pod_info.get("pod_ip"),
                    "branch": existing["branch"],
                }

            # Session record exists but the pod is gone — recreate on same branch.
            branch = existing["branch"]
            logger.info(
                "Pod %s gone for %s/%s — recreating on branch %s",
                existing["pod_name"],
                user_id,
                app_slug,
                branch,
            )
        else:
            branch = self._generate_branch(user_id, app_slug)

        # Create a new pod and persist the session.
        pod_name = self._pods.create_build_pod(
            user_id=user_id,
            app_slug=app_slug,
            branch=branch,
        )
        self._sessions.upsert(
            user_id=user_id,
            pod_name=pod_name,
            branch=branch,
            app_slug=app_slug,
        )

        # The pod may not have an IP yet (still scheduling).
        pod_info = self._pods.get_build_pod(pod_name)
        pod_ip = pod_info.get("pod_ip") if pod_info else None

        return {
            "pod_name": pod_name,
            "pod_ip": pod_ip,
            "branch": branch,
        }

    def save(
        self,
        user_id: str,
        team: str,
        app_slug: str,
        message: str | None = None,
    ) -> dict:
        """Signal the build pod that a save (named commit) was requested.

        The actual ``git add / git commit`` is performed by Claude Code inside
        the pod, which watches for the marker file written here.

        Returns status information including the branch name.
        """
        session = self._sessions.get(user_id, app_slug)
        if session is None:
            return {"status": "error", "detail": "no active session"}

        branch = session["branch"]
        # TODO: write a marker file / send a signal to the build pod so Claude
        # Code picks up the save request with the optional commit message.
        logger.info(
            "Save requested for %s/%s on branch %s (message=%s)",
            user_id,
            app_slug,
            branch,
            message,
        )
        return {"status": "save_requested", "branch": branch}

    def publish(self, user_id: str, team: str, app_slug: str) -> dict:
        """Signal the build pod that a publish (PR creation) was requested.

        The actual PR is created by Claude Code inside the pod.

        Returns status information including the branch name.
        """
        session = self._sessions.get(user_id, app_slug)
        if session is None:
            return {"status": "error", "detail": "no active session"}

        branch = session["branch"]
        # TODO: write a marker file / send a signal to the build pod so Claude
        # Code picks up the publish request.
        logger.info(
            "Publish requested for %s/%s on branch %s",
            user_id,
            app_slug,
            branch,
        )

        # If a publisher is configured, also create/update the run pod.
        publish_result = None
        if self._publisher is not None:
            try:
                publish_result = self._publisher.publish_app(team=team, app_slug=app_slug)
                logger.info("Run pod published: %s", publish_result)
            except Exception:
                logger.exception("Failed to publish run pod for %s/%s", team, app_slug)

        return {
            "status": "publish_requested",
            "branch": branch,
            "publish": publish_result,
        }

    def end_session(self, user_id: str, team: str, app_slug: str) -> None:
        """Tear down the build pod and remove the session record."""
        session = self._sessions.get(user_id, app_slug)
        if session is None:
            return

        pod_name = session["pod_name"]
        logger.info("Ending session for %s/%s — deleting pod %s", user_id, app_slug, pod_name)
        self._pods.delete_build_pod(pod_name)
        self._sessions.delete(user_id, app_slug)
