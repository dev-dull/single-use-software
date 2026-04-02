"""Pluggable identity provider interface for SUS."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional, Sequence

from starlette.requests import Request


@dataclass
class UserIdentity:
    """Resolved user identity attached to each request."""

    id: str
    display_name: str
    groups: Optional[Sequence[str]] = field(default_factory=list)


class IdentityProvider(abc.ABC):
    """Abstract base class for identity resolution.

    Implement ``resolve`` to extract a ``UserIdentity`` from an incoming
    HTTP request.  The landing page pod calls this on every request so
    that downstream handlers always have access to the caller's identity.
    """

    @abc.abstractmethod
    async def resolve(self, request: Request) -> UserIdentity:
        """Return the identity associated with *request*."""
        ...


class SingleUserProvider(IdentityProvider):
    """Default provider for single-user / no-auth deployments.

    Always returns a fixed "Local Operator" identity with full access.
    """

    async def resolve(self, request: Request) -> UserIdentity:
        return UserIdentity(
            id="local",
            display_name="Local Operator",
            groups=["default"],
        )
