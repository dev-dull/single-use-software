"""API routes for MCP server configuration management."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..mcp_config import MCPConfigManager, MCPServerConfig

router = APIRouter(prefix="/api/mcp")

# Shared manager instance — config path is relative to the working directory.
_manager = MCPConfigManager()


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------


class MCPServerBody(BaseModel):
    """Pydantic model for creating/updating an MCP server config."""

    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    description: str = ""
    teams: list[str] = []


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("/servers")
async def list_servers(team: str | None = None) -> list[dict]:
    """List all configured MCP servers, optionally filtered by team."""
    return [asdict(s) for s in _manager.list_servers(team=team)]


@router.get("/servers/{name}")
async def get_server(name: str) -> dict:
    """Get a single MCP server config by name."""
    server = _manager.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    return asdict(server)


@router.post("/servers", status_code=201)
async def create_server(body: MCPServerBody) -> dict:
    """Add or update an MCP server configuration."""
    config = MCPServerConfig(
        name=body.name,
        command=body.command,
        args=body.args,
        env=body.env,
        description=body.description,
        teams=body.teams,
    )
    _manager.save_server(config)
    return asdict(config)


@router.delete("/servers/{name}", status_code=204)
async def delete_server(name: str) -> None:
    """Remove an MCP server configuration."""
    if _manager.get_server(name) is None:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    _manager.delete_server(name)
