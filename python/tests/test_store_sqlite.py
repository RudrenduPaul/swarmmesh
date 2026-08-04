"""Tests for SQLiteBackend: writes persist across a close()/reconnect cycle
that simulates a `swarmmesh serve --persist <path>` restart.
"""

from __future__ import annotations

import pytest

from swarmmesh_cli.store import SQLiteBackend

pytestmark = pytest.mark.asyncio


async def test_sqlite_backend_survives_restart(tmp_path):
    db_path = str(tmp_path / "mesh.db")

    backend = SQLiteBackend(db_path)
    await backend.connect()
    await backend.register_agent("agent-1", "worker", {"team": "a"})
    await backend.put_context("demo", "phase", "planning", None, "agent-1")
    await backend.put_memory("demo", "an important finding", {}, "agent-1", "note-1")
    await backend.close()

    # Simulate a process restart: a brand-new SQLiteBackend instance
    # pointed at the same file.
    reopened = SQLiteBackend(db_path)
    await reopened.connect()

    agents = await reopened.list_agents()
    assert len(agents) == 1
    assert agents[0].agent_id == "agent-1"
    assert agents[0].metadata == {"team": "a"}

    context_entries = await reopened.list_context("demo")
    assert len(context_entries) == 1
    assert context_entries[0].key == "phase"
    assert context_entries[0].value == "planning"

    memory_entries = await reopened.list_memory("demo")
    assert len(memory_entries) == 1
    assert memory_entries[0].id == "note-1"
    assert memory_entries[0].text == "an important finding"

    await reopened.close()


async def test_sqlite_backend_agent_lifecycle(tmp_path):
    db_path = str(tmp_path / "agents.db")
    backend = SQLiteBackend(db_path)
    await backend.connect()

    agent = await backend.register_agent("a1", "worker", {})
    assert agent is not None

    duplicate = await backend.register_agent("a1", "worker", {})
    assert duplicate is None

    deleted = await backend.deregister_agent("a1")
    assert deleted is True

    deleted_again = await backend.deregister_agent("a1")
    assert deleted_again is False

    await backend.close()


async def test_sqlite_backend_context_ttl_expiry(tmp_path):
    import asyncio

    db_path = str(tmp_path / "ttl.db")
    backend = SQLiteBackend(db_path)
    await backend.connect()

    await backend.put_context("ns", "key", "value", 1, "agent-1")
    assert await backend.get_context("ns", "key") is not None

    await asyncio.sleep(1.2)

    assert await backend.get_context("ns", "key") is None
    assert await backend.list_context("ns") == []

    await backend.close()


async def test_sqlite_backend_delete_context(tmp_path):
    db_path = str(tmp_path / "delete.db")
    backend = SQLiteBackend(db_path)
    await backend.connect()

    await backend.put_context("ns", "key", "value", None, "agent-1")
    deleted = await backend.delete_context("ns", "key")
    assert deleted is True
    assert await backend.get_context("ns", "key") is None

    deleted_again = await backend.delete_context("ns", "key")
    assert deleted_again is False

    await backend.close()


async def test_sqlite_backend_counts_and_namespaces(tmp_path):
    db_path = str(tmp_path / "counts.db")
    backend = SQLiteBackend(db_path)
    await backend.connect()

    await backend.put_context("ns1", "k1", 1, None, "a1")
    await backend.put_context("ns1", "k2", 2, None, "a1")
    await backend.put_memory("ns2", "text", {}, "a1", None)

    namespaces = await backend.namespaces()
    assert set(namespaces) == {"ns1", "ns2"}

    context_count, memory_count = await backend.counts()
    assert context_count == 2
    assert memory_count == 1

    await backend.close()
