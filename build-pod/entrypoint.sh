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

# --- Runner: auto-start app on port 3000 ---------------------------------
# Background watcher that detects servable content in /repo and starts the
# appropriate server process.  Checks every 5 seconds.

SERVER_PID=""
SERVER_TYPE=""

_kill_server() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    SERVER_PID=""
    SERVER_TYPE=""
}

_start_server() {
    local new_type="$1"

    # If the stack changed, kill the old server first
    if [ -n "$SERVER_TYPE" ] && [ "$SERVER_TYPE" != "$new_type" ]; then
        _kill_server
    fi

    # Already running with the right type — nothing to do
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        return
    fi

    SERVER_TYPE="$new_type"

    case "$new_type" in
        python)
            cd /repo
            pip install -q -r requirements.txt 2>/dev/null || true
            uvicorn main:app --host 0.0.0.0 --port 3000 --reload &
            SERVER_PID=$!
            ;;
        node)
            cd /repo
            npm install --silent 2>/dev/null || true
            if grep -q '"start"' /repo/package.json 2>/dev/null; then
                npm start &
            else
                node server.js &
            fi
            SERVER_PID=$!
            ;;
        static)
            cd /repo
            python3 -m http.server 3000 &
            SERVER_PID=$!
            ;;
    esac
}

_runner_loop() {
    while true; do
        sleep 5

        # Determine what kind of project exists in /repo
        detected=""
        if [ -f /repo/requirements.txt ]; then
            if grep -qiE 'fastapi|uvicorn' /repo/requirements.txt 2>/dev/null; then
                detected="python"
            fi
        fi

        if [ -z "$detected" ] && [ -f /repo/package.json ]; then
            detected="node"
        fi

        if [ -z "$detected" ] && [ -f /repo/index.html ]; then
            detected="static"
        fi

        if [ -z "$detected" ]; then
            continue
        fi

        # If stack changed, kill old server
        if [ -n "$SERVER_TYPE" ] && [ "$SERVER_TYPE" != "$detected" ]; then
            _kill_server
        fi

        # Restart if the server died
        if [ -n "$SERVER_PID" ] && ! kill -0 "$SERVER_PID" 2>/dev/null; then
            SERVER_PID=""
            SERVER_TYPE=""
        fi

        _start_server "$detected"
    done
}

_runner_loop &

# --- Start Claude Code CLI via ttyd ---------------------------------------
# ttyd exposes the Claude Code CLI as a WebSocket terminal on port 8080.
# The landing page proxies the browser's xterm.js to this WebSocket.

exec ttyd --port 8080 --writable --base-path / claude --dangerously-skip-permissions
