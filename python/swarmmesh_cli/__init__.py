"""SwarmMesh: shared-context and memory coordination for swarms of parallel AI agents.

Implements the SwarmMesh v1 wire protocol documented in `docs/protocol.md`
at the repository root: HTTP endpoints for agent registration, shared
context, and shared memory; a WebSocket pub/sub channel for real-time
context change events; and an MCP server exposing the same operations as
tools.
"""

from __future__ import annotations

__version__ = "0.1.1"

__all__ = ["__version__"]
