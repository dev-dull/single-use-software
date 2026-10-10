"""Auth + denylist tests for the /api/secrets router (#79).

The router exposes CRUD over cluster secrets. It must reject unauthenticated
(guest) callers — build/run pods call the platform API directly and resolve to
``guest`` — and must never expose or mutate platform-owned secrets, even for an
authenticated operator.
"""

import importlib
import pathlib
import re
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


# --- the /setup router writes the same secrets, so it is gated too (#79) --

def test_setup_routes_require_operator():
    # /setup/{git-token,api-key,repo-url} write the platform's own credentials;
    # a guest (any build/run pod) must not reach them.
    c = _client(_GUEST)
    assert c.get("/setup").status_code == 403
    assert c.post("/setup/api-key", data={"api_key": "sk-x"}).status_code == 403
    assert c.post("/setup/git-token", data={"git_token": "ghp_x"}).status_code == 403
    assert c.post("/setup/repo-url", data={"repo_url": "https://evil/r"}).status_code == 403


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


# --- denylist must cover every platform-managed secret --------------------
# In single-user mode and in open-proxy (no trusted_proxies) mode the auth gate
# is bypassed and this denylist is the *only* thing protecting platform creds
# from a pod. So if a future module starts managing a secret, its name must be
# in _DEFAULT_PROTECTED_SECRETS. Discover such modules by source scan (avoids
# import side effects), then import the matches and assert coverage.

_APP_DIR = pathlib.Path(secrets_mod.__file__).resolve().parent.parent  # landing/app
_DEFINES_SECRET_NAME = re.compile(r"^SECRET_NAME\s*=", re.MULTILINE)


def _modules_defining_secret_name():
    mods = []
    for py in _APP_DIR.rglob("*.py"):
        if _DEFINES_SECRET_NAME.search(py.read_text()):
            rel = py.relative_to(_APP_DIR).with_suffix("")
            mods.append("app." + ".".join(rel.parts))
    return mods


def test_denylist_covers_all_platform_secret_names():
    modules = _modules_defining_secret_name()
    # The git-token and api-key managers are the baseline; fail loudly if the
    # scan finds nothing (e.g. constant renamed) rather than passing vacuously.
    assert modules, "expected modules defining SECRET_NAME (git_token, api_key)"
    protected = secrets_mod._DEFAULT_PROTECTED_SECRETS
    missing = []
    for dotted in modules:
        name = getattr(importlib.import_module(dotted), "SECRET_NAME", None)
        if name and name not in protected:
            missing.append((dotted, name))
    assert not missing, (
        f"platform-managed secrets missing from _DEFAULT_PROTECTED_SECRETS: "
        f"{missing} — add them so they stay protected when the auth gate is "
        f"bypassed (single-user / open-proxy modes)"
    )
