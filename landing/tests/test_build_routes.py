"""Route-level tests for build readiness + server-side pod resolution.

Proves the request-layer behaviour of the #91/#80 fix without a cluster:
- /status reflects resolver + terminal readiness,
- proxy routes 503 when the pod isn't resolvable,
- a forged ?pod_ip query param has no effect (the route no longer reads it).
"""

import app.routes.build as build
from app.deps import resolve_identity
from app.identity import UserIdentity
from app.main import app
from fastapi.testclient import TestClient


class _FakeWorkflow:
    def __init__(self, pod_ip=None, ready=False):
        self._pod_ip = pod_ip
        self._ready = ready
        self.start_session_called = False

    def resolve_pod_ip(self, user_id, app_slug):
        return self._pod_ip

    def is_terminal_ready(self, pod_ip):
        return self._ready

    def start_session(self, **kwargs):
        self.start_session_called = True
        return {"pod_name": "build-x", "branch": "b"}


def _client(pod_ip=None, ready=False):
    build._workflow = _FakeWorkflow(pod_ip=pod_ip, ready=ready)
    app.dependency_overrides[resolve_identity] = lambda: UserIdentity(
        id="alice", display_name="Alice", groups=["default"]
    )
    return TestClient(app)


def teardown_function(_):
    app.dependency_overrides.clear()
    build._workflow = None


def test_status_not_ready_when_no_pod():
    r = _client(pod_ip=None).get("/build/games/minesweeper/status")
    assert r.status_code == 200
    assert r.json() == {"ready": False, "phase": "starting"}


def test_status_ready_when_pod_and_ttyd_up():
    r = _client(pod_ip="10.42.1.9", ready=True).get("/build/games/minesweeper/status")
    assert r.json() == {"ready": True, "phase": "running"}


def test_status_starting_when_pod_but_ttyd_down():
    # Pod scheduled with an IP, but ttyd not serving yet -> not ready.
    r = _client(pod_ip="10.42.1.9", ready=False).get("/build/games/minesweeper/status")
    assert r.json() == {"ready": False, "phase": "starting"}


def test_terminal_token_503_when_not_resolvable():
    r = _client(pod_ip=None).get("/build/games/minesweeper/terminal/token")
    assert r.status_code == 503


def test_forged_pod_ip_query_is_ignored():
    # #80: the route resolves the pod server-side; a client-supplied pod_ip
    # must have no effect. Resolver returns None -> 503 regardless of the param.
    r = _client(pod_ip=None).get(
        "/build/games/minesweeper/terminal/token?pod_ip=10.99.99.99"
    )
    assert r.status_code == 503
