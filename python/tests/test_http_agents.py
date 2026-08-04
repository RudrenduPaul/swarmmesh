"""Tests for the agent registration endpoints: POST/GET/DELETE /v1/agents."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_register_agent_returns_201_and_stored_agent(client):
    response = await client.post(
        "/v1/agents", json={"agent_id": "agent-1", "role": "researcher", "metadata": {"team": "a"}}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["agent_id"] == "agent-1"
    assert body["role"] == "researcher"
    assert body["metadata"] == {"team": "a"}
    assert "registered_at" in body


async def test_register_agent_without_metadata_defaults_to_empty_dict(client):
    response = await client.post("/v1/agents", json={"agent_id": "agent-2", "role": "worker"})
    assert response.status_code == 201
    assert response.json()["metadata"] == {}


async def test_register_duplicate_agent_returns_409(client):
    await client.post("/v1/agents", json={"agent_id": "dup", "role": "worker"})
    response = await client.post("/v1/agents", json={"agent_id": "dup", "role": "worker"})
    assert response.status_code == 409


async def test_list_agents_returns_all_registered(client):
    await client.post("/v1/agents", json={"agent_id": "a1", "role": "worker"})
    await client.post("/v1/agents", json={"agent_id": "a2", "role": "researcher"})

    response = await client.get("/v1/agents")
    assert response.status_code == 200
    body = response.json()
    agent_ids = {a["agent_id"] for a in body["agents"]}
    assert agent_ids == {"a1", "a2"}


async def test_list_agents_empty_mesh(client):
    response = await client.get("/v1/agents")
    assert response.status_code == 200
    assert response.json() == {"agents": []}


async def test_deregister_agent_returns_204(client):
    await client.post("/v1/agents", json={"agent_id": "gone", "role": "worker"})
    response = await client.delete("/v1/agents/gone")
    assert response.status_code == 204

    listing = await client.get("/v1/agents")
    assert listing.json() == {"agents": []}


async def test_deregister_unknown_agent_returns_404(client):
    response = await client.delete("/v1/agents/never-existed")
    assert response.status_code == 404


async def test_register_agent_rejects_missing_required_field(client):
    # No "role" field -- pydantic validation must reject this before it
    # ever reaches the storage backend.
    response = await client.post("/v1/agents", json={"agent_id": "bad"})
    assert response.status_code == 422
