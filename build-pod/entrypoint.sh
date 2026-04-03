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

cd /repo

if [ -n "${GIT_REPO_URL:-}" ] && [ "${GIT_REPO_URL}" != "https://github.com/sus/"* ]; then
    # A real repo URL was provided — clone if not already cloned.
    if [ ! -d "/repo/.git" ]; then
        git clone "${GIT_REPO_URL}" /tmp/repo-clone
        cp -a /tmp/repo-clone/. /repo/
        rm -rf /tmp/repo-clone
    fi

    if [ -n "${GIT_BRANCH:-}" ]; then
        git fetch --all 2>/dev/null || true
        git checkout "${GIT_BRANCH}" 2>/dev/null || git checkout -b "${GIT_BRANCH}"
    fi
else
    # No valid repo URL — initialize a local git repo for autosave.
    if [ ! -d "/repo/.git" ]; then
        git init
        git add -A
        git commit -m "chore: initial scaffold" --allow-empty 2>/dev/null || true
    fi

    if [ -n "${GIT_BRANCH:-}" ]; then
        git checkout "${GIT_BRANCH}" 2>/dev/null || git checkout -b "${GIT_BRANCH}"
    fi
fi

# --- Auto-commit loop -----------------------------------------------------
# Runs in the background every 5 minutes.  If there are uncommitted changes
# it creates a lightweight "autosave" commit so work is never lost.

_autosave_loop() {
    while true; do
        sleep 300  # 5 minutes
        # Only commit if there are tracked or untracked changes
        if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
            git add -A
            git commit -m "chore: autosave" --no-verify 2>/dev/null || true
        fi
    done
}

_autosave_loop &

# --- Start Claude Code CLI via ttyd ---------------------------------------
# ttyd exposes the Claude Code CLI as a WebSocket terminal on port 8080.
# The landing page proxies the browser's xterm.js to this WebSocket.

exec ttyd --port 8080 --writable --base-path / claude --dangerously-skip-permissions
