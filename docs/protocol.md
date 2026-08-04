# SwarmMesh Protocol v1

SwarmMesh is a shared context and memory coordination layer for swarms of parallel AI
agents. This document is the wire protocol both official implementations (Python and
Node/TypeScript) implement identically, so a Python agent and a Node agent can join the
same mesh and exchange context regardless of which language spawned them.

A "mesh" is one running `swarmmesh serve` process. Agents are independent processes
(coding agents, research agents, subprocess workers — anything that can make an HTTP
request) that register with a mesh, then read and write namespaced shared context and
memory through it.

## Transport

- HTTP/1.1 for all request/response operations. JSON request and response bodies
  (`Content-Type: application/json`) unless stated otherwise.
- A single WebSocket endpoint (`/v1/events`) for real-time pub/sub of context changes.
- No authentication in v1 — SwarmMesh is designed to run on `localhost` or inside a
  private network alongside the agents it coordinates, the same trust boundary as a
  local Redis or SQLite file. Do not expose a SwarmMesh server directly to the public
  internet. (Documented explicitly in the README's security section — this is a scope
  boundary, not an oversight.)

## Data model

- **Agent**: `{ "agent_id": string, "role": string, "metadata": object, "registered_at": string (RFC 3339) }`
- **Context entry**: `{ "namespace": string, "key": string, "value": any JSON, "ttl_seconds": integer | null, "updated_by": string, "updated_at": string (RFC 3339) }`
- **Memory entry**: `{ "namespace": string, "id": string, "text": string, "metadata": object, "created_by": string, "created_at": string (RFC 3339) }`

Namespaces are arbitrary strings an operator chooses to scope a swarm run (e.g. a project
name or experiment ID). There is no cross-namespace query in v1.

## HTTP endpoints

### `POST /v1/agents`
Register an agent with the mesh.
Request: `{ "agent_id": string, "role": string, "metadata": object (optional) }`
Response `201`: the stored Agent object.
Response `409`: `agent_id` already registered (call `PUT /v1/agents/{agent_id}` to update
metadata instead).

### `DELETE /v1/agents/{agent_id}`
Deregister an agent. Response `204`. Idempotent — `404` is not an error condition callers
need to handle specially, but is returned for an unknown `agent_id`.

### `GET /v1/agents`
List currently registered agents. Response `200`: `{ "agents": [Agent, ...] }`.

### `PUT /v1/context/{namespace}/{key}`
Publish (create or overwrite) a context value.
Request: `{ "value": any JSON, "ttl_seconds": integer (optional), "agent_id": string }`
Response `200`: the stored Context entry.
Side effect: broadcasts a `context.updated` event (see WebSocket section) to every
subscriber watching this namespace.

### `GET /v1/context/{namespace}/{key}`
Read a single context value. Response `200`: the Context entry, or `404` if unset or
expired (TTL elapsed).

### `GET /v1/context/{namespace}`
List all live (non-expired) context entries in a namespace. Response `200`:
`{ "namespace": string, "entries": [Context entry, ...] }`.

### `DELETE /v1/context/{namespace}/{key}`
Delete a context value. Response `204`.

### `POST /v1/memory/{namespace}`
Write a memory entry (e.g. a finding, a summary, a note one agent wants other agents in
the swarm to be able to find later).
Request: `{ "text": string, "metadata": object (optional), "agent_id": string, "id": string (optional, server generates a UUID if omitted) }`
Response `201`: the stored Memory entry.

### `POST /v1/memory/{namespace}/query`
Query memory entries in a namespace.
Request: `{ "query": string, "top_k": integer (default 10) }`
Response `200`: `{ "results": [{ "entry": Memory entry, "score": number }, ...] }`,
ordered by `score` descending.

**v1 ranking is keyword/BM25-style term-frequency scoring over `text` — not embedding or
vector similarity search.** Both implementations MUST document this plainly and MUST NOT
claim semantic search unless a real embedding backend is configured (see "Pluggable
backends" below). Overstating ranking quality here is exactly the kind of unverified
capability claim this project's contributing guidelines forbid in the README.

### `GET /v1/status`
Mesh status snapshot. Response `200`:
```json
{
  "agent_count": integer,
  "namespaces": [string, ...],
  "context_entry_count": integer,
  "memory_entry_count": integer,
  "uptime_seconds": number
}
```
This is the endpoint both CLIs' `swarmmesh status --json` command calls.

## WebSocket: `/v1/events`

Client sends a subscribe frame on connect:
```json
{ "type": "subscribe", "namespaces": ["my-namespace"] }
```
(an empty or omitted `namespaces` array subscribes to every namespace).

Server pushes event frames as they occur:
```json
{ "type": "context.updated", "namespace": string, "key": string, "value": any, "updated_by": string, "updated_at": string }
{ "type": "context.deleted", "namespace": string, "key": string }
{ "type": "memory.written", "namespace": string, "id": string, "text": string, "created_by": string }
{ "type": "agent.registered", "agent_id": string }
{ "type": "agent.deregistered", "agent_id": string }
```

## Pluggable backends

Both implementations expose two extension points as documented interfaces, not just
internal implementation detail:

1. **Storage backend** — in-memory (default, process lifetime only) or SQLite
   (`--persist <path>`, survives restarts). A backend implements: put/get/delete/list for
   context, and put/query/list for memory.
2. **Ranking backend** for `POST /v1/memory/{namespace}/query` — keyword/BM25 (default,
   zero extra dependencies) or a user-supplied embedding function (documented hook, not
   bundled — SwarmMesh does not ship a bundled embedding model or make network calls to
   an embedding API on a user's behalf without explicit opt-in configuration).

## MCP surface

Both `swarmmesh mcp` subcommands (Python and Node) expose the same tool set to an MCP
client (Claude, or any other MCP-capable agent), each mapping 1:1 to an HTTP endpoint
above: `register_agent`, `deregister_agent`, `list_agents`, `publish_context`,
`get_context`, `list_context`, `delete_context`, `write_memory`, `query_memory`,
`get_status`. Tool input/output schemas mirror the HTTP request/response bodies above.

## Compatibility

Any client (not just the two official CLIs) that speaks this HTTP/WebSocket contract can
join a SwarmMesh mesh — this is a documented public protocol, not an implementation
detail of either CLI.
