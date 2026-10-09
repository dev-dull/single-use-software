"""Auth + denylist tests for the /api/secrets router (#79).

The router exposes CRUD over cluster secrets. It must reject unauthenticated
(guest) callers — build/run pods call the platform API directly and resolve to
``guest`` — and must never expose or mutate platform-owned secrets, even for an
authenticated operator.
"""

from types import SimpleNamespace

import app.routes.secrets as secrets_mod
from app.deps import resolve_identity
from app.identity import UserIdentity
from app.main import app
from fastapi.testclient import TestClient


def _client(identity: UserIdentity) -> TestClient:
    app.dependency_overrides[resolve_identity] = lambda: identity
    return TestClient(app)


def teardown_function(_):
    app.dependency_overrides.clear()


_GUEST = UserIdentity(id="guest", display_name="Guest", groups=["guest"])
_OPERATOR = UserIdentity(id="local", display_name="Local Operator", groups=["default"])


class _FakeCore:
    """Minimal CoreV1Api stand-in listing two secrets (one protected)."""

    def list_namespaced_secret(self, _ns):
        items = [
            SimpleNamespace(metadata=SimpleNamespace(
                name="app-config", creation_timestamp=None), data={"KEY": "dmFs"}),
            SimpleNamespace(metadata=SimpleNamespace(
                name="sus-git-token", creation_timestamp=None), data={"token": "eA=="}),
        ]
        return SimpleNamespace(items=items)


# --- the gate: guests are rejected on every verb --------------------------

def test_guest_is_rejected_on_all_routes():
    c = _client(_GUEST)
    assert c.get("/api/secrets").status_code == 403
    assert c.get("/api/secrets/app-config").status_code == 403
    assert c.post("/api/secrets", json={"name": "x", "data": {"K": "v"}}).status_code == 403
    assert c.put("/api/secrets/app-config", json={"data": {"K": "v"}}).status_code == 403
    assert c.delete("/api/secrets/app-config").status_code == 403


# --- the denylist: platform secrets stay hidden/immutable to an operator --

def test_operator_list_excludes_protected(monkeypatch):
    monkeypatch.setattr(secrets_mod, "_get_core", lambda: _FakeCore())
    r = _client(_OPERATOR).get("/api/secrets")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()}
    assert "app-config" in names
    assert "sus-git-token" not in names


def test_operator_cannot_read_protected_values(monkeypatch):
    # Guard runs before any k8s call, so no core stub is needed — assert that
    # too by making _get_core explode if it's reached.
    monkeypatch.setattr(secrets_mod, "_get_core",
                        lambda: (_ for _ in ()).throw(AssertionError("k8s hit")))
    r = _client(_OPERATOR).get("/api/secrets/sus-git-token?values=true")
    assert r.status_code == 403


def test_operator_cannot_mutate_protected(monkeypatch):
    monkeypatch.setattr(secrets_mod, "_get_core",
                        lambda: (_ for _ in ()).throw(AssertionError("k8s hit")))
    c = _client(_OPERATOR)
    assert c.put("/api/secrets/sus-git-token", json={"data": {"token": "x"}}).status_code == 403
    assert c.delete("/api/secrets/sus-git-token").status_code == 403
    assert c.post("/api/secrets",
                  json={"name": "sus-git-token", "data": {"token": "x"}}).status_code == 403


def test_protected_set_is_extensible(monkeypatch):
    monkeypatch.setenv("SUS_PROTECTED_SECRETS", "extra-secret, another")
    assert secrets_mod._is_protected("extra-secret")
    assert secrets_mod._is_protected("another")
    assert secrets_mod._is_protected("sus-git-token")  # defaults still apply
    assert not secrets_mod._is_protected("app-config")
