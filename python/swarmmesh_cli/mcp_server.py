"""MCP server exposing the SwarmMesh tool set documented in docs/protocol.md.

Started via `swarmmesh mcp` (stdio transport). Each tool maps 1:1 to an HTTP
endpoint on a running `swarmmesh serve` process -- this module is a thin MCP
wrapper around `swarmmesh_cli.client.SwarmMeshClient`, not a second
implementation of the protocol.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from swarmmesh_cli.client import DEFAULT_BASE_URL, SwarmMeshClient


def build_mcp_server(base_url: str = DEFAULT_BASE_URL) -> MCPServer:
    """Builds the MCP server. Each tool proxies to `base_url` over HTTP."""
    server = MCPServer("swarmmesh")

    @server.tool()
    async def register_agent(
        agent_id: str, role: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Register an agent with the mesh."""
        async with SwarmMeshClient(base_url) as client:
            return await client.register_agent(agent_id, role, metadata)

    @server.tool()
    async def deregister_agent(agent_id: str) -> dict[str, Any]:
        """Deregister an agent from the mesh. Idempotent."""
        async with SwarmMeshClient(base_url) as client:
            await client.deregister_agent(agent_id)
        return {"agent_id": agent_id, "deregistered": True}

    @server.tool()
    async def list_agents() -> dict[str, Any]:
        """List agents currently registered with the mesh."""
        async with SwarmMeshClient(base_url) as client:
            return await client.list_agents()

    @server.tool()
    async def publish_context(
        namespace: str,
        key: str,
        value: Any,
        agent_id: str,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Publish (create or overwrite) a context value in a namespace."""
        async with SwarmMeshClient(base_url) as client:
            return await client.publish_context(namespace, key, value, agent_id, ttl_seconds)

    @server.tool()
    async def get_context(namespace: str, key: str) -> dict[str, Any]:
        """Read a single context value."""
        async with SwarmMeshClient(base_url) as client:
            return await client.get_context(namespace, key)

    @server.tool()
    async def list_context(namespace: str) -> dict[str, Any]:
        """List all live (non-expired) context entries in a namespace."""
        async with SwarmMeshClient(base_url) as client:
            return await client.list_context(namespace)

    @server.tool()
    async def delete_context(namespace: str, key: str) -> dict[str, Any]:
        """Delete a context value."""
        async with SwarmMeshClient(base_url) as client:
            await client.delete_context(namespace, key)
        return {"namespace": namespace, "key": key, "deleted": True}

    @server.tool()
    async def write_memory(
        namespace: str,
        text: str,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
        id: str | None = None,
    ) -> dict[str, Any]:
        """Write a memory entry other agents in the swarm can find later."""
        async with SwarmMeshClient(base_url) as client:
            return await client.write_memory(namespace, text, agent_id, metadata, id)

    @server.tool()
    async def query_memory(namespace: str, query: str, top_k: int = 10) -> dict[str, Any]:
        """Query memory entries in a namespace. Ranking is keyword/BM25-style
        term-frequency scoring, not semantic/embedding search."""
        async with SwarmMeshClient(base_url) as client:
            return await client.query_memory(namespace, query, top_k)

    @server.tool()
    async def get_status() -> dict[str, Any]:
        """Get a mesh status snapshot (agent count, namespaces, entry counts, uptime)."""
        async with SwarmMeshClient(base_url) as client:
            return await client.get_status()

    return server


def run_stdio(base_url: str = DEFAULT_BASE_URL) -> None:
    """Runs the MCP server over stdio -- entry point for `swarmmesh mcp`."""
    server = build_mcp_server(base_url)
    server.run(transport="stdio")
