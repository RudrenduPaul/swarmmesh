"""Storage and ranking backends for SwarmMesh.

This module defines the two pluggable extension points documented in
``docs/protocol.md``:

1. :class:`StorageBackend` -- persistence for agents, context, and memory.
   :class:`InMemoryBackend` is the zero-dependency default (process
   lifetime only); :class:`SQLiteBackend` persists to a SQLite file across
   restarts via ``swarmmesh serve --persist <path>``.
2. :class:`RankingBackend` -- scoring for ``POST /v1/memory/{namespace}/query``.
   :class:`BM25RankingBackend` is the default: real keyword/BM25-style
   term-frequency scoring, computed locally with zero extra dependencies
   and zero network calls. It is NOT semantic or embedding-based search.

Pluggable embedding backend (documented extension point, not implemented)
---------------------------------------------------------------------------
SwarmMesh does not ship a bundled embedding model and does not call any
external embedding API on a user's behalf. An operator who wants semantic
memory search can implement :class:`RankingBackend` with a ``score`` method
that embeds ``query`` and each entry's ``text`` (via whatever model/API
they choose to wire in) and ranks by vector similarity, then pass an
instance of it to :func:`swarmmesh_cli.server.create_app` as
``ranking_backend=...``. Until an operator does that, memory ranking stays
keyword/BM25 -- do not describe it as "AI-powered" or "semantic" search
anywhere in code, docs, or commit messages.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Data model (mirrors docs/protocol.md exactly)
# --------------------------------------------------------------------------


class Agent(BaseModel):
    agent_id: str
    role: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    registered_at: str


class ContextEntry(BaseModel):
    namespace: str
    key: str
    value: Any
    ttl_seconds: int | None = None
    updated_by: str
    updated_at: str


class MemoryEntry(BaseModel):
    namespace: str
    id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: str


# --------------------------------------------------------------------------
# Storage backend interface
# --------------------------------------------------------------------------


class StorageBackend(ABC):
    """Abstract persistence interface for agents, context, and memory.

    Implementations must provide put/get/delete/list semantics for context
    and put/query/list semantics for memory, plus agent registration. See
    :class:`InMemoryBackend` and :class:`SQLiteBackend` for the two
    implementations SwarmMesh ships.
    """

    async def connect(self) -> None:
        """Optional startup hook (e.g. opening a DB connection). No-op by default."""
        return None

    async def close(self) -> None:
        """Optional shutdown hook (e.g. closing a DB connection). No-op by default."""
        return None

    # Agents
    @abstractmethod
    async def register_agent(
        self, agent_id: str, role: str, metadata: dict[str, Any]
    ) -> Agent | None:
        """Register a new agent. Returns None if agent_id is already registered."""

    @abstractmethod
    async def get_agent(self, agent_id: str) -> Agent | None: ...

    @abstractmethod
    async def deregister_agent(self, agent_id: str) -> bool:
        """Returns True if the agent existed and was removed, False otherwise."""

    @abstractmethod
    async def list_agents(self) -> list[Agent]: ...

    # Context
    @abstractmethod
    async def put_context(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        agent_id: str,
    ) -> ContextEntry: ...

    @abstractmethod
    async def get_context(self, namespace: str, key: str) -> ContextEntry | None:
        """Returns None if unset or expired."""

    @abstractmethod
    async def list_context(self, namespace: str) -> list[ContextEntry]:
        """Returns only live (non-expired) entries."""

    @abstractmethod
    async def delete_context(self, namespace: str, key: str) -> bool: ...

    # Memory
    @abstractmethod
    async def put_memory(
        self,
        namespace: str,
        text: str,
        metadata: dict[str, Any],
        agent_id: str,
        entry_id: str | None,
    ) -> MemoryEntry: ...

    @abstractmethod
    async def list_memory(self, namespace: str) -> list[MemoryEntry]: ...

    # Status
    @abstractmethod
    async def namespaces(self) -> list[str]:
        """Distinct namespaces with at least one live context or memory entry."""

    @abstractmethod
    async def counts(self) -> tuple[int, int]:
        """Returns (context_entry_count, memory_entry_count) across all namespaces."""


class InMemoryBackend(StorageBackend):
    """Default storage backend: everything lives in process memory only."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        # namespace -> key -> (entry, expires_at epoch seconds or None)
        self._context: dict[str, dict[str, tuple[ContextEntry, float | None]]] = defaultdict(dict)
        # namespace -> id -> entry
        self._memory: dict[str, dict[str, MemoryEntry]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def register_agent(
        self, agent_id: str, role: str, metadata: dict[str, Any]
    ) -> Agent | None:
        async with self._lock:
            if agent_id in self._agents:
                return None
            agent = Agent(
                agent_id=agent_id,
                role=role,
                metadata=metadata,
                registered_at=_now_rfc3339(),
            )
            self._agents[agent_id] = agent
            return agent

    async def get_agent(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    async def deregister_agent(self, agent_id: str) -> bool:
        async with self._lock:
            return self._agents.pop(agent_id, None) is not None

    async def list_agents(self) -> list[Agent]:
        return list(self._agents.values())

    async def put_context(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        agent_id: str,
    ) -> ContextEntry:
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        entry = ContextEntry(
            namespace=namespace,
            key=key,
            value=value,
            ttl_seconds=ttl_seconds,
            updated_by=agent_id,
            updated_at=_now_rfc3339(),
        )
        async with self._lock:
            self._context[namespace][key] = (entry, expires_at)
        return entry

    async def get_context(self, namespace: str, key: str) -> ContextEntry | None:
        async with self._lock:
            bucket = self._context.get(namespace)
            if bucket is None or key not in bucket:
                return None
            entry, expires_at = bucket[key]
            if expires_at is not None and time.time() >= expires_at:
                del bucket[key]
                return None
            return entry

    async def list_context(self, namespace: str) -> list[ContextEntry]:
        async with self._lock:
            bucket = self._context.get(namespace)
            if not bucket:
                return []
            now = time.time()
            live: list[ContextEntry] = []
            expired_keys: list[str] = []
            for key, (entry, expires_at) in bucket.items():
                if expires_at is not None and now >= expires_at:
                    expired_keys.append(key)
                else:
                    live.append(entry)
            for key in expired_keys:
                del bucket[key]
            return sorted(live, key=lambda e: e.key)

    async def delete_context(self, namespace: str, key: str) -> bool:
        async with self._lock:
            bucket = self._context.get(namespace)
            if not bucket or key not in bucket:
                return False
            del bucket[key]
            return True

    async def put_memory(
        self,
        namespace: str,
        text: str,
        metadata: dict[str, Any],
        agent_id: str,
        entry_id: str | None,
    ) -> MemoryEntry:
        resolved_id = entry_id or str(uuid.uuid4())
        entry = MemoryEntry(
            namespace=namespace,
            id=resolved_id,
            text=text,
            metadata=metadata,
            created_by=agent_id,
            created_at=_now_rfc3339(),
        )
        async with self._lock:
            self._memory[namespace][resolved_id] = entry
        return entry

    async def list_memory(self, namespace: str) -> list[MemoryEntry]:
        return list(self._memory.get(namespace, {}).values())

    async def namespaces(self) -> list[str]:
        live_context_namespaces = {ns for ns in self._context if await self._has_live_context(ns)}
        memory_namespaces = {ns for ns, entries in self._memory.items() if entries}
        return sorted(live_context_namespaces | memory_namespaces)

    async def _has_live_context(self, namespace: str) -> bool:
        return len(await self.list_context(namespace)) > 0

    async def counts(self) -> tuple[int, int]:
        context_count = 0
        for namespace in list(self._context.keys()):
            context_count += len(await self.list_context(namespace))
        memory_count = sum(len(entries) for entries in self._memory.values())
        return context_count, memory_count


class SQLiteBackend(StorageBackend):
    """Storage backend that persists agents, context, and memory to SQLite.

    Selected via ``swarmmesh serve --persist <path>``. Data survives process
    restarts; the same file re-opened later resumes with the prior state.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                metadata TEXT NOT NULL,
                registered_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS context (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                ttl_seconds INTEGER,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at REAL,
                PRIMARY KEY (namespace, key)
            );
            CREATE TABLE IF NOT EXISTS memory (
                namespace TEXT NOT NULL,
                id TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (namespace, id)
            );
            """
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SQLiteBackend.connect() must be called before use")
        return self._conn

    async def register_agent(
        self, agent_id: str, role: str, metadata: dict[str, Any]
    ) -> Agent | None:
        conn = self._require_conn()
        async with self._lock:
            existing = await self.get_agent(agent_id)
            if existing is not None:
                return None
            registered_at = _now_rfc3339()
            await conn.execute(
                "INSERT INTO agents (agent_id, role, metadata, registered_at) VALUES (?, ?, ?, ?)",
                (agent_id, role, json.dumps(metadata), registered_at),
            )
            await conn.commit()
            return Agent(
                agent_id=agent_id,
                role=role,
                metadata=metadata,
                registered_at=registered_at,
            )

    async def get_agent(self, agent_id: str) -> Agent | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT agent_id, role, metadata, registered_at FROM agents WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return Agent(
            agent_id=row["agent_id"],
            role=row["role"],
            metadata=json.loads(row["metadata"]),
            registered_at=row["registered_at"],
        )

    async def deregister_agent(self, agent_id: str) -> bool:
        conn = self._require_conn()
        async with self._lock:
            cursor = await conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            await conn.commit()
            deleted = cursor.rowcount > 0
            await cursor.close()
            return deleted

    async def list_agents(self) -> list[Agent]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT agent_id, role, metadata, registered_at FROM agents ORDER BY registered_at"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            Agent(
                agent_id=row["agent_id"],
                role=row["role"],
                metadata=json.loads(row["metadata"]),
                registered_at=row["registered_at"],
            )
            for row in rows
        ]

    async def put_context(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        agent_id: str,
    ) -> ContextEntry:
        conn = self._require_conn()
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        updated_at = _now_rfc3339()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO context
                    (namespace, key, value, ttl_seconds, updated_by, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (namespace, key) DO UPDATE SET
                    value = excluded.value,
                    ttl_seconds = excluded.ttl_seconds,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (namespace, key, json.dumps(value), ttl_seconds, agent_id, updated_at, expires_at),
            )
            await conn.commit()
        return ContextEntry(
            namespace=namespace,
            key=key,
            value=value,
            ttl_seconds=ttl_seconds,
            updated_by=agent_id,
            updated_at=updated_at,
        )

    async def _purge_expired_context(self, namespace: str | None = None) -> None:
        conn = self._require_conn()
        now = time.time()
        if namespace is None:
            await conn.execute(
                "DELETE FROM context WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)
            )
        else:
            await conn.execute(
                "DELETE FROM context WHERE namespace = ? "
                "AND expires_at IS NOT NULL AND expires_at <= ?",
                (namespace, now),
            )
        await conn.commit()

    async def get_context(self, namespace: str, key: str) -> ContextEntry | None:
        conn = self._require_conn()
        async with self._lock:
            await self._purge_expired_context(namespace)
            cursor = await conn.execute(
                "SELECT namespace, key, value, ttl_seconds, updated_by, updated_at "
                "FROM context WHERE namespace = ? AND key = ?",
                (namespace, key),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        return ContextEntry(
            namespace=row["namespace"],
            key=row["key"],
            value=json.loads(row["value"]),
            ttl_seconds=row["ttl_seconds"],
            updated_by=row["updated_by"],
            updated_at=row["updated_at"],
        )

    async def list_context(self, namespace: str) -> list[ContextEntry]:
        conn = self._require_conn()
        async with self._lock:
            await self._purge_expired_context(namespace)
            cursor = await conn.execute(
                "SELECT namespace, key, value, ttl_seconds, updated_by, updated_at "
                "FROM context WHERE namespace = ? ORDER BY key",
                (namespace,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [
            ContextEntry(
                namespace=row["namespace"],
                key=row["key"],
                value=json.loads(row["value"]),
                ttl_seconds=row["ttl_seconds"],
                updated_by=row["updated_by"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def delete_context(self, namespace: str, key: str) -> bool:
        conn = self._require_conn()
        async with self._lock:
            cursor = await conn.execute(
                "DELETE FROM context WHERE namespace = ? AND key = ?", (namespace, key)
            )
            await conn.commit()
            deleted = cursor.rowcount > 0
            await cursor.close()
            return deleted

    async def put_memory(
        self,
        namespace: str,
        text: str,
        metadata: dict[str, Any],
        agent_id: str,
        entry_id: str | None,
    ) -> MemoryEntry:
        conn = self._require_conn()
        resolved_id = entry_id or str(uuid.uuid4())
        created_at = _now_rfc3339()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO memory (namespace, id, text, metadata, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (namespace, id) DO UPDATE SET
                    text = excluded.text,
                    metadata = excluded.metadata,
                    created_by = excluded.created_by,
                    created_at = excluded.created_at
                """,
                (namespace, resolved_id, text, json.dumps(metadata), agent_id, created_at),
            )
            await conn.commit()
        return MemoryEntry(
            namespace=namespace,
            id=resolved_id,
            text=text,
            metadata=metadata,
            created_by=agent_id,
            created_at=created_at,
        )

    async def list_memory(self, namespace: str) -> list[MemoryEntry]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT namespace, id, text, metadata, created_by, created_at "
            "FROM memory WHERE namespace = ? ORDER BY created_at",
            (namespace,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            MemoryEntry(
                namespace=row["namespace"],
                id=row["id"],
                text=row["text"],
                metadata=json.loads(row["metadata"]),
                created_by=row["created_by"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def namespaces(self) -> list[str]:
        conn = self._require_conn()
        async with self._lock:
            await self._purge_expired_context()
        cursor = await conn.execute("SELECT DISTINCT namespace FROM context")
        context_rows = await cursor.fetchall()
        await cursor.close()
        cursor = await conn.execute("SELECT DISTINCT namespace FROM memory")
        memory_rows = await cursor.fetchall()
        await cursor.close()
        context_namespaces = {row["namespace"] for row in context_rows}
        memory_namespaces = {row["namespace"] for row in memory_rows}
        return sorted(context_namespaces | memory_namespaces)

    async def counts(self) -> tuple[int, int]:
        conn = self._require_conn()
        async with self._lock:
            await self._purge_expired_context()
        cursor = await conn.execute("SELECT COUNT(*) AS n FROM context")
        row = await cursor.fetchone()
        await cursor.close()
        context_count = int(row["n"]) if row else 0
        cursor = await conn.execute("SELECT COUNT(*) AS n FROM memory")
        row = await cursor.fetchone()
        await cursor.close()
        memory_count = int(row["n"]) if row else 0
        return context_count, memory_count


# --------------------------------------------------------------------------
# Ranking backend interface
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class RankingBackend(ABC):
    """Scores memory entries against a query string for
    ``POST /v1/memory/{namespace}/query``.

    v1 ships :class:`BM25RankingBackend` -- real keyword/term-frequency
    scoring, not embedding or vector similarity search. To add semantic
    search, implement this interface with a ``score`` method that computes
    embedding similarity (using whatever model or API you choose to wire
    in yourself) and pass an instance to
    :func:`swarmmesh_cli.server.create_app` as ``ranking_backend=...``.
    SwarmMesh does not bundle an embedding model or call an embedding API
    on your behalf.
    """

    @abstractmethod
    def score(
        self, query: str, entries: Sequence[MemoryEntry]
    ) -> list[tuple[MemoryEntry, float]]:
        """Returns (entry, score) pairs sorted by score descending."""


class BM25RankingBackend(RankingBackend):
    """Okapi BM25 term-frequency ranking over `MemoryEntry.text`.

    This is real term-frequency/inverse-document-frequency scoring computed
    over the entries in the queried namespace -- not a placeholder and not
    semantic search.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def score(
        self, query: str, entries: Sequence[MemoryEntry]
    ) -> list[tuple[MemoryEntry, float]]:
        if not entries:
            return []

        query_terms = _tokenize(query)
        if not query_terms:
            return [(entry, 0.0) for entry in entries]

        docs_tokens = [_tokenize(entry.text) for entry in entries]
        doc_lengths = [len(tokens) for tokens in docs_tokens]
        n_docs = len(entries)
        avgdl = (sum(doc_lengths) / n_docs) if n_docs else 0.0

        document_frequency: dict[str, int] = defaultdict(int)
        for tokens in docs_tokens:
            for term in set(tokens):
                document_frequency[term] += 1

        results: list[tuple[MemoryEntry, float]] = []
        for entry, tokens, doc_length in zip(entries, docs_tokens, doc_lengths, strict=True):
            term_frequency: dict[str, int] = defaultdict(int)
            for token in tokens:
                term_frequency[token] += 1

            doc_score = 0.0
            for term in query_terms:
                freq = term_frequency.get(term, 0)
                if freq == 0:
                    continue
                n_t = document_frequency.get(term, 0)
                idf = math.log((n_docs - n_t + 0.5) / (n_t + 0.5) + 1)
                length_norm = 1 - self.b + self.b * (doc_length / avgdl if avgdl else 0.0)
                denominator = freq + self.k1 * length_norm
                doc_score += idf * (freq * (self.k1 + 1)) / denominator if denominator else 0.0

            results.append((entry, doc_score))

        results.sort(key=lambda pair: pair[1], reverse=True)
        return results
