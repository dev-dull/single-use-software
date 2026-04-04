"""Sync the app repo to a local clone for catalog and run-mode serving."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

CLONE_DIR = Path(os.environ.get("SUS_REPO_CLONE_DIR", "/data/repo"))
APPS_DIR = CLONE_DIR


def _get_repo_url() -> str:
    """Get the app repo URL, injecting the git token for HTTPS auth if available."""
    # Check ConfigMap first, then env var.
    url = ""
    try:
        from .repo_config import RepoConfigManager
        url = RepoConfigManager().get_url()
    except Exception:
        pass
    if not url:
        url = os.environ.get("SUS_GIT_REPO_URL", "")
    if not url:
        return ""

    # Try to get the git token from the K8s secret.
    token = None
    try:
        from .git_token import GitTokenManager
        mgr = GitTokenManager()
        token = mgr.get_token()
    except Exception:
        pass

    # Inject token into HTTPS URLs: https://TOKEN@github.com/...
    if token and url.startswith("https://"):
        url = re.sub(r"^https://", f"https://{token}@", url)

    return url


def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = ["git"] + list(args)
    return subprocess.run(cmd, cwd=cwd or CLONE_DIR, capture_output=True, text=True, timeout=60)


def clone_or_pull() -> bool:
    """Clone the app repo (first time) or pull latest changes."""
    url = _get_repo_url()
    if not url:
        logger.warning("SUS_GIT_REPO_URL not set — catalog will be empty")
        return False

    if (CLONE_DIR / ".git").is_dir():
        # Update the remote URL in case the token changed.
        _run_git("remote", "set-url", "origin", url)
        result = _run_git("pull", "--ff-only")
        if result.returncode == 0:
            logger.info("Pulled latest from app repo")
            return True
        else:
            logger.warning("Git pull failed: %s", result.stderr.strip())
            _run_git("fetch", "origin")
            _run_git("reset", "--hard", "origin/main")
            return True
    else:
        CLONE_DIR.mkdir(parents=True, exist_ok=True)
        result = _run_git("clone", url, str(CLONE_DIR))
        if result.returncode == 0:
            logger.info("Cloned app repo to %s", CLONE_DIR)
            return True
        else:
            logger.error("Git clone failed: %s", result.stderr.strip())
            return False


def get_apps_root() -> Path:
    """Return the path to the app directories in the local clone."""
    return APPS_DIR


async def start_sync_loop(interval_seconds: int = 30) -> None:
    """Periodically pull the app repo to pick up published apps."""
    clone_or_pull()
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            clone_or_pull()
        except Exception:
            logger.exception("Repo sync failed")
