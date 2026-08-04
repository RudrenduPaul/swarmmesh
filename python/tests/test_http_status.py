"""Tests for GET /v1/status."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_status_on_empty_mesh(client):
    response = await client.get("/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_count"] == 0
    assert body["namespaces"] == []
    assert body["context_entry_count"] == 0
    assert body["memory_entry_count"] == 0
    assert body["uptime_seconds"] >= 0


async def test_status_reflects_registered_state(client):
    await client.post("/v1/agents", json={"agent_id": "a1", "role": "worker"})
    await client.post("/v1/agents", json={"agent_id": "a2", "role": "worker"})
    await client.put("/v1/context/ns1/key1", json={"value": 1, "agent_id": "a1"})
    await client.put("/v1/context/ns1/key2", json={"value": 2, "agent_id": "a1"})
    await client.post("/v1/memory/ns2", json={"text": "a note", "agent_id": "a1"})

    response = await client.get("/v1/status")
    body = response.json()
    assert body["agent_count"] == 2
    assert set(body["namespaces"]) == {"ns1", "ns2"}
    assert body["context_entry_count"] == 2
    assert body["memory_entry_count"] == 1


async def test_status_excludes_deleted_context_namespace(client):
    await client.put("/v1/context/temp-ns/key", json={"value": 1, "agent_id": "a1"})
    await client.delete("/v1/context/temp-ns/key")

    response = await client.get("/v1/status")
    body = response.json()
    assert "temp-ns" not in body["namespaces"]
    assert body["context_entry_count"] == 0
