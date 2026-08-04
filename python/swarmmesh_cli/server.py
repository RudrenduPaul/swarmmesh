"""FastAPI application implementing the SwarmMesh v1 wire protocol.

Every HTTP endpoint and the ``/v1/events`` WebSocket here implement
``docs/protocol.md`` exactly -- see that document for the binding wire
contract. This module does not add endpoints beyond what is documented
there.

SwarmMesh has no authentication in v1 and is designed to run on localhost
or inside a private network alongside the agents it coordinates -- the
same trust boundary as a local Redis instance or a SQLite file. All
external input is still validated through pydantic models before use.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from swarmmesh_cli.store import (
    Agent,
    BM25RankingBackend,
    ContextEntry,
    InMemoryBackend,
    MemoryEntry,
    RankingBackend,
    StorageBackend,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8420


# --------------------------------------------------------------------------
# Request/response schemas -- all external input is validated through these
# pydantic models before touching the storage backend.
# --------------------------------------------------------------------------


class RegisterAgentRequest(BaseModel):
    agent_id: str
    role: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentListResponse(BaseModel):
    agents: list[Agent]


class PublishContextRequest(BaseModel):
    value: Any
    ttl_seconds: int | None = None
    agent_id: str


class ContextListResponse(BaseModel):
    namespace: str
    entries: list[ContextEntry]


class WriteMemoryRequest(BaseModel):
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    agent_id: str
    id: str | None = None


class QueryMemoryRequest(BaseModel):
    query: str
    top_k: int = 10


class MemoryQueryResult(BaseModel):
    entry: MemoryEntry
    score: float


class MemoryQueryResponse(BaseModel):
    results: list[MemoryQueryResult]


class StatusResponse(BaseModel):
    agent_count: int
    namespaces: list[str]
    context_entry_count: int
    memory_entry_count: int
    uptime_seconds: float


# --------------------------------------------------------------------------
# WebSocket pub/sub broadcaster
# --------------------------------------------------------------------------


class EventBroadcaster:
    """Tracks `/v1/events` subscribers and fans out event frames to them.

    A subscriber's namespace filter of ``None`` means "subscribed to every
    namespace" (an empty or omitted `namespaces` list in the subscribe
    frame, per docs/protocol.md). Agent lifecycle events are not
    namespace-scoped and are always sent to every connected subscriber.
    """

    def __init__(self) -> None:
        self._subscribers: dict[WebSocket, set[str] | None] = {}

    def subscribe(self, websocket: WebSocket, namespaces: list[str]) -> None:
        self._subscribers[websocket] = set(namespaces) if namespaces else None

    def unsubscribe(self, websocket: WebSocket) -> None:
        self._subscribers.pop(websocket, None)

    async def broadcast(self, event: dict[str, Any], namespace: str | None = None) -> None:
        stale: list[WebSocket] = []
        for websocket, subscribed_namespaces in list(self._subscribers.items()):
            if (
                namespace is not None
                and subscribed_namespaces is not None
                and namespace not in subscribed_namespaces
            ):
                continue
            try:
                await websocket.send_json(event)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.unsubscribe(websocket)


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------


def create_app(
    storage_backend: StorageBackend | None = None,
    ranking_backend: RankingBackend | None = None,
) -> FastAPI:
    """Builds the SwarmMesh FastAPI app.

    ``storage_backend`` defaults to :class:`InMemoryBackend`;
    ``ranking_backend`` defaults to :class:`BM25RankingBackend`. Both are
    documented pluggable extension points (see `swarmmesh_cli.store`).
    """

    storage = storage_backend if storage_backend is not None else InMemoryBackend()
    ranking = ranking_backend if ranking_backend is not None else BM25RankingBackend()
    broadcaster = EventBroadcaster()
    state: dict[str, float] = {"start_time": time.monotonic()}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await storage.connect()
        state["start_time"] = time.monotonic()
        try:
            yield
        finally:
            await storage.close()

    app = FastAPI(title="SwarmMesh", version="1", lifespan=lifespan)
    app.state.storage = storage
    app.state.ranking = ranking
    app.state.broadcaster = broadcaster

    # ---- Agents ----

    @app.post("/v1/agents", status_code=201, response_model=Agent)
    async def register_agent(request: RegisterAgentRequest) -> Agent:
        agent = await storage.register_agent(request.agent_id, request.role, request.metadata)
        if agent is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"agent_id '{request.agent_id}' already registered; "
                    f"call PUT /v1/agents/{request.agent_id} to update metadata instead"
                ),
            )
        await broadcaster.broadcast({"type": "agent.registered", "agent_id": agent.agent_id})
        return agent

    @app.delete("/v1/agents/{agent_id}", status_code=204)
    async def deregister_agent(agent_id: str) -> Response:
        existed = await storage.deregister_agent(agent_id)
        if not existed:
            raise HTTPException(status_code=404, detail=f"agent_id '{agent_id}' not registered")
        await broadcaster.broadcast({"type": "agent.deregistered", "agent_id": agent_id})
        return Response(status_code=204)

    @app.get("/v1/agents", response_model=AgentListResponse)
    async def list_agents() -> AgentListResponse:
        agents = await storage.list_agents()
        return AgentListResponse(agents=agents)

    # ---- Context ----

    @app.put("/v1/context/{namespace}/{key}", response_model=ContextEntry)
    async def publish_context(
        namespace: str, key: str, request: PublishContextRequest
    ) -> ContextEntry:
        entry = await storage.put_context(
            namespace, key, request.value, request.ttl_seconds, request.agent_id
        )
        await broadcaster.broadcast(
            {
                "type": "context.updated",
                "namespace": entry.namespace,
                "key": entry.key,
                "value": entry.value,
                "updated_by": entry.updated_by,
                "updated_at": entry.updated_at,
            },
            namespace=entry.namespace,
        )
        return entry

    @app.get("/v1/context/{namespace}/{key}", response_model=ContextEntry)
    async def get_context(namespace: str, key: str) -> ContextEntry:
        entry = await storage.get_context(namespace, key)
        if entry is None:
            raise HTTPException(status_code=404, detail="context key not found or expired")
        return entry

    @app.get("/v1/context/{namespace}", response_model=ContextListResponse)
    async def list_context(namespace: str) -> ContextListResponse:
        entries = await storage.list_context(namespace)
        return ContextListResponse(namespace=namespace, entries=entries)

    @app.delete("/v1/context/{namespace}/{key}", status_code=204)
    async def delete_context(namespace: str, key: str) -> Response:
        await storage.delete_context(namespace, key)
        await broadcaster.broadcast(
            {"type": "context.deleted", "namespace": namespace, "key": key},
            namespace=namespace,
        )
        return Response(status_code=204)

    # ---- Memory ----

    @app.post("/v1/memory/{namespace}", status_code=201, response_model=MemoryEntry)
    async def write_memory(namespace: str, request: WriteMemoryRequest) -> MemoryEntry:
        entry = await storage.put_memory(
            namespace, request.text, request.metadata, request.agent_id, request.id
        )
        await broadcaster.broadcast(
            {
                "type": "memory.written",
                "namespace": entry.namespace,
                "id": entry.id,
                "text": entry.text,
                "created_by": entry.created_by,
            },
            namespace=entry.namespace,
        )
        return entry

    @app.post("/v1/memory/{namespace}/query", response_model=MemoryQueryResponse)
    async def query_memory(namespace: str, request: QueryMemoryRequest) -> MemoryQueryResponse:
        entries = await storage.list_memory(namespace)
        scored = ranking.score(request.query, entries)
        top = scored[: request.top_k]
        return MemoryQueryResponse(
            results=[MemoryQueryResult(entry=entry, score=score) for entry, score in top]
        )

    # ---- Status ----

    @app.get("/v1/status", response_model=StatusResponse)
    async def get_status() -> StatusResponse:
        agents = await storage.list_agents()
        namespaces = await storage.namespaces()
        context_count, memory_count = await storage.counts()
        return StatusResponse(
            agent_count=len(agents),
            namespaces=namespaces,
            context_entry_count=context_count,
            memory_entry_count=memory_count,
            uptime_seconds=time.monotonic() - state["start_time"],
        )

    # ---- WebSocket: /v1/events ----

    @app.websocket("/v1/events")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                frame = await websocket.receive_json()
                if isinstance(frame, dict) and frame.get("type") == "subscribe":
                    namespaces = frame.get("namespaces") or []
                    if isinstance(namespaces, list):
                        broadcaster.subscribe(websocket, [str(ns) for ns in namespaces])
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unsubscribe(websocket)

    return app
