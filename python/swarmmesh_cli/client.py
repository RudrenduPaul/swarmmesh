"""Async HTTP client for the SwarmMesh v1 protocol.

Used internally by `swarmmesh_cli.cli`, and importable as a standalone
library by anyone scripting against a running mesh from Python:

    from swarmmesh_cli.client import SwarmMeshClient

    async def main() -> None:
        async with SwarmMeshClient("http://127.0.0.1:8420") as client:
            await client.register_agent("agent-1", "worker")
            await client.publish_context("demo", "phase", "planning", agent_id="agent-1")
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8420"


class SwarmMeshError(RuntimeError):
    """Raised when a SwarmMesh HTTP request returns a 4xx/5xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"SwarmMesh request failed ({status_code}): {detail}")


class SwarmMeshClient:
    """Thin async wrapper over every HTTP endpoint in docs/protocol.md."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def __aenter__(self) -> SwarmMeshClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            detail: str
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = str(body.get("detail", response.text))
                else:
                    detail = response.text
            except ValueError:
                detail = response.text
            raise SwarmMeshError(response.status_code, detail)

    # ---- Agents ----

    async def register_agent(
        self, agent_id: str, role: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self._client.post(
            "/v1/agents",
            json={"agent_id": agent_id, "role": role, "metadata": metadata or {}},
        )
        self._raise_for_status(response)
        return dict(response.json())

    async def deregister_agent(self, agent_id: str) -> None:
        response = await self._client.delete(f"/v1/agents/{agent_id}")
        self._raise_for_status(response)

    async def list_agents(self) -> dict[str, Any]:
        response = await self._client.get("/v1/agents")
        self._raise_for_status(response)
        return dict(response.json())

    # ---- Context ----

    async def publish_context(
        self,
        namespace: str,
        key: str,
        value: Any,
        agent_id: str,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"value": value, "agent_id": agent_id}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        response = await self._client.put(f"/v1/context/{namespace}/{key}", json=body)
        self._raise_for_status(response)
        return dict(response.json())

    async def get_context(self, namespace: str, key: str) -> dict[str, Any]:
        response = await self._client.get(f"/v1/context/{namespace}/{key}")
        self._raise_for_status(response)
        return dict(response.json())

    async def list_context(self, namespace: str) -> dict[str, Any]:
        response = await self._client.get(f"/v1/context/{namespace}")
        self._raise_for_status(response)
        return dict(response.json())

    async def delete_context(self, namespace: str, key: str) -> None:
        response = await self._client.delete(f"/v1/context/{namespace}/{key}")
        self._raise_for_status(response)

    # ---- Memory ----

    async def write_memory(
        self,
        namespace: str,
        text: str,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
        id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text, "agent_id": agent_id, "metadata": metadata or {}}
        if id is not None:
            body["id"] = id
        response = await self._client.post(f"/v1/memory/{namespace}", json=body)
        self._raise_for_status(response)
        return dict(response.json())

    async def query_memory(self, namespace: str, query: str, top_k: int = 10) -> dict[str, Any]:
        response = await self._client.post(
            f"/v1/memory/{namespace}/query", json={"query": query, "top_k": top_k}
        )
        self._raise_for_status(response)
        return dict(response.json())

    # ---- Status ----

    async def get_status(self) -> dict[str, Any]:
        response = await self._client.get("/v1/status")
        self._raise_for_status(response)
        return dict(response.json())
