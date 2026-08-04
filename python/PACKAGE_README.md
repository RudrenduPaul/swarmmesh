# swarmmesh-cli (Python)

Shared-context and memory coordination server + CLI for swarms of parallel AI agents.
Implements the [SwarmMesh v1 protocol](https://github.com/RudrenduPaul/swarmmesh/blob/main/docs/protocol.md)
over HTTP, WebSocket, and MCP.

This is the Python implementation. A behaviorally identical Node/TypeScript implementation
lives in the same repository — a Python agent and a Node agent can join the same mesh.

## Install

```bash
pip install swarmmesh-cli
```

## Quickstart

Start a mesh:

```bash
swarmmesh serve --host 127.0.0.1 --port 8420
```

Add `--persist ./mesh.db` to survive restarts (SQLite-backed storage instead of the
in-memory default).

Register an agent and check status from another terminal:

```bash
swarmmesh agent register agent-1 researcher
swarmmesh status --json
```

Share context and memory across agents:

```bash
swarmmesh context set my-run phase '"planning"' --agent-id agent-1
swarmmesh context get my-run phase

swarmmesh memory write my-run "found a race condition in the retry loop" --agent-id agent-1
swarmmesh memory query my-run "race condition"
```

Every subcommand supports `--json` for structured output an agent or script can parse.

## MCP

```bash
swarmmesh mcp --host 127.0.0.1 --port 8420
```

Starts an MCP server over stdio exposing `register_agent`, `deregister_agent`,
`list_agents`, `publish_context`, `get_context`, `list_context`, `delete_context`,
`write_memory`, `query_memory`, and `get_status` as tools, proxying to a running
`swarmmesh serve` process.

## Library usage

```python
from swarmmesh_cli.client import SwarmMeshClient

async def main() -> None:
    async with SwarmMeshClient("http://127.0.0.1:8420") as client:
        await client.register_agent("agent-1", "researcher")
        await client.publish_context("my-run", "phase", "planning", agent_id="agent-1")
```

## Ranking

Memory query ranking is keyword/BM25-style term-frequency scoring, computed locally with
zero extra dependencies and zero network calls. It is not semantic or embedding-based
search. `RankingBackend` in `swarmmesh_cli.store` is a documented extension point for
plugging in your own embedding-based scorer; SwarmMesh does not ship one.

## Security

No authentication in v1. SwarmMesh is designed to run on `localhost` or inside a private
network alongside the agents it coordinates — do not expose it directly to the public
internet.

## License

MIT
