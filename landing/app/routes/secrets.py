"""Secrets API — manage K8s secrets in the workloads namespace.

Operator-only. Every route is gated behind ``require_operator`` so that
build/run pods — which call the platform API directly and therefore resolve
to the anonymous ``guest`` identity — cannot read or mutate cluster secrets
(app→platform privilege escalation, see #79). As defence in depth, a denylist
of platform-owned secrets is never listed, read, or mutated through this API
regardless of caller (this is what protects those credentials in single-user /
open-proxy modes, where a pod can appear authenticated).
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from ..api_key import SECRET_NAME as _API_KEY_SECRET
from ..deps import require_operator
from ..git_token import SECRET_NAME as _GIT_TOKEN_SECRET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/secrets", dependencies=[Depends(require_operator)])

_core: client.CoreV1Api | None = None

# Platform-owned secrets that must never be exposed or mutated through this
# generic API, even to an authenticated operator. Sourced from the managers
# that own them so a rename can't silently un-protect them. Extend via the
# ``SUS_PROTECTED_SECRETS`` env var (comma-separated).
_DEFAULT_PROTECTED_SECRETS = frozenset({
    _GIT_TOKEN_SECRET,
    _API_KEY_SECRET,
})


def _protected_secrets() -> frozenset[str]:
    extra = {
        s.strip()
        for s in os.environ.get("SUS_PROTECTED_SECRETS", "").split(",")
        if s.strip()
    }
    return _DEFAULT_PROTECTED_SECRETS | extra


def _is_protected(name: str) -> bool:
    return name in _protected_secrets()


def _protected_response() -> JSONResponse:
    return JSONResponse(
        {"error": "Secret is platform-managed and not accessible via this API"},
        status_code=403,
    )


def _get_core() -> client.CoreV1Api:
    global _core
    if _core is None:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        _core = client.CoreV1Api()
    return _core


def _namespace() -> str:
    return os.environ.get("SUS_WORKLOADS_NAMESPACE", "sus-workloads")


@router.get("")
async def list_secrets() -> JSONResponse:
    """List secret names in the workloads namespace (values are never exposed)."""
    try:
        core = _get_core()
        secrets = core.list_namespaced_secret(_namespace())
        result = []
        for s in secrets.items:
            if _is_protected(s.metadata.name):
                continue
            result.append({
                "name": s.metadata.name,
                "keys": list(s.data.keys()) if s.data else [],
                "created": s.metadata.creation_timestamp.isoformat() if s.metadata.creation_timestamp else None,
            })
        return JSONResponse(result)
    except Exception:
        logger.exception("Failed to list secrets")
        return JSONResponse({"error": "Failed to list secrets"}, status_code=500)


@router.get("/{name}")
async def get_secret(name: str, values: bool = False) -> JSONResponse:
    """Get a secret's metadata and optionally its values.

    Pass ?values=true to include decoded secret values.
    By default only key names are returned.
    """
    if _is_protected(name):
        return _protected_response()
    try:
        core = _get_core()
        secret = core.read_namespaced_secret(name, _namespace())
        result = {
            "name": secret.metadata.name,
            "keys": list(secret.data.keys()) if secret.data else [],
            "created": secret.metadata.creation_timestamp.isoformat() if secret.metadata.creation_timestamp else None,
        }
        if values and secret.data:
            import base64
            result["data"] = {
                k: base64.b64decode(v).decode() for k, v in secret.data.items()
            }
        return JSONResponse(result)
    except ApiException as exc:
        if exc.status == 404:
            return JSONResponse({"error": "Secret not found"}, status_code=404)
        raise


@router.post("")
async def create_secret(request: Request) -> JSONResponse:
    """Create a new secret. Body: {"name": "...", "data": {"KEY": "value"}}"""
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        data = body.get("data", {})

        if not name:
            return JSONResponse({"error": "Name is required"}, status_code=400)
        if _is_protected(name):
            return _protected_response()
        if not data:
            return JSONResponse({"error": "At least one key-value pair is required"}, status_code=400)

        core = _get_core()
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=name, namespace=_namespace()),
            string_data=data,
            type="Opaque",
        )
        core.create_namespaced_secret(_namespace(), secret)
        return JSONResponse({"status": "created", "name": name})
    except ApiException as exc:
        if exc.status == 409:
            return JSONResponse({"error": "Secret already exists"}, status_code=409)
        logger.exception("Failed to create secret")
        return JSONResponse({"error": "Failed to create secret"}, status_code=500)


@router.put("/{name}")
async def update_secret(name: str, request: Request) -> JSONResponse:
    """Update a secret's data. Body: {"data": {"KEY": "value"}}"""
    if _is_protected(name):
        return _protected_response()
    try:
        body = await request.json()
        data = body.get("data", {})

        if not data:
            return JSONResponse({"error": "At least one key-value pair is required"}, status_code=400)

        core = _get_core()
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=name, namespace=_namespace()),
            string_data=data,
            type="Opaque",
        )
        core.replace_namespaced_secret(name, _namespace(), secret)
        return JSONResponse({"status": "updated", "name": name})
    except ApiException as exc:
        if exc.status == 404:
            return JSONResponse({"error": "Secret not found"}, status_code=404)
        logger.exception("Failed to update secret")
        return JSONResponse({"error": "Failed to update secret"}, status_code=500)


@router.delete("/{name}")
async def delete_secret(name: str) -> JSONResponse:
    """Delete a secret."""
    if _is_protected(name):
        return _protected_response()
    try:
        core = _get_core()
        core.delete_namespaced_secret(name, _namespace())
        return JSONResponse({"status": "deleted", "name": name})
    except ApiException as exc:
        if exc.status == 404:
            return JSONResponse({"error": "Secret not found"}, status_code=404)
        logger.exception("Failed to delete secret")
        return JSONResponse({"error": "Failed to delete secret"}, status_code=500)
