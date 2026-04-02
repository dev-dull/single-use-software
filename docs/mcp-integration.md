# MCP Server Integrations

SUS supports connecting local data sources to build pods via
[Model Context Protocol (MCP)](https://modelcontextprotocol.io) servers.
This allows Claude inside a build pod to query databases, read files, and
interact with other tools through a standardised interface.

## How the MCP config file works

All MCP server definitions live in `mcp_servers.json` at the repository root.
The file has the following structure:

```json
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/repo/apps"],
      "env": {},
      "description": "Read-only access to the apps directory",
      "teams": []
    }
  ]
}
```

Each entry contains:

| Field         | Description                                                                 |
|---------------|-----------------------------------------------------------------------------|
| `name`        | Unique identifier for the server (used as the key in Claude's MCP config). |
| `command`     | Executable to launch the MCP server (`npx`, `uvx`, etc.).                  |
| `args`        | Arguments passed to the command.                                            |
| `env`         | Extra environment variables the server needs (connection strings, etc.).    |
| `description` | Human-readable summary shown in the management UI / API.                   |
| `teams`       | List of team slugs allowed to use this server. Empty means **all teams**.   |

## Adding a new data source

### Filesystem

Expose a directory inside the build pod:

```json
{
  "name": "project-files",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/repo"],
  "env": {},
  "description": "Full repository file access",
  "teams": []
}
```

### SQLite

Provide read access to a SQLite database:

```json
{
  "name": "sqlite-analytics",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "/data/analytics.db"],
  "env": {},
  "description": "Analytics database (read-only)",
  "teams": ["data"]
}
```

### Postgres

Connect to a Postgres instance using a connection string passed via `env`:

```json
{
  "name": "postgres-main",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-postgres"],
  "env": {
    "POSTGRES_CONNECTION_STRING": "postgresql://reader:password@postgres:5432/main"
  },
  "description": "Main Postgres database (read-only)",
  "teams": ["engineering"]
}
```

### Via the API

You can also manage servers through the REST API:

```bash
# List all servers
curl http://localhost:8000/api/mcp/servers

# List servers available to a specific team
curl http://localhost:8000/api/mcp/servers?team=engineering

# Add a new server
curl -X POST http://localhost:8000/api/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-sqlite",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "/data/my.db"],
    "env": {},
    "description": "My local SQLite DB",
    "teams": []
  }'

# Delete a server
curl -X DELETE http://localhost:8000/api/mcp/servers/my-sqlite
```

## Team scoping

The `teams` field controls which teams have access to a given MCP server:

- **Empty list (`[]`)** -- the server is available to all teams.
- **Non-empty list** -- only teams whose slug appears in the list can see or
  use the server.

When listing servers (either via `MCPConfigManager.list_servers(team=...)` or
the `GET /api/mcp/servers?team=...` endpoint), servers are filtered so that
only those accessible to the given team are returned.

## How MCP servers get provisioned into build pods

1. When a build pod is created, the landing page calls
   `MCPConfigManager.get_claude_mcp_config()` to produce the `mcpServers`
   JSON structure that Claude Code understands.
2. This config is JSON-encoded and injected into the pod as the
   `SUS_MCP_CONFIG` environment variable via `BuildPodManager.create_build_pod`.
3. Inside the build pod, the entrypoint reads `SUS_MCP_CONFIG` and writes it
   into Claude Code's settings so that MCP servers are available during the
   build session.
