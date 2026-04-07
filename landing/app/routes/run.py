"""Run-mode routes — serve published apps via proxied run pods."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from ..proxy import http_proxy
from ..published_apps import PublishedAppStore
from ..run_pods import RunPodManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/run")

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# Lazy-initialised singleton
# ---------------------------------------------------------------------------

_run_pod_mgr: Optional[RunPodManager] = None
_published_store: Optional[PublishedAppStore] = None


def _get_run_pod_mgr() -> RunPodManager:
    global _run_pod_mgr
    if _run_pod_mgr is None:
        _run_pod_mgr = RunPodManager()
    return _run_pod_mgr


def _get_published_store() -> PublishedAppStore:
    global _published_store
    if _published_store is None:
        _published_store = PublishedAppStore()
    return _published_store


# ---------------------------------------------------------------------------
# Run UI
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}", response_class=HTMLResponse)
async def run_ui(
    request: Request,
    team: str,
    app_slug: str,
) -> HTMLResponse:
    """Render the run-mode page with the app in a full-page iframe."""
    return _templates.TemplateResponse(
        request,
        "run.html",
        context={
            "team": team,
            "app_slug": app_slug,
        },
    )


# ---------------------------------------------------------------------------
# HTTP proxy — run pod app traffic
# ---------------------------------------------------------------------------


@router.get("/{team}/{app_slug}/proxy/{path:path}")
async def run_proxy(
    request: Request,
    team: str,
    app_slug: str,
    path: str,
) -> Response:
    """Proxy HTTP requests to the published app.

    First checks the published apps store (MVP: proxies to the build pod).
    Falls back to looking for a dedicated run pod by labels.
    Returns 503 if no serving endpoint is available.
    """
    pod_ip = None

    # 1. Check published apps store (MVP: build pod as run target).
    try:
        store = _get_published_store()
        published = store.get(team, app_slug)
        if published:
            pod_ip = published.get("pod_ip")
    except Exception:
        logger.exception("Failed to check published store for %s/%s", team, app_slug)

    # 2. Fall back to dedicated run pod lookup.
    if not pod_ip:
        try:
            mgr = _get_run_pod_mgr()
            pod_info = mgr.find_run_pod(team, app_slug)
            if pod_info:
                pod_ip = pod_info.get("pod_ip")
        except Exception:
            logger.exception("Failed to look up run pod for %s/%s", team, app_slug)

    # Try proxying to the pod. If it fails (stale IP, deleted pod), clear
    # pod_ip and fall through to static file serving.
    if pod_ip:
        try:
            resp = await http_proxy(
                request,
                pod_ip=pod_ip,
                pod_port=3000,
                path=f"/{path}" if path else "/",
            )
            if resp.status_code != 502:
                return resp
            logger.warning("502 from pod_ip %s for %s/%s — falling through to static files", pod_ip, team, app_slug)
        except Exception:
            logger.warning("Stale pod_ip %s for %s/%s — falling through to static files", pod_ip, team, app_slug)

    # 3. Fall back to serving static files from the repo clone (for static apps).
    from ..repo_sync import get_apps_root
    app_dir = get_apps_root() / team / app_slug
    serve_path = path.strip("/") if path.strip("/") else "index.html"
    static_file = app_dir / serve_path
    if static_file.is_file():
        from fastapi.responses import FileResponse
        return FileResponse(static_file)

    # 4. App exists in the repo but no running pod —
    # check if a pod is already starting, otherwise create one.
    sus_json = app_dir / "sus.json"
    if sus_json.is_file():
        try:
            import os
            mgr = _get_run_pod_mgr()
            build_image = os.environ.get("SUS_BUILD_IMAGE", "")
            if build_image:
                # Check if a pod for this app is already pending/starting.
                existing = mgr.find_run_pod(team, app_slug)
                if not existing:
                    logger.info("Auto-creating run pod for %s/%s", team, app_slug)
                    mgr.create_run_pod(team=team, app_slug=app_slug, image=build_image)

                # Return a loading page that auto-refreshes.
                return _starting_page(team, app_slug)
        except Exception:
            logger.exception("Failed to auto-create run pod for %s/%s", team, app_slug)

    return Response(
        content="This app hasn't been published yet. Build it first!",
        status_code=503,
    )


def _starting_page(team: str, app_slug: str) -> HTMLResponse:
    """Return a loading page that auto-refreshes while the run pod starts."""
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Starting {team}/{app_slug}...</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🤨</text></svg>" />
  <meta http-equiv="refresh" content="5" />
  <style>
    body {{
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      height: 100vh; margin: 0; font-family: -apple-system, sans-serif;
      background: #0f0f13; color: #f5f0e8;
    }}
    .spinner {{
      width: 48px; height: 48px; border: 4px solid #333;
      border-top: 4px solid #4a7c8e; border-radius: 50%;
      animation: spin 1s linear infinite; margin-bottom: 1.5rem;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    h1 {{ font-size: 1.5rem; margin: 0 0 .5rem; font-weight: 400; }}
    p  {{ color: #888; margin: .25rem 0; font-size: .9rem; }}
    .app-name {{ color: #4a7c8e; font-weight: 600; }}
    .countdown {{ color: #666; font-size: .8rem; margin-top: 1.5rem; }}
  </style>
  <script>
    // Track elapsed time in localStorage so we can show a real error after a timeout.
    const key = 'sus-starting-{team}-{app_slug}';
    const start = parseInt(localStorage.getItem(key) || '0');
    const now = Date.now();
    if (!start) {{ localStorage.setItem(key, now.toString()); }}
    const elapsed = start ? Math.floor((now - start) / 1000) : 0;
    if (elapsed > 300) {{ // 5 minute timeout
      localStorage.removeItem(key);
      document.title = 'Failed to start';
      window.stop();
      document.addEventListener('DOMContentLoaded', () => {{
        document.body.innerHTML = `
          <div style="text-align:center; max-width: 500px; padding: 2rem;">
            <div style="font-size:3rem; margin-bottom:1rem;">😞</div>
            <h1>The app didn't start in time</h1>
            <p>We waited 5 minutes for <span class="app-name">{team}/{app_slug}</span> to start, but it didn't respond.</p>
            <p>This usually means the app has an error or is missing dependencies.</p>
            <p style="margin-top:1.5rem;">
              <a href="/build/{team}/{app_slug}" style="color:#4a7c8e;">Open in build mode to investigate</a> ·
              <a href="/" style="color:#888;">Back to catalog</a>
            </p>
          </div>`;
      }});
    }} else {{
      window.addEventListener('load', () => {{
        document.getElementById('elapsed').textContent = elapsed + 's';
      }});
    }}
  </script>
</head>
<body>
  <div class="spinner"></div>
  <h1>Starting <span class="app-name">{team}/{app_slug}</span>...</h1>
  <p>The app is being prepared. This usually takes 30-90 seconds.</p>
  <p class="countdown">Waiting <span id="elapsed">0s</span> · Auto-refreshing every 5 seconds</p>
</body>
</html>""")
