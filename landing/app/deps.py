"""Shared FastAPI dependencies for SUS.

Housing the identity provider singleton and the ``resolve_identity``
dependency here (rather than in ``main``) lets routers depend on them
without importing ``main`` at decoration time, which would create a
circular import.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from starlette.requests import Request

from .config import create_identity_provider, load_config
from .identity import IdentityProvider, UserIdentity

# Instantiated once at import time from the active configuration.
_identity_provider: IdentityProvider = create_identity_provider(load_config())


def get_identity_provider() -> IdentityProvider:
    """Return the active identity provider (swappable at startup)."""
    return _identity_provider


async def resolve_identity(
    request: Request,
    provider: IdentityProvider = Depends(get_identity_provider),
) -> UserIdentity:
    """Resolve the calling user's identity and stash it on ``request.state``.

    Stashing on ``request.state`` lets non-dependency code (e.g. analytics
    middleware) reuse the resolved identity instead of re-resolving.
    """
    identity = await provider.resolve(request)
    request.state.identity = identity
    return identity


def _is_guest(identity: UserIdentity) -> bool:
    """True for an unauthenticated caller.

    Both ``ProxyHeaderProvider`` and ``LocalDatabaseProvider`` represent an
    anonymous request as ``id="guest"`` with ``groups=["guest"]``.
    """
    return identity.id == "guest" or "guest" in (identity.groups or ())


async def require_operator(
    identity: UserIdentity = Depends(resolve_identity),
) -> UserIdentity:
    """Require an authenticated (non-guest) operator identity.

    Build/run pods call the platform API directly, bypassing the forward-auth
    proxy, so they resolve to the anonymous ``guest`` identity. Routes that
    manage cluster credentials depend on this to reject those (and any other
    unauthenticated) callers. In single-user / no-auth deployments every
    request is the local operator, so this is a no-op there by design.
    """
    if _is_guest(identity):
        raise HTTPException(
            status_code=403, detail="operator authentication required"
        )
    return identity
