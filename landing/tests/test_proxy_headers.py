"""Unit tests for proxy header handling.

Security-sensitive: the proxy must strip all inbound identity headers (they
are only verified at the landing pod, not forwardable) and inject verified
X-SUS-* values so apps get an unforgeable viewer identity.
"""

from app.identity import UserIdentity
from app.proxy import build_proxy_headers


def test_injects_verified_identity():
    identity = UserIdentity(id="alice", display_name="Alice Test",
                            groups=["admins", "default"])
    out = build_proxy_headers({"Accept": "text/html"}, identity)
    assert out["X-SUS-User"] == "alice"
    assert out["X-SUS-Name"] == "Alice Test"
    assert out["X-SUS-Groups"] == "admins,default"
    assert out["Accept"] == "text/html"


def test_strips_forged_identity_headers():
    identity = UserIdentity(id="alice", display_name="Alice", groups=["default"])
    inbound = {
        "Remote-User": "admin",
        "Remote-Groups": "admins",
        "X-Forwarded-User": "admin",
        "X-SUS-User": "admin",
        "Accept": "text/html",
    }
    out = build_proxy_headers(inbound, identity)
    # Forged values must not survive; verified identity wins.
    assert out["X-SUS-User"] == "alice"
    assert out["X-SUS-Groups"] == "default"
    assert "Remote-User" not in out
    assert "Remote-Groups" not in out
    assert "X-Forwarded-User" not in out


def test_guest_defaults_without_identity():
    out = build_proxy_headers({"Remote-User": "admin"}, identity=None)
    assert out["X-SUS-User"] == "guest"
    assert out["X-SUS-Name"] == "Guest"
    assert out["X-SUS-Groups"] == "guest"
    assert "Remote-User" not in out


def test_strips_hop_by_hop_and_host():
    out = build_proxy_headers(
        {"Host": "sus.local", "Connection": "keep-alive",
         "Accept-Encoding": "gzip", "X-Custom": "kept"},
        None,
    )
    assert "Host" not in out
    assert "Connection" not in out
    assert "Accept-Encoding" not in out
    assert out["X-Custom"] == "kept"
