"""Unit tests for ProxyHeaderProvider trust + header parsing.

Security-sensitive: verifies that identity headers are honoured only from a
trusted proxy peer and ignored (forge-proof) from anywhere else.
"""

import asyncio

from starlette.requests import Request

from app.identity import ProxyHeaderProvider


def _request(client_ip: str, headers: dict[str, str]) -> Request:
    """Build a minimal ASGI Request with a fixed peer IP and headers."""
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (client_ip, 54321),
    }
    return Request(scope)


def _resolve(provider: ProxyHeaderProvider, request: Request):
    return asyncio.run(provider.resolve(request))


TRUSTED = ["10.42.0.0/16"]


def test_honors_remote_headers_from_trusted_peer():
    provider = ProxyHeaderProvider(trusted_proxies=TRUSTED)
    req = _request(
        "10.42.0.5",
        {
            "Remote-User": "alice",
            "Remote-Name": "Alice Example",
            "Remote-Groups": "admins, default",
        },
    )
    identity = _resolve(provider, req)
    assert identity.id == "alice"
    assert identity.display_name == "Alice Example"
    assert list(identity.groups) == ["admins", "default"]


def test_ignores_forged_headers_from_untrusted_peer():
    provider = ProxyHeaderProvider(trusted_proxies=TRUSTED)
    # A workload pod outside the trusted range trying to impersonate admin.
    req = _request("192.168.1.50", {"Remote-User": "admin"})
    identity = _resolve(provider, req)
    assert identity.id == "guest"
    assert identity.groups == ["guest"]


def test_x_forwarded_fallback_from_trusted_peer():
    provider = ProxyHeaderProvider(trusted_proxies=TRUSTED)
    req = _request(
        "10.42.0.9",
        {"X-Forwarded-User": "bob", "X-Forwarded-Groups": "default"},
    )
    identity = _resolve(provider, req)
    assert identity.id == "bob"
    assert list(identity.groups) == ["default"]


def test_trusted_peer_without_headers_is_guest():
    provider = ProxyHeaderProvider(trusted_proxies=TRUSTED)
    req = _request("10.42.0.5", {})
    identity = _resolve(provider, req)
    assert identity.id == "guest"


def test_no_trusted_proxies_honors_headers_open_mode():
    # Back-compat: with no trust anchor configured, headers are honoured from
    # any peer (and a warning is logged).
    provider = ProxyHeaderProvider(trusted_proxies=[])
    req = _request("203.0.113.7", {"Remote-User": "carol"})
    identity = _resolve(provider, req)
    assert identity.id == "carol"


def test_bare_host_ip_trusted_proxy():
    # A single host address (no CIDR suffix) is treated as a /32.
    provider = ProxyHeaderProvider(trusted_proxies=["10.43.0.10"])
    trusted = _resolve(provider, _request("10.43.0.10", {"Remote-User": "dana"}))
    assert trusted.id == "dana"
    untrusted = _resolve(provider, _request("10.43.0.11", {"Remote-User": "dana"}))
    assert untrusted.id == "guest"
