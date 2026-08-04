"""Tests for the context endpoints: PUT/GET/DELETE /v1/context/{namespace}[/{key}],
including TTL expiry.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def test_publish_and_get_context(client):
    put_response = await client.put(
        "/v1/context/demo/phase", json={"value": "planning", "agent_id": "agent-1"}
    )
    assert put_response.status_code == 200
    body = put_response.json()
    assert body["namespace"] == "demo"
    assert body["key"] == "phase"
    assert body["value"] == "planning"
    assert body["updated_by"] == "agent-1"

    get_response = await client.get("/v1/context/demo/phase")
    assert get_response.status_code == 200
    assert get_response.json()["value"] == "planning"


async def test_publish_overwrites_existing_value(client):
    await client.put("/v1/context/demo/phase", json={"value": "planning", "agent_id": "agent-1"})
    await client.put("/v1/context/demo/phase", json={"value": "executing", "agent_id": "agent-2"})

    response = await client.get("/v1/context/demo/phase")
    body = response.json()
    assert body["value"] == "executing"
    assert body["updated_by"] == "agent-2"


async def test_get_unset_context_key_returns_404(client):
    response = await client.get("/v1/context/demo/never-set")
    assert response.status_code == 404


async def test_list_context_returns_only_entries_in_namespace(client):
    await client.put("/v1/context/ns-a/k1", json={"value": 1, "agent_id": "a1"})
    await client.put("/v1/context/ns-a/k2", json={"value": 2, "agent_id": "a1"})
    await client.put("/v1/context/ns-b/k1", json={"value": 3, "agent_id": "a1"})

    response = await client.get("/v1/context/ns-a")
    assert response.status_code == 200
    body = response.json()
    assert body["namespace"] == "ns-a"
    keys = {entry["key"] for entry in body["entries"]}
    assert keys == {"k1", "k2"}


async def test_list_context_empty_namespace(client):
    response = await client.get("/v1/context/nothing-here")
    assert response.status_code == 200
    assert response.json() == {"namespace": "nothing-here", "entries": []}


async def test_delete_context_returns_204_and_removes_entry(client):
    await client.put("/v1/context/demo/temp", json={"value": "x", "agent_id": "a1"})
    delete_response = await client.delete("/v1/context/demo/temp")
    assert delete_response.status_code == 204

    get_response = await client.get("/v1/context/demo/temp")
    assert get_response.status_code == 404


async def test_delete_context_missing_key_is_still_204(client):
    response = await client.delete("/v1/context/demo/never-existed")
    assert response.status_code == 204


async def test_context_ttl_expiry(client):
    await client.put(
        "/v1/context/demo/short-lived",
        json={"value": "temporary", "ttl_seconds": 1, "agent_id": "a1"},
    )

    immediate = await client.get("/v1/context/demo/short-lived")
    assert immediate.status_code == 200

    await asyncio.sleep(1.2)

    expired = await client.get("/v1/context/demo/short-lived")
    assert expired.status_code == 404

    listing = await client.get("/v1/context/demo")
    assert listing.json()["entries"] == []


async def test_context_without_ttl_never_expires(client):
    await client.put("/v1/context/demo/permanent", json={"value": "forever", "agent_id": "a1"})
    await asyncio.sleep(0.1)
    response = await client.get("/v1/context/demo/permanent")
    assert response.status_code == 200
    assert response.json()["value"] == "forever"
