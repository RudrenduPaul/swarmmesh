"""Unit tests for InMemoryBackend, exercised directly (not over HTTP)."""

from __future__ import annotations

import asyncio

import pytest

from swarmmesh_cli.store import InMemoryBackend

pytestmark = pytest.mark.asyncio


async def test_register_and_get_agent():
    backend = InMemoryBackend()
    agent = await backend.register_agent("a1", "worker", {"x": 1})
    assert agent is not None
    fetched = await backend.get_agent("a1")
    assert fetched == agent


async def test_get_unknown_agent_returns_none():
    backend = InMemoryBackend()
    assert await backend.get_agent("nope") is None


async def test_register_duplicate_agent_returns_none():
    backend = InMemoryBackend()
    await backend.register_agent("a1", "worker", {})
    assert await backend.register_agent("a1", "worker", {}) is None


async def test_context_ttl_lazy_expiry_removes_entry_from_bucket():
    backend = InMemoryBackend()
    await backend.put_context("ns", "k1", "v1", 1, "a1")
    await backend.put_context("ns", "k2", "v2", None, "a1")

    await asyncio.sleep(1.2)

    live = await backend.list_context("ns")
    assert [entry.key for entry in live] == ["k2"]


async def test_namespaces_omits_namespace_with_only_expired_context():
    backend = InMemoryBackend()
    await backend.put_context("temp-ns", "k1", "v1", 1, "a1")
    await asyncio.sleep(1.2)

    namespaces = await backend.namespaces()
    assert "temp-ns" not in namespaces


async def test_namespaces_includes_memory_only_namespace():
    backend = InMemoryBackend()
    await backend.put_memory("mem-ns", "text", {}, "a1", None)
    namespaces = await backend.namespaces()
    assert "mem-ns" in namespaces


async def test_put_memory_generates_uuid_when_id_omitted():
    backend = InMemoryBackend()
    entry = await backend.put_memory("ns", "text", {}, "a1", None)
    assert entry.id
    assert len(entry.id) == 36  # uuid4 string length


async def test_put_memory_overwrites_existing_id():
    backend = InMemoryBackend()
    await backend.put_memory("ns", "first", {}, "a1", "fixed-id")
    await backend.put_memory("ns", "second", {}, "a1", "fixed-id")

    entries = await backend.list_memory("ns")
    assert len(entries) == 1
    assert entries[0].text == "second"


async def test_delete_context_returns_false_for_missing_key():
    backend = InMemoryBackend()
    assert await backend.delete_context("ns", "missing") is False


async def test_counts_across_multiple_namespaces():
    backend = InMemoryBackend()
    await backend.put_context("ns1", "k1", 1, None, "a1")
    await backend.put_context("ns2", "k1", 1, None, "a1")
    await backend.put_memory("ns1", "text", {}, "a1", None)

    context_count, memory_count = await backend.counts()
    assert context_count == 2
    assert memory_count == 1
