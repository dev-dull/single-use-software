"""Authentication routes -- active when using the local-database provider."""

from __future__ import annotations

import json as _json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..identity import LocalDatabaseProvider

router = APIRouter(prefix="/auth")


def _get_provider(request: Request) -> LocalDatabaseProvider | None:
    """Return the identity provider only if it is a LocalDatabaseProvider."""
    from ..main import get_identity_provider

    provider = get_identity_provider()
    if isinstance(provider, LocalDatabaseProvider):
        return provider
    return None


@router.post("/login")
async def login(request: Request) -> JSONResponse:
    """Authenticate a user and set a session cookie."""
    provider = _get_provider(request)
    if provider is None:
        return JSONResponse(
            {"error": "Login is only available with the local-database provider"},
            status_code=400,
        )

    body = await request.json()
    username: str = body.get("username", "")
    password: str = body.get("password", "")

    token = provider.authenticate(username, password)
    if token is None:
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)

    with provider._connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.display_name, u.groups FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()

    response = JSONResponse(
        {
            "id": str(row["id"]),
            "display_name": row["display_name"],
            "groups": _json.loads(row["groups"]),
        }
    )
    response.set_cookie(
        key="sus_session", value=token, httponly=True, samesite="lax"
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    """Clear the session cookie and invalidate the server-side session."""
    provider = _get_provider(request)
    token = request.cookies.get("sus_session")

    if provider is not None and token:
        provider.delete_session(token)

    response = JSONResponse({"status": "ok"})
    response.delete_cookie(key="sus_session")
    return response


@router.get("/me")
async def me(request: Request) -> JSONResponse:
    """Return the current user's identity."""
    from ..main import get_identity_provider

    provider = get_identity_provider()
    identity = await provider.resolve(request)
    return JSONResponse(
        {
            "id": identity.id,
            "display_name": identity.display_name,
            "groups": list(identity.groups) if identity.groups else [],
        }
    )


@router.post("/register")
async def register(request: Request) -> JSONResponse:
    """Create a new user account (local-database provider only)."""
    provider = _get_provider(request)
    if provider is None:
        return JSONResponse(
            {
                "error": (
                    "Registration is only available with the "
                    "local-database provider"
                )
            },
            status_code=400,
        )

    body = await request.json()
    username: str = body.get("username", "")
    password: str = body.get("password", "")
    display_name: str = body.get("display_name", username)
    groups: list[str] = body.get("groups", ["default"])

    if not username or not password:
        return JSONResponse(
            {"error": "Username and password are required"},
            status_code=400,
        )

    try:
        identity = provider.create_user(
            username, password, display_name, groups
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)

    return JSONResponse(
        {
            "id": identity.id,
            "display_name": identity.display_name,
            "groups": list(identity.groups) if identity.groups else [],
        },
        status_code=201,
    )
