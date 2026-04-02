"""Analytics middleware — tracks page views and API calls."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .analytics import AnalyticsTracker

logger = logging.getLogger(__name__)

# Paths that should not be tracked.
_SKIP_PREFIXES = (
    "/healthz",
    "/readyz",
    "/static",
    "/analytics",
    "/favicon",
)

# Map URL path prefixes to event types.
_EVENT_MAP: list[tuple[str, str]] = [
    ("/build/", "build_view"),
    ("/run/", "run_view"),
    ("/api/catalog", "catalog_view"),
]


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that records page-view analytics events."""

    def __init__(self, app, tracker: AnalyticsTracker | None = None) -> None:  # noqa: ANN001
        super().__init__(app)
        self.tracker = tracker or AnalyticsTracker()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Skip paths we don't want to track.
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        # Only track GET requests (page views).
        if request.method == "GET":
            event_type: str | None = None
            for prefix, etype in _EVENT_MAP:
                if path.startswith(prefix):
                    event_type = etype
                    break

            # Track the landing/catalog page itself.
            if path == "/" or path == "":
                event_type = "catalog_view"

            if event_type is not None:
                # Extract user identity — best-effort.
                user_id = "anonymous"
                try:
                    # Try reading from request state set by identity middleware.
                    identity = getattr(request.state, "identity", None)
                    if identity is not None:
                        user_id = getattr(identity, "user_id", "anonymous") or "anonymous"
                except Exception:
                    pass

                # Extract team/app_slug from path segments if applicable.
                team = ""
                app_slug = ""
                parts = [p for p in path.strip("/").split("/") if p]
                if len(parts) >= 3 and parts[0] in ("build", "run"):
                    team = parts[1]
                    app_slug = parts[2]

                try:
                    self.tracker.track_event(
                        event_type=event_type,
                        user_id=user_id,
                        team=team,
                        app_slug=app_slug,
                        metadata={"path": path, "method": request.method},
                    )
                except Exception:
                    logger.exception("Failed to track analytics event")

        return await call_next(request)
