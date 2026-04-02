"""MCP (Model Context Protocol) server configuration manager."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str  # e.g., "sqlite-local", "postgres-analytics"
    command: str  # e.g., "npx", "uvx"
    args: list[str]  # e.g., ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "/data/analytics.db"]
    env: dict[str, str]  # additional env vars for the MCP server
    description: str  # human-readable description
    teams: list[str] = field(default_factory=list)  # which teams can use this (empty = all)


class MCPConfigManager:
    """Load, query, and persist MCP server configurations."""

    def __init__(self, config_path: str = "mcp_servers.json") -> None:
        self._path = Path(config_path)
        self._servers: dict[str, MCPServerConfig] = {}
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read the JSON config file and populate the in-memory map."""
        if not self._path.exists():
            return
        data = json.loads(self._path.read_text())
        for entry in data.get("servers", []):
            cfg = MCPServerConfig(
                name=entry["name"],
                command=entry["command"],
                args=entry.get("args", []),
                env=entry.get("env", {}),
                description=entry.get("description", ""),
                teams=entry.get("teams", []),
            )
            self._servers[cfg.name] = cfg

    def _persist(self) -> None:
        """Write the current server configs back to disk."""
        payload = {"servers": [asdict(s) for s in self._servers.values()]}
        self._path.write_text(json.dumps(payload, indent=2) + "\n")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_servers(self, team: str | None = None) -> list[MCPServerConfig]:
        """Return available MCP servers, optionally filtered by *team*.

        If *team* is ``None`` every server is returned.  Otherwise only
        servers that either have an empty ``teams`` list (available to all)
        or explicitly include *team* are returned.
        """
        servers = list(self._servers.values())
        if team is not None:
            servers = [s for s in servers if not s.teams or team in s.teams]
        return servers

    def get_server(self, name: str) -> MCPServerConfig | None:
        """Look up a single server by name."""
        return self._servers.get(name)

    def get_claude_mcp_config(self, team: str | None = None) -> dict:
        """Build the ``mcpServers`` dict in the format Claude Code expects.

        Example output::

            {
                "mcpServers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/repo/apps"],
                        "env": {}
                    }
                }
            }
        """
        servers = self.list_servers(team=team)
        mcp_servers: dict[str, dict] = {}
        for srv in servers:
            mcp_servers[srv.name] = {
                "command": srv.command,
                "args": srv.args,
                "env": srv.env,
            }
        return {"mcpServers": mcp_servers}

    def save_server(self, config: MCPServerConfig) -> None:
        """Add or update a server configuration and persist to disk."""
        self._servers[config.name] = config
        self._persist()

    def delete_server(self, name: str) -> None:
        """Remove a server configuration by name and persist to disk."""
        self._servers.pop(name, None)
        self._persist()
