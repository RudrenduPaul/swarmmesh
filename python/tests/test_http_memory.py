"""Tests for the memory endpoints: POST /v1/memory/{namespace} and
POST /v1/memory/{namespace}/query, including that BM25 ranking orders
results sensibly.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_write_memory_returns_201_and_stored_entry(client):
    response = await client.post(
        "/v1/memory/demo",
        json={"text": "found a race condition in the retry loop", "agent_id": "agent-1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["namespace"] == "demo"
    assert body["text"] == "found a race condition in the retry loop"
    assert body["created_by"] == "agent-1"
    assert body["id"]  # server-generated UUID


async def test_write_memory_with_explicit_id(client):
    response = await client.post(
        "/v1/memory/demo",
        json={"text": "explicit id entry", "agent_id": "agent-1", "id": "custom-id"},
    )
    assert response.status_code == 201
    assert response.json()["id"] == "custom-id"


async def test_write_memory_with_metadata(client):
    response = await client.post(
        "/v1/memory/demo",
        json={
            "text": "tagged entry",
            "agent_id": "agent-1",
            "metadata": {"severity": "high"},
        },
    )
    assert response.json()["metadata"] == {"severity": "high"}


async def test_query_memory_empty_namespace_returns_no_results(client):
    response = await client.post("/v1/memory/empty-ns/query", json={"query": "anything"})
    assert response.status_code == 200
    assert response.json() == {"results": []}


async def test_query_memory_bm25_orders_results_sensibly(client):
    # Three documents with clearly different relevance to the query "apples":
    # doc-a mentions "apples" three times, doc-b once, doc-c not at all.
    await client.post(
        "/v1/memory/fruit",
        json={"id": "doc-a", "text": "apples apples apples oranges", "agent_id": "a1"},
    )
    await client.post(
        "/v1/memory/fruit",
        json={"id": "doc-b", "text": "apples oranges oranges grapes", "agent_id": "a1"},
    )
    await client.post(
        "/v1/memory/fruit",
        json={"id": "doc-c", "text": "bananas melons watermelons", "agent_id": "a1"},
    )

    response = await client.post("/v1/memory/fruit/query", json={"query": "apples", "top_k": 10})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 3

    ids_in_order = [r["entry"]["id"] for r in results]
    # doc-a (3 occurrences) must outrank doc-b (1 occurrence), and doc-c
    # (0 occurrences, score 0) must rank last.
    assert ids_in_order[0] == "doc-a"
    assert ids_in_order[-1] == "doc-c"
    assert "doc-b" in ids_in_order

    scores_by_id = {r["entry"]["id"]: r["score"] for r in results}
    assert scores_by_id["doc-a"] > scores_by_id["doc-b"] > scores_by_id["doc-c"]
    assert scores_by_id["doc-c"] == 0.0

    # Results must be sorted descending by score.
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


async def test_query_memory_respects_top_k(client):
    for i in range(5):
        await client.post(
            "/v1/memory/many",
            json={"id": f"doc-{i}", "text": "shared keyword appears here", "agent_id": "a1"},
        )

    response = await client.post("/v1/memory/many/query", json={"query": "keyword", "top_k": 2})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2


async def test_query_memory_default_top_k_is_10(client):
    for i in range(15):
        await client.post(
            "/v1/memory/many",
            json={"id": f"doc-{i}", "text": "keyword present", "agent_id": "a1"},
        )

    response = await client.post("/v1/memory/many/query", json={"query": "keyword"})
    assert len(response.json()["results"]) == 10
