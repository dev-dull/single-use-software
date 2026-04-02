#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# SUS Build Pod Entrypoint
#
# Environment variables (set by the landing page pod when creating this pod):
#   GIT_USER_NAME   — git commit author name
#   GIT_USER_EMAIL  — git commit author email
#   GIT_REPO_URL    — repository clone URL (SSH or HTTPS)
#   GIT_BRANCH      — branch to check out (empty = default branch)
#   ANTHROPIC_API_KEY — API key for Claude Code
# ---------------------------------------------------------------------------

# --- Git configuration ----------------------------------------------------

git config --global user.name  "${GIT_USER_NAME:-sus-user}"
git config --global user.email "${GIT_USER_EMAIL:-sus@localhost}"

# Trust the /repo directory
git config --global --add safe.directory /repo

# --- Clone or checkout ----------------------------------------------------

if [ -n "${GIT_REPO_URL:-}" ]; then
    if [ ! -d "/repo/.git" ]; then
        git clone "${GIT_REPO_URL}" /repo
    fi

    if [ -n "${GIT_BRANCH:-}" ]; then
        cd /repo
        # Fetch latest and check out the requested branch
        git fetch --all
        git checkout "${GIT_BRANCH}" 2>/dev/null || git checkout -b "${GIT_BRANCH}"
    fi
fi

cd /repo

# --- Start Claude Code CLI ------------------------------------------------
# Launch Claude Code in WebSocket mode so the landing page can proxy a
# terminal session from the browser.

exec claude --dangerously-skip-permissions
