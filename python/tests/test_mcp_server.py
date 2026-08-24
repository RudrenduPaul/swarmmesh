"""Tests for the MCP server: tool registry matches docs/protocol.md exactly,
and a couple of tools work end-to-end against a real running mesh.
"""

from __future__ import annotations

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from swarmmesh_cli.mcp_server import build_mcp_server

pytestmark = pytest.mark.asyncio

EXPECTED_TOOL_NAMES = {
    "register_agent",
    "deregister_agent",
    "list_agents",
    "publish_context",
    "get_context",
    "list_context",
    "delete_context",
    "write_memory",
    "query_memory",
    "get_status",
}


async def test_mcp_server_exposes_exactly_the_documented_tool_set():
    server = build_mcp_server()
    tools = await server.list_tools()
    tool_names = {tool.name for tool in tools}
    assert tool_names == EXPECTED_TOOL_NAMES


async def test_register_agent_tool_calls_through_to_live_server(live_server):
    host, port = live_server
    server = build_mcp_server(base_url=f"http://{host}:{port}")

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "register_agent", {"agent_id": "mcp-agent", "role": "worker"}
        )
        assert result.isError is False
        assert result.structuredContent["agent_id"] == "mcp-agent"
        assert result.structuredContent["role"] == "worker"


async def test_publish_and_get_context_tools_round_trip(live_server):
    host, port = live_server
    server = build_mcp_server(base_url=f"http://{host}:{port}")

    async with create_connected_server_and_client_session(server) as session:
        publish_result = await session.call_tool(
            "publish_context",
            {"namespace": "demo", "key": "phase", "value": "planning", "agent_id": "agent-1"},
        )
        assert publish_result.isError is False
        assert publish_result.structuredContent["value"] == "planning"

        get_result = await session.call_tool(
            "get_context", {"namespace": "demo", "key": "phase"}
        )
        assert get_result.isError is False
        assert get_result.structuredContent["value"] == "planning"


async def test_write_and_query_memory_tools_round_trip(live_server):
    host, port = live_server
    server = build_mcp_server(base_url=f"http://{host}:{port}")

    async with create_connected_server_and_client_session(server) as session:
        await session.call_tool(
            "write_memory",
            {"namespace": "notes", "text": "found a bug in retries", "agent_id": "agent-1"},
        )

        query_result = await session.call_tool(
            "query_memory", {"namespace": "notes", "query": "bug retries"}
        )
        assert query_result.isError is False
        assert len(query_result.structuredContent["results"]) == 1


async def test_get_status_tool_reflects_live_server_state(live_server):
    host, port = live_server
    server = build_mcp_server(base_url=f"http://{host}:{port}")

    async with create_connected_server_and_client_session(server) as session:
        await session.call_tool("register_agent", {"agent_id": "status-agent", "role": "worker"})
        status_result = await session.call_tool("get_status", {})
        assert status_result.isError is False
        assert status_result.structuredContent["agent_count"] >= 1
