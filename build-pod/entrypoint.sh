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
#   APP_TEAM        — the team this app belongs to
#   APP_SLUG        — the app's short name
#   ANTHROPIC_API_KEY — API key for Claude Code
# ---------------------------------------------------------------------------

# --- Git configuration ----------------------------------------------------

git config --global user.name  "${GIT_USER_NAME:-sus-user}"
git config --global user.email "${GIT_USER_EMAIL:-sus@localhost}"
git config --global --add safe.directory /repo

# --- Build authenticated repo URL -----------------------------------------

REPO_URL="${GIT_REPO_URL:-}"
if [ -n "${GIT_TOKEN:-}" ] && [ -n "$REPO_URL" ]; then
    # Inject token into HTTP(S) URL: https://TOKEN@host/... or http://TOKEN@host/...
    REPO_URL=$(echo "$REPO_URL" | sed -e "s|^https://|https://${GIT_TOKEN}@|" -e "s|^http://|http://${GIT_TOKEN}@|")
fi

# --- Clone or init --------------------------------------------------------

cd /repo

if [ -n "$REPO_URL" ]; then
    # Clone the app repo.
    if [ ! -d "/repo/.git" ]; then
        git clone "$REPO_URL" /tmp/repo-clone
        # Make baked-in read-only files writable so clone can overwrite them.
        chmod -R u+w /repo/claude/ 2>/dev/null || true
        cp -a /tmp/repo-clone/. /repo/
        # Restore read-only on CLAUDE.md and skills.
        chmod 444 /repo/claude/CLAUDE.md 2>/dev/null || true
        chmod 444 /repo/claude/skills/*.md 2>/dev/null || true
        rm -rf /tmp/repo-clone
    fi

    if [ -n "${GIT_BRANCH:-}" ]; then
        git fetch --all 2>/dev/null || true
        git checkout "${GIT_BRANCH}" 2>/dev/null || git checkout -b "${GIT_BRANCH}"
    fi
else
    # No repo URL — initialize a local git repo.
    if [ ! -d "/repo/.git" ]; then
        git init
        git add -A
        git commit -m "chore: initial scaffold" --allow-empty 2>/dev/null || true
    fi

    if [ -n "${GIT_BRANCH:-}" ]; then
        git checkout "${GIT_BRANCH}" 2>/dev/null || git checkout -b "${GIT_BRANCH}"
    fi
fi

# --- Set up app working directory -----------------------------------------
# Claude works inside apps/{team}/{app-slug}/ per the monorepo layout.

APP_DIR="/repo/${APP_TEAM:-_new}/${APP_SLUG:-_new}"
mkdir -p "$APP_DIR"

# If this is a new app, create a minimal sus.json.
if [ ! -f "$APP_DIR/sus.json" ]; then
    cat > "$APP_DIR/sus.json" <<SUSJSON
{
  "name": "${APP_NAME:-New App}",
  "description": "${APP_DESCRIPTION:-}",
  "owner": "${USER_ID:-anonymous}",
  "team": "${APP_TEAM:-_new}",
  "created_at": "$(date -u +%Y-%m-%d)",
  "visibility": ["default"],
  "default_stack": "python+htmx",
  "tags": []
}
SUSJSON
    git add -A 2>/dev/null || true
    git commit -m "chore: scaffold ${APP_TEAM:-_new}/${APP_SLUG:-_new}" 2>/dev/null || true
fi

# --- Auto-commit loop -----------------------------------------------------

_autosave_loop() {
    while true; do
        sleep 300
        cd /repo
        if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
            git add -A
            git commit -m "chore: autosave" --no-verify 2>/dev/null || true
        fi
        # Push the working branch so work survives pod restarts.
        if [ -n "${GIT_BRANCH:-}" ] && git remote get-url origin >/dev/null 2>&1; then
            git push origin "${GIT_BRANCH}" 2>/dev/null || true
        fi
    done
}

# --- Server-side activity heartbeat ---------------------------------------
# Detects file changes and pings the landing page so the pod isn't reaped
# while Claude is actively working (even if the user's tab is backgrounded).
_activity_loop() {
    local last_mtime=""
    while true; do
        sleep 60
        # Get the most recent mtime of any file in the app dir.
        local cur_mtime
        cur_mtime=$(find "$APP_DIR" -type f -not -path '*/.git/*' -not -path '*/__pycache__/*' -printf '%T@\n' 2>/dev/null | sort -n | tail -1)
        # Also check for any uncommitted changes (Claude actively writing).
        local has_changes=""
        if [ -d /repo/.git ]; then
            has_changes=$(cd /repo && git status --porcelain 2>/dev/null | head -1)
        fi
        if [ "$cur_mtime" != "$last_mtime" ] || [ -n "$has_changes" ]; then
            last_mtime="$cur_mtime"
            # Files changed — ping the landing page heartbeat endpoint.
            if [ -n "${SUS_API_URL:-}" ] && [ -n "${APP_TEAM:-}" ] && [ -n "${APP_SLUG:-}" ]; then
                curl -s -o /dev/null -X POST "${SUS_API_URL}/build/${APP_TEAM}/${APP_SLUG}/heartbeat" 2>/dev/null || true
            fi
        fi
    done
}

_autosave_loop &
_activity_loop &

# --- Runner: auto-start app on port 3000 ---------------------------------
# Watches the app directory for servable content.

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
    if [ -n "$SERVER_TYPE" ] && [ "$SERVER_TYPE" != "$new_type" ]; then
        _kill_server
    fi
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        return
    fi

    SERVER_TYPE="$new_type"
    cd "$APP_DIR"

    case "$new_type" in
        python)
            pip install --user -q -r requirements.txt 2>/dev/null || true
            python3 -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload &
            SERVER_PID=$!
            ;;
        node)
            npm install --silent 2>/dev/null || true
            if grep -q '"start"' package.json 2>/dev/null; then
                npm start &
            else
                node server.js &
            fi
            SERVER_PID=$!
            ;;
        static)
            python3 -m http.server 3000 --bind 0.0.0.0 &
            SERVER_PID=$!
            ;;
    esac
}

_runner_loop() {
    while true; do
        sleep 5
        detected=""
        if [ -f "$APP_DIR/requirements.txt" ]; then
            if grep -qiE 'fastapi|uvicorn' "$APP_DIR/requirements.txt" 2>/dev/null; then
                detected="python"
            fi
        fi
        if [ -z "$detected" ] && [ -f "$APP_DIR/package.json" ]; then
            detected="node"
        fi
        if [ -z "$detected" ] && [ -f "$APP_DIR/index.html" ]; then
            detected="static"
        fi
        if [ -z "$detected" ]; then
            continue
        fi
        if [ -n "$SERVER_TYPE" ] && [ "$SERVER_TYPE" != "$detected" ]; then
            _kill_server
        fi
        if [ -n "$SERVER_PID" ] && ! kill -0 "$SERVER_PID" 2>/dev/null; then
            SERVER_PID=""
            SERVER_TYPE=""
        fi
        _start_server "$detected"
    done
}

_runner_loop &

# --- Start Claude Code CLI via ttyd ---------------------------------------

export DISABLE_AUTOUPDATER=1

# Ensure the app directory exists and start Claude there.
mkdir -p "$APP_DIR"
cd "$APP_DIR"

exec ttyd --port 8080 --writable --base-path / \
    bash -c "cd '$APP_DIR' && exec claude --dangerously-skip-permissions --model sonnet"
