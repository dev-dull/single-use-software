FROM python:3.12-slim

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    openssh-client \
    expect \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x (LTS) for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Install ttyd — terminal-to-WebSocket bridge
# Determine arch for download: aarch64 or x86_64
RUN ARCH=$(uname -m) && \
    curl -fsSL -o /usr/local/bin/ttyd \
    "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.${ARCH}" && \
    chmod +x /usr/local/bin/ttyd

# Create working directory
RUN mkdir -p /repo/claude/skills

# Copy CLAUDE.md with read-only permissions
COPY CLAUDE.md /repo/claude/CLAUDE.md
RUN chmod 444 /repo/claude/CLAUDE.md

# Copy skill definitions with read-only permissions
COPY claude/skills/ /repo/claude/skills/
RUN chmod 444 /repo/claude/skills/*.md

# Create non-root user for Claude Code (it refuses to run as root)
RUN useradd -m -s /bin/bash sus && chown -R sus:sus /repo
ENV PATH="/home/sus/.local/bin:${PATH}"

# Pre-configure Claude Code to suppress ALL interactive prompts:
# - ~/.claude/settings.json: disable auto-updater
# - ~/.claude.json: mark onboarding complete, trust /repo folder,
#   accept bypass mode, skip all first-run dialogs
RUN mkdir -p /home/sus/.claude && \
    echo '{"autoUpdaterStatus":"disabled","defaultMode":"bypassPermissions"}' > /home/sus/.claude/settings.json && \
    echo '{ \
      "numStartups": 100, \
      "hasCompletedOnboarding": true, \
      "lastOnboardingVersion": "9.9.9", \
      "lastReleaseNotesSeen": "9.9.9", \
      "autoUpdates": false, \
      "hasSeenTasksHint": true, \
      "opus46FeedSeenCount": 100, \
      "opus1mMergeNoticeSeenCount": 100, \
      "projects": { \
        "/repo": { \
          "allowedTools": [], \
          "hasTrustDialogAccepted": true, \
          "hasCompletedProjectOnboarding": true, \
          "projectOnboardingSeenCount": 100 \
        } \
      } \
    }' > /home/sus/.claude.json && \
    chown -R sus:sus /home/sus/.claude /home/sus/.claude.json

# Disable the Claude Code auto-updater at the environment level
ENV DISABLE_AUTOUPDATER=1

WORKDIR /repo

# Copy and set up entrypoint + expect wrapper
COPY entrypoint.sh /entrypoint.sh
COPY claude-wrapper.sh /claude-wrapper.sh
RUN chmod +x /entrypoint.sh /claude-wrapper.sh

# Expose ports:
#   8080 — Claude Code terminal (ttyd WebSocket)
#   3000 — App preview
EXPOSE 8080 3000

USER sus
ENTRYPOINT ["/entrypoint.sh"]
