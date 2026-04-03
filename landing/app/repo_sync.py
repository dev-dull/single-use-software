"""Sync the monorepo to a local clone for catalog and run-mode serving."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

CLONE_DIR = Path(os.environ.get("SUS_REPO_CLONE_DIR", "/data/repo"))
REPO_URL = os.environ.get("SUS_GIT_REPO_URL", "")
APPS_DIR = CLONE_DIR / "apps"


def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + list(args)
    return subprocess.run(
        cmd,
        cwd=cwd or CLONE_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )


def clone_or_pull() -> bool:
    """Clone the monorepo (first time) or pull latest changes.

    Returns True if successful, False otherwise.
    """
    if not REPO_URL:
        logger.warning("SUS_GIT_REPO_URL not set — catalog will be empty")
        return False

    if (CLONE_DIR / ".git").is_dir():
        # Already cloned — pull latest.
        result = _run_git("pull", "--ff-only", cwd=CLONE_DIR)
        if result.returncode == 0:
            logger.info("Pulled latest from %s", REPO_URL)
            return True
        else:
            logger.warning("Git pull failed: %s", result.stderr.strip())
            # Try a reset to recover from diverged state.
            _run_git("fetch", "origin", cwd=CLONE_DIR)
            _run_git("reset", "--hard", "origin/main", cwd=CLONE_DIR)
            return True
    else:
        # First clone.
        CLONE_DIR.mkdir(parents=True, exist_ok=True)
        result = _run_git("clone", REPO_URL, str(CLONE_DIR))
        if result.returncode == 0:
            logger.info("Cloned %s to %s", REPO_URL, CLONE_DIR)
            return True
        else:
            logger.error("Git clone failed: %s", result.stderr.strip())
            return False


def get_apps_root() -> Path:
    """Return the path to the apps/ directory in the local clone."""
    return APPS_DIR


async def start_sync_loop(interval_seconds: int = 30) -> None:
    """Periodically pull the monorepo to pick up new/updated apps."""
    # Initial clone.
    clone_or_pull()

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            clone_or_pull()
        except Exception:
            logger.exception("Repo sync failed")
