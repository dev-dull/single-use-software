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

        # Look up app metadata from the catalog for context.
        app_name = ""
        app_description = ""
        try:
            from .catalog import scan_apps
            for app in scan_apps():
                if app.get("team") == team and app.get("slug") == app_slug:
                    app_name = app.get("name", "")
                    app_description = app.get("description", "")
                    break
        except Exception:
            pass

        # Create a new pod and persist the session.
        pod_name = self._pods.create_build_pod(
            user_id=user_id,
            app_slug=app_slug,
            branch=branch,
            team=team,
            app_name=app_name,
            app_description=app_description,
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
        """Publish the app — register the build pod as the run target.

        For the MVP, we skip building a separate container image and instead
        proxy run-mode traffic to the existing build pod's port 3000.
        """
        session = self._sessions.get(user_id, app_slug)
        if session is None:
            return {"status": "error", "detail": "no active session"}

        branch = session["branch"]
        pod_name = session["pod_name"]

        # Get the build pod's IP so we can proxy run traffic to it.
        pod_info = self._pods.get_build_pod(pod_name)
        pod_ip = pod_info.get("pod_ip") if pod_info else None

        if not pod_ip:
            return {"status": "error", "detail": "build pod not running"}

        # Commit and push changes from the build pod to the app repo.
        commit_hash = "unknown"
        try:
            # Stage and commit all changes.
            self._pods.exec_in_pod(pod_name, [
                "bash", "-c",
                "cd /repo && git add -A && "
                "git diff --cached --quiet || "
                "git commit -m 'publish: update ${APP_TEAM}/${APP_SLUG}'"
            ])

            # Get the commit hash.
            try:
                commit_hash = self._pods.exec_in_pod(pod_name, [
                    "bash", "-c", "cd /repo && git rev-parse --short HEAD"
                ]).strip()
            except Exception:
                pass

            # Push to main (merge the branch).
            self._pods.exec_in_pod(pod_name, [
                "bash", "-c",
                "cd /repo && "
                "git checkout main 2>/dev/null && "
                "git merge --no-edit ${GIT_BRANCH} && "
                "git push origin main && "
                "git checkout ${GIT_BRANCH}"
            ])
            logger.info("Pushed published changes for %s/%s to app repo", team, app_slug)
        except Exception:
            logger.exception("Failed to push to app repo for %s/%s — saving locally only", team, app_slug)

        # Register the build pod as the run target for immediate serving.
        from .published_apps import PublishedAppStore
        store = PublishedAppStore()
        store.publish(
            team=team,
            app_slug=app_slug,
            pod_ip=pod_ip,
            pod_name=pod_name,
            published_by=user_id,
        )

        # Record version history.
        try:
            from .versions import VersionTracker
            tracker = VersionTracker()
            version_number = tracker.record_version(
                team=team,
                app_slug=app_slug,
                commit_hash=commit_hash,
                published_by=user_id,
                image_tag=f"build-pod:{pod_name}",
                message=f"Published from build session",
            )
            logger.info("Recorded version %d for %s/%s", version_number, team, app_slug)
        except Exception:
            logger.exception("Failed to record version for %s/%s", team, app_slug)

        # Trigger a repo sync so the landing page picks up the changes.
        try:
            from .repo_sync import clone_or_pull
            clone_or_pull()
        except Exception:
            pass

        logger.info(
            "Published %s/%s — proxying run to build pod %s (%s)",
            team, app_slug, pod_name, pod_ip,
        )

        return {
            "status": "publish_requested",
            "branch": branch,
            "pod_ip": pod_ip,
            "commit": commit_hash,
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
