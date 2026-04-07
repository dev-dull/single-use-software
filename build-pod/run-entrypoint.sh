#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# SUS Run Pod Entrypoint
#
# Long-lived pod that serves a published app on port 3000.
# Clones the app repo, checks out main, and runs the appropriate server
# based on the app's files (FastAPI, Node, or static).
#
# Environment variables:
#   GIT_REPO_URL  — repository clone URL
#   GIT_TOKEN     — token for HTTPS auth (optional)
#   APP_TEAM      — the app's category
#   APP_SLUG      — the app's slug
# ---------------------------------------------------------------------------

git config --global user.name  "sus-runner"
git config --global user.email "sus-runner@localhost"
git config --global --add safe.directory /repo

REPO_URL="${GIT_REPO_URL:-}"
if [ -n "${GIT_TOKEN:-}" ] && [ -n "$REPO_URL" ]; then
    REPO_URL=$(echo "$REPO_URL" | sed -e "s|^https://|https://${GIT_TOKEN}@|" -e "s|^http://|http://${GIT_TOKEN}@|")
fi

if [ -z "$REPO_URL" ]; then
    echo "ERROR: GIT_REPO_URL is not set" >&2
    exit 1
fi

# Clone the repo (always main).
cd /tmp
git clone --depth 1 "$REPO_URL" /tmp/repo-clone
mkdir -p /repo
cp -a /tmp/repo-clone/. /repo/
rm -rf /tmp/repo-clone

APP_DIR="/repo/${APP_TEAM}/${APP_SLUG}"
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: app directory $APP_DIR not found in repo" >&2
    exit 1
fi

cd "$APP_DIR"

# Detect stack and start the server.
if [ -f requirements.txt ] && grep -qiE 'fastapi|uvicorn' requirements.txt 2>/dev/null; then
    pip install --user -q -r requirements.txt
    exec python3 -m uvicorn main:app --host 0.0.0.0 --port 3000
elif [ -f package.json ]; then
    npm install --silent
    if grep -q '"start"' package.json; then
        exec npm start
    else
        exec node server.js
    fi
elif [ -f index.html ]; then
    exec python3 -m http.server 3000 --bind 0.0.0.0
else
    echo "ERROR: no recognized app stack in $APP_DIR" >&2
    exit 1
fi
