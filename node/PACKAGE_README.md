# swarmmesh-cli

A shared-context and memory coordination server for swarms of parallel AI agents.
`swarmmesh serve` starts an HTTP + WebSocket mesh that independent agent processes
register with, then read and write namespaced shared context and memory through.

This package is the Node/TypeScript implementation of the SwarmMesh protocol. A Python
implementation exists too — both speak the identical wire protocol, so agents written
in either language can join the same mesh.

## Install

```bash
npm install -g swarmmesh-cli
```

## Quickstart

Start a mesh:

```bash
swarmmesh serve --port 8420
```

From another process, register an agent and publish some context:

```bash
swarmmesh agent register agent-1 researcher
swarmmesh context set my-run status '"running"' --agent-id agent-1
swarmmesh context get my-run status
swarmmesh memory write my-run "found a race condition in the retry loop" --agent-id agent-1
swarmmesh memory query my-run "race condition"
swarmmesh status --json
```

Persist state across restarts with SQLite:

```bash
swarmmesh serve --persist ./mesh.db
```

Every subcommand supports `--json` for machine-readable output.

## MCP

Expose the same mesh to an MCP-capable agent (Claude, or any other MCP client):

```bash
swarmmesh mcp --port 8420
```

## Library usage

```ts
import { SwarmMeshClient } from "swarmmesh-cli";

const client = new SwarmMeshClient({ port: 8420 });
await client.registerAgent("agent-1", "researcher");
await client.publishContext("my-run", "status", "running", "agent-1");
```

## Ranking

Memory queries use keyword/BM25-style term-frequency scoring over entry text — not
embedding or vector similarity search. `RankingBackend` and `StorageBackend` are
documented, pluggable interfaces (see the project README) if you want to swap in your
own implementation.

## Security

SwarmMesh has no authentication in v1. It is designed to run on `localhost` or inside a
private network alongside the agents it coordinates — the same trust boundary as a
local Redis or SQLite file. Do not expose a SwarmMesh server to the public internet.
