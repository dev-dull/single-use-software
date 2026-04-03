"""Secrets API — manage K8s secrets in the workloads namespace.

SUS apps can call these endpoints to manage credentials without
needing direct Kubernetes API access.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/secrets")

_core: client.CoreV1Api | None = None


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
async def get_secret(name: str) -> JSONResponse:
    """Get a secret's key names (never expose values)."""
    try:
        core = _get_core()
        secret = core.read_namespaced_secret(name, _namespace())
        return JSONResponse({
            "name": secret.metadata.name,
            "keys": list(secret.data.keys()) if secret.data else [],
            "created": secret.metadata.creation_timestamp.isoformat() if secret.metadata.creation_timestamp else None,
        })
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
    try:
        core = _get_core()
        core.delete_namespaced_secret(name, _namespace())
        return JSONResponse({"status": "deleted", "name": name})
    except ApiException as exc:
        if exc.status == 404:
            return JSONResponse({"error": "Secret not found"}, status_code=404)
        logger.exception("Failed to delete secret")
        return JSONResponse({"error": "Failed to delete secret"}, status_code=500)
