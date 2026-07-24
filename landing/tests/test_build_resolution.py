"""Unit tests for server-side build-pod resolution + terminal readiness.

These back the #91/#80 fix: the pod address is resolved from the session
server-side (never trusted from the client), and terminal readiness reflects
ttyd actually serving, not just the pod being scheduled.
"""

import httpx

from app.git_workflow import GitWorkflowManager


class _FakeSessions:
    def __init__(self, session):
        self._session = session

    def get(self, user_id, app_slug):
        return self._session


class _FakePods:
    def __init__(self, pod_info):
        self._pod_info = pod_info

    def get_build_pod(self, pod_name):
        return self._pod_info


def _wf(session, pod_info):
    return GitWorkflowManager(_FakePods(pod_info), _FakeSessions(session))


def test_resolve_pod_ip_running():
    wf = _wf(
        session={"pod_name": "build-alice-abc"},
        pod_info={"phase": "Running", "pod_ip": "10.42.1.9"},
    )
    assert wf.resolve_pod_ip("alice", "hello-world") == "10.42.1.9"


def test_resolve_pod_ip_no_session():
    wf = _wf(session=None, pod_info={"phase": "Running", "pod_ip": "10.42.1.9"})
    assert wf.resolve_pod_ip("alice", "hello-world") is None


def test_resolve_pod_ip_pod_gone():
    # Session record exists but the pod is no longer there.
    wf = _wf(session={"pod_name": "build-alice-abc"}, pod_info=None)
    assert wf.resolve_pod_ip("alice", "hello-world") is None


def test_resolve_pod_ip_pod_not_running():
    wf = _wf(
        session={"pod_name": "build-alice-abc"},
        pod_info={"phase": "Failed", "pod_ip": "10.42.1.9"},
    )
    assert wf.resolve_pod_ip("alice", "hello-world") is None


def test_resolve_pod_ip_scheduled_without_ip():
    # Pending pod that hasn't been assigned an IP yet -> not resolvable.
    wf = _wf(
        session={"pod_name": "build-alice-abc"},
        pod_info={"phase": "Pending", "pod_ip": None},
    )
    assert wf.resolve_pod_ip("alice", "hello-world") is None


def test_is_terminal_ready_true(monkeypatch):
    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    assert GitWorkflowManager.is_terminal_ready("10.42.1.9") is True


def test_is_terminal_ready_empty_ip():
    assert GitWorkflowManager.is_terminal_ready("") is False
    assert GitWorkflowManager.is_terminal_ready(None) is False


def test_is_terminal_ready_connection_error(monkeypatch):
    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "Client", _Client)
    assert GitWorkflowManager.is_terminal_ready("10.42.1.9") is False
