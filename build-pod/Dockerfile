FROM python:3.12-slim

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x (LTS) for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Create working directory
RUN mkdir -p /repo/claude/skills

# Copy CLAUDE.md with read-only permissions
COPY CLAUDE.md /repo/claude/CLAUDE.md
RUN chmod 444 /repo/claude/CLAUDE.md

# Copy skill definitions with read-only permissions
COPY claude/skills/ /repo/claude/skills/
RUN chmod 444 /repo/claude/skills/*.md

WORKDIR /repo

# Copy and set up entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose ports:
#   8080 — Claude Code terminal (WebSocket)
#   3000 — App preview
EXPOSE 8080 3000

ENTRYPOINT ["/entrypoint.sh"]
