"""Shared FastAPI dependencies for SUS.

Housing the identity provider singleton and the ``resolve_identity``
dependency here (rather than in ``main``) lets routers depend on them
without importing ``main`` at decoration time, which would create a
circular import.
"""

from __future__ import annotations

from fastapi import Depends
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
