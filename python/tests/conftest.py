"""Shared pytest fixtures for the SwarmMesh test suite."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient

from swarmmesh_cli.server import create_app
from swarmmesh_cli.store import InMemoryBackend


@pytest.fixture
def app():
    """A fresh SwarmMesh FastAPI app with a clean InMemoryBackend per test."""
    return create_app(storage_backend=InMemoryBackend())


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """An httpx.AsyncClient wired directly to the app via ASGI transport (no real socket)."""
    transport = ASGITransport(app=app)
    # Drive the app's lifespan context manually so storage.connect()/close()
    # run, since ASGITransport alone does not send lifespan events.
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def live_server() -> Iterator[tuple[str, int]]:
    """Runs a real SwarmMesh server on a background thread + real TCP port.

    Used by tests that need an actual HTTP/WebSocket server process (CLI
    invocation tests, MCP tool tests) rather than an in-process ASGI
    transport.
    """
    port = _free_port()
    fastapi_app = create_app(storage_backend=InMemoryBackend())
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5.0
    while not server.started and time.time() < deadline:
        time.sleep(0.05)

    yield "127.0.0.1", port

    server.should_exit = True
    thread.join(timeout=5.0)
