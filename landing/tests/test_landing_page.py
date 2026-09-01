"""Landing page + static-asset smoke tests.

The desktop rewrite (#112) replaced the landing page and repointed ~10 templates
at assets served by a new StaticFiles mount that didn't exist before. These
guard the failure modes that would otherwise only surface in a browser: the page
rendering (broken template context), the mount serving the shared theme (missing
mount / Dockerfile COPY regression), and the cache policy for static assets.
"""

from app.deps import resolve_identity
from app.identity import UserIdentity
from app.main import app
from fastapi.testclient import TestClient


def _client():
    app.dependency_overrides[resolve_identity] = lambda: UserIdentity(
        id="alice", display_name="Alice", groups=["default"]
    )
    return TestClient(app)


def teardown_function(_):
    app.dependency_overrides.clear()


def test_landing_page_renders_and_links_theme():
    r = _client().get("/")
    assert r.status_code == 200
    # The desktop links the shared theme + the glue script.
    assert "/static/desktop/theme.css" in r.text
    assert "/static/desktop/desktop.js" in r.text


def test_static_theme_css_is_served():
    r = _client().get("/static/desktop/theme.css")
    assert r.status_code == 200
    assert "--accent" in r.text  # the token stylesheet


def test_static_assets_are_not_no_store():
    # Static assets must be revalidated (no-cache), not no-store like dynamic
    # pages — otherwise the desktop CSS/JS is re-downloaded in full every load.
    r = _client().get("/static/desktop/theme.css")
    cache_control = r.headers.get("cache-control", "")
    assert "no-store" not in cache_control


def test_landing_page_renders_folders_and_app_icons(monkeypatch):
    # scan_apps() returns [] when /repo/apps is absent (the CI default), so the
    # populated branch — the folder loop, per-team <template>s, and the data-*
    # attributes desktop.js reads — needs a real catalog to exercise it.
    monkeypatch.setattr(
        "app.main.scan_apps",
        lambda **kw: [
            {"name": "Widget", "team": "acme", "slug": "widget",
             "description": "d", "tags": ["x"]},
        ],
    )
    r = _client().get("/")
    assert r.status_code == 200
    assert 'class="icon icon--folder"' in r.text
    assert 'data-team="acme"' in r.text
    assert 'data-run-url="/run/acme/widget"' in r.text
    assert 'data-build-url="/build/acme/widget"' in r.text
