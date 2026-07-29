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
#   CLAUDE_MODEL    — Claude model for the session (default: opus)
# ---------------------------------------------------------------------------

# --- Git configuration ----------------------------------------------------

git config --global user.name  "${GIT_USER_NAME:-sus-user}"
git config --global user.email "${GIT_USER_EMAIL:-sus@localhost}"
git config --global --add safe.directory /repo

# --- Build authenticated repo URL -----------------------------------------

REPO_URL="${GIT_REPO_URL:-}"
if [ -n "${GIT_TOKEN:-}" ] && [ -n "$REPO_URL" ]; then
    # Inject token as user:password credentials — the username-only form
    # (https://TOKEN@host) makes git prompt for a password and fail in a pod.
    REPO_URL=$(echo "$REPO_URL" | sed -e "s|^https://|https://x-access-token:${GIT_TOKEN}@|" -e "s|^http://|http://x-access-token:${GIT_TOKEN}@|")
fi

# --- Clone or init --------------------------------------------------------

cd /repo

if [ -n "$REPO_URL" ]; then
    # Clone the app repo.
    if [ ! -d "/repo/.git" ]; then
        git clone "$REPO_URL" /tmp/repo-clone
        # Make baked-in read-only files writable so clone can overwrite them.
        # (Platform CLAUDE.md lives at ~/.claude/CLAUDE.md, outside /repo.)
        chmod -R u+w /repo/claude/ 2>/dev/null || true
        cp -a /tmp/repo-clone/. /repo/
        # Restore read-only on skills.
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

# If this is a new app, create a minimal sus.json. The absence of sus.json is
# also our "brand-new app" signal (an existing app's clone brings its own down),
# and it's restart-safe: a recreated pod re-clones the now-committed scaffold, so
# NEW_APP reads 0 and we don't re-kick a build on restart.
NEW_APP=0
if [ ! -f "$APP_DIR/sus.json" ]; then
    NEW_APP=1
    # Build the manifest with json.dump, not a heredoc: APP_NAME and especially
    # APP_DESCRIPTION are free-form user input (a <textarea>), so a quote or
    # newline spliced into hand-written JSON yields an invalid sus.json — and
    # catalog.py silently drops apps whose manifest won't parse.
    APP_DIR="$APP_DIR" python3 - <<'PYEOF'
import datetime, json, os
data = {
    "name": os.environ.get("APP_NAME") or "New App",
    "description": os.environ.get("APP_DESCRIPTION", ""),
    "owner": os.environ.get("USER_ID") or "anonymous",
    "team": os.environ.get("APP_TEAM") or "_new",
    "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
    "visibility": ["default"],
    "default_stack": "python+htmx",
    "tags": [],
}
with open(os.path.join(os.environ["APP_DIR"], "sus.json"), "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
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

# Pre-trust the exact cwd in ~/.claude.json. The Claude Code trust dialog is
# keyed to the exact working directory, so the baked-in /repo entry doesn't
# cover /repo/{team}/{app-slug}. Also pre-ack the bypass-mode warning and
# stamp the API key as approved. Speculative keys (vary by version) are
# harmless if Claude ignores them.
export APP_DIR
python3 - <<'PYEOF'
import json, os
path = "/home/sus/.claude.json"
with open(path) as f:
    data = json.load(f)

app_dir = os.environ["APP_DIR"]
trust = {
    "allowedTools": [],
    "hasTrustDialogAccepted": True,
    "hasCompletedProjectOnboarding": True,
    "projectOnboardingSeenCount": 100,
    "hasAcceptedBypassPermissionsMode": True,
    "bypassPermissionsModeAccepted": True,
}
projects = data.setdefault("projects", {})
for p in (app_dir, os.path.dirname(app_dir), "/repo"):
    projects[p] = {**projects.get(p, {}), **trust}

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if api_key:
    data["customApiKeyResponses"] = {"approved": [api_key[-20:]], "rejected": []}

data["hasAcceptedBypassPermissionsMode"] = True
data["bypassPermissionsModeAccepted"] = True

with open(path, "w") as f:
    json.dump(data, f)
PYEOF

# For a brand-new app with a description, hand Claude an initial prompt so it
# starts building to spec on the first turn — otherwise the form description
# only reaches the session as an env var CLAUDE.md *asks* Claude to read, which
# isn't guaranteed. Gated to NEW_APP: an existing-app "Build" session must NOT
# be auto-kicked — its sus.json description may be stale and the user is about
# to say what they want.
#
# One-shot, and this matters: ttyd spawns a fresh `claude` per *client
# connection*, and the frontend reconnects on its own (terminal-iframe reload on
# a not-ready blip, a full page reload after ~15s, a manual refresh, a second
# tab). If every connection were seeded, a reconnect hours into a session would
# re-run "build the initial version" over the user's work — and autosave would
# commit the clobber. So we drop the prompt in a seed file and let the inner
# shell claim it with an atomic `mv` that succeeds exactly once: only the first
# connection is seeded; every later one falls through to a plain interactive
# session. (NEW_APP alone can't gate this — it's fixed for the pod's lifetime.)
#
# APP_DESCRIPTION is untrusted: it's expanded into the seed file by the heredoc
# (bash does not re-scan an expansion's contents) and reaches claude as a single
# "$(cat …)" word — never spliced into the command string, so it cannot break
# quoting or inject shell.
if [ "${NEW_APP:-0}" = "1" ] && [ -n "${APP_DESCRIPTION:-}" ]; then
    SUS_SEED_FILE=/tmp/sus-initial-prompt
    cat > "$SUS_SEED_FILE" <<SEEDEOF
Build this app now and show it in the preview pane on the right. Here is what it should do:

${APP_DESCRIPTION}

Create the initial working version straight away, then tell me it's ready.
SEEDEOF
    export SUS_SEED_FILE
fi

export APP_DIR
export CLAUDE_MODEL="${CLAUDE_MODEL:-opus}"
# ttyd spawns a fresh `claude` per client connection, so consume the seed with
# an atomic `mv` that succeeds exactly once: the first connection is seeded,
# every later one (reconnect, refresh, second tab) falls through to a plain
# interactive session and never re-runs the build over the user's work.
#
# Deliberately NOT recovered: if an early reconnect kills the very first build
# before it writes a file, the replacement session is plain and the user just
# restates the request. Auto-recovering that (re-arming the seed) needs a
# claimant-liveness protocol whose races aren't worth it for a first-turn
# convenience — a plain session is a fine, non-destructive fallback.
#
# Single-quoted body on purpose: $APP_DIR/$SUS_SEED_FILE/$CLAUDE_MODEL and the
# $(cat …) are evaluated by the inner per-connection shell, not baked in once
# by this shell at exec time. The untrusted description lives only in the seed
# file and reaches claude as a single "$(cat …)" argv word — never spliced into
# the command string, so it can't break quoting or inject shell.
# shellcheck disable=SC2016
exec ttyd --port 8080 --writable --base-path / \
    bash -c '
        cd "$APP_DIR" || exit 1
        if [ -n "${SUS_SEED_FILE:-}" ] && mv "$SUS_SEED_FILE" "$SUS_SEED_FILE.used" 2>/dev/null; then
            exec claude --dangerously-skip-permissions --model "$CLAUDE_MODEL" "$(cat "$SUS_SEED_FILE.used")"
        fi
        exec claude --dangerously-skip-permissions --model "$CLAUDE_MODEL"
    '
