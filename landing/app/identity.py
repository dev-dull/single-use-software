"""Pluggable identity provider interface for SUS."""

from __future__ import annotations

import abc
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from starlette.requests import Request

logger = logging.getLogger(__name__)


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


class ProxyHeaderProvider(IdentityProvider):
    """Identity provider that trusts reverse-proxy forwarded headers.

    Designed for a forward-auth gateway (e.g. Authelia) that authenticates
    each request and injects the resolved identity as trusted headers:

    - ``Remote-User`` / ``Remote-Email`` -- user identifier (Authelia)
    - ``Remote-Name`` -- display name
    - ``Remote-Groups`` -- comma-separated group list

    The ``X-Forwarded-*`` variants are accepted as a fallback for proxies
    that use that naming (oauth2-proxy, etc.).

    Security: these headers are only trustworthy when they came from the
    forward-auth proxy. Any client — including a semi-untrusted build/run
    pod calling the platform API — could otherwise set ``Remote-User: admin``
    and impersonate the operator. ``trusted_proxies`` pins the set of source
    IPs/CIDRs whose identity headers are honoured; requests from anywhere
    else are treated as anonymous. The peer IP is taken from the raw socket
    (``request.client.host``), never from a forwardable header, so it cannot
    be spoofed as long as uvicorn is not configured to rewrite the client
    from ``X-Forwarded-For``.
    """

    # Header names in preference order: Authelia's Remote-* first, then the
    # X-Forwarded-* fallback.
    _USER_HEADERS = ("Remote-User", "Remote-Email",
                     "X-Forwarded-User", "X-Forwarded-Email")
    _NAME_HEADERS = ("Remote-Name", "X-Forwarded-Name")
    _GROUPS_HEADERS = ("Remote-Groups", "X-Forwarded-Groups")

    def __init__(
        self,
        trusted_proxies: Optional[Sequence[str]] = None,
        header_style: str = "remote",
    ) -> None:
        self._header_style = header_style
        self._trusted_networks: list[ipaddress._BaseNetwork] = []
        for entry in trusted_proxies or []:
            try:
                # ``strict=False`` lets a bare host IP ("10.42.0.5") parse as
                # a /32 (or /128) network.
                self._trusted_networks.append(
                    ipaddress.ip_network(entry, strict=False)
                )
            except ValueError:
                logger.warning(
                    "Ignoring invalid trusted_proxies entry: %r", entry
                )
        self._warned_open = False

    @staticmethod
    def _guest() -> UserIdentity:
        return UserIdentity(id="guest", display_name="Guest", groups=["guest"])

    def _peer_trusted(self, request: Request) -> bool:
        """Return True if the request's raw socket peer is a trusted proxy."""
        if not self._trusted_networks:
            # No trust anchor configured. Honour headers for backward
            # compatibility, but warn once — this is the footgun the design
            # doc calls out (any caller can forge identity headers).
            if not self._warned_open:
                logger.warning(
                    "ProxyHeaderProvider has no trusted_proxies configured; "
                    "identity headers are trusted from ANY source. Set "
                    "identity_options.trusted_proxies to the forward-auth "
                    "proxy address to close this hole."
                )
                self._warned_open = True
            return True

        client = request.client
        if client is None or not client.host:
            return False
        try:
            peer = ipaddress.ip_address(client.host)
        except ValueError:
            return False
        return any(peer in net for net in self._trusted_networks)

    @staticmethod
    def _first_header(request: Request, names: Sequence[str]) -> Optional[str]:
        for name in names:
            value = request.headers.get(name)
            if value:
                return value
        return None

    async def resolve(self, request: Request) -> UserIdentity:
        # An untrusted peer gets no identity, regardless of what headers it
        # sent — treat it as an anonymous guest.
        if not self._peer_trusted(request):
            return self._guest()

        user_id = self._first_header(request, self._USER_HEADERS)
        if not user_id:
            return self._guest()

        display_name = self._first_header(request, self._NAME_HEADERS) or user_id
        groups_header = self._first_header(request, self._GROUPS_HEADERS) or "default"
        groups = [g.strip() for g in groups_header.split(",") if g.strip()]

        return UserIdentity(
            id=user_id,
            display_name=display_name,
            groups=groups if groups else ["default"],
        )


class LocalDatabaseProvider(IdentityProvider):
    """SQLite-backed local user database with session management."""

    _SALT_LENGTH = 16
    _HASH_ITERATIONS = 260_000
    _SESSION_TTL_HOURS = 24

    def __init__(self, db_path: str = "users.db") -> None:
        self.db_path = db_path
        self._init_db()

    # -- database setup ------------------------------------------------------

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    groups TEXT NOT NULL DEFAULT '["default"]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    expires_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # -- password hashing ----------------------------------------------------

    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> str:
        if salt is None:
            salt = os.urandom(LocalDatabaseProvider._SALT_LENGTH)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt,
            LocalDatabaseProvider._HASH_ITERATIONS,
        )
        return f"{salt.hex()}:{dk.hex()}"

    @staticmethod
    def _verify_password(password: str, stored: str) -> bool:
        salt_hex, _ = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        return LocalDatabaseProvider._hash_password(password, salt) == stored

    # -- public API ----------------------------------------------------------

    async def resolve(self, request: Request) -> UserIdentity:
        token = request.cookies.get("sus_session")
        if not token:
            return UserIdentity(
                id="guest", display_name="Guest", groups=["guest"]
            )

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.username, u.display_name, u.groups
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ? AND s.expires_at > datetime('now')
                """,
                (token,),
            ).fetchone()

        if row is None:
            return UserIdentity(
                id="guest", display_name="Guest", groups=["guest"]
            )

        return UserIdentity(
            id=str(row["id"]),
            display_name=row["display_name"],
            groups=json.loads(row["groups"]),
        )

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str,
        groups: list[str] | None = None,
    ) -> UserIdentity:
        groups = groups or ["default"]
        password_hash = self._hash_password(password)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, display_name, groups) "
                "VALUES (?, ?, ?, ?)",
                (username, password_hash, display_name, json.dumps(groups)),
            )
            user_id = cursor.lastrowid
        return UserIdentity(
            id=str(user_id), display_name=display_name, groups=groups
        )

    def authenticate(self, username: str, password: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if row is None or not self._verify_password(
            password, row["password_hash"]
        ):
            return None

        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(
            hours=self._SESSION_TTL_HOURS
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) "
                "VALUES (?, ?, ?)",
                (
                    token,
                    row["id"],
                    expires.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
        return token

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
