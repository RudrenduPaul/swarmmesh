"""Typer CLI for SwarmMesh: `swarmmesh serve|status|agent|context|memory|mcp`."""

from __future__ import annotations

import asyncio
import json as json_module
from collections.abc import Coroutine
from typing import Any, NoReturn, TypeVar

import typer
import uvicorn

from swarmmesh_cli.client import SwarmMeshClient
from swarmmesh_cli.server import DEFAULT_HOST, DEFAULT_PORT, create_app
from swarmmesh_cli.store import InMemoryBackend, SQLiteBackend

T = TypeVar("T")

app = typer.Typer(
    name="swarmmesh",
    help="SwarmMesh: shared-context and memory coordination for swarms of parallel AI agents.",
    no_args_is_help=True,
)
agent_app = typer.Typer(help="Manage agent registrations on a running mesh.")
context_app = typer.Typer(help="Read and write shared context on a running mesh.")
memory_app = typer.Typer(help="Write and query shared memory on a running mesh.")
app.add_typer(agent_app, name="agent")
app.add_typer(context_app, name="context")
app.add_typer(memory_app, name="memory")

HostOption = typer.Option(DEFAULT_HOST, "--host", help="SwarmMesh server host.")
PortOption = typer.Option(DEFAULT_PORT, "--port", help="SwarmMesh server port.")
JsonOption = typer.Option(False, "--json", help="Output structured JSON, not human-readable text.")


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _print_json(data: Any) -> None:
    typer.echo(json_module.dumps(data, indent=2, default=str))


def _fail(message: str, as_json: bool) -> NoReturn:
    if as_json:
        typer.echo(json_module.dumps({"error": message}), err=True)
    else:
        typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _parse_metadata(raw: str | None, as_json: bool) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json_module.loads(raw)
    except json_module.JSONDecodeError as exc:
        _fail(f"invalid --metadata JSON: {exc}", as_json)
    if not isinstance(parsed, dict):
        _fail("--metadata must be a JSON object", as_json)
    return parsed


def _parse_value(raw: str) -> Any:
    try:
        return json_module.loads(raw)
    except json_module.JSONDecodeError:
        return raw


@app.command()
def serve(
    host: str = HostOption,
    port: int = PortOption,
    persist: str | None = typer.Option(
        None, "--persist", help="Path to a SQLite file for durable storage across restarts."
    ),
) -> None:
    """Start a SwarmMesh coordination server."""
    storage = SQLiteBackend(persist) if persist else InMemoryBackend()
    fastapi_app = create_app(storage_backend=storage)
    uvicorn.run(fastapi_app, host=host, port=port)


@app.command()
def status(
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """Show a mesh status snapshot."""

    async def _run() -> dict[str, Any]:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            return await client.get_status()

    try:
        result = _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json(result)
    else:
        typer.echo(f"agents:          {result['agent_count']}")
        typer.echo(f"namespaces:       {', '.join(result['namespaces']) or '(none)'}")
        typer.echo(f"context entries:  {result['context_entry_count']}")
        typer.echo(f"memory entries:   {result['memory_entry_count']}")
        typer.echo(f"uptime:           {result['uptime_seconds']:.1f}s")


@agent_app.command("register")
def agent_register(
    agent_id: str = typer.Argument(..., help="Unique agent identifier."),
    role: str = typer.Argument(..., help="Agent role label."),
    metadata: str | None = typer.Option(None, "--metadata", help="JSON object string."),
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """Register an agent with a running mesh."""
    meta = _parse_metadata(metadata, json)

    async def _run() -> dict[str, Any]:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            return await client.register_agent(agent_id, role, meta)

    try:
        result = _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json(result)
    else:
        typer.echo(f"registered {result['agent_id']} ({result['role']})")


@agent_app.command("list")
def agent_list(
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """List agents currently registered with a running mesh."""

    async def _run() -> dict[str, Any]:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            return await client.list_agents()

    try:
        result = _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json(result)
    else:
        agents = result.get("agents", [])
        if not agents:
            typer.echo("(no agents registered)")
        for entry in agents:
            typer.echo(f"{entry['agent_id']}\t{entry['role']}\t{entry['registered_at']}")


@agent_app.command("deregister")
def agent_deregister(
    agent_id: str = typer.Argument(...),
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """Deregister an agent from a running mesh."""

    async def _run() -> None:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            await client.deregister_agent(agent_id)

    try:
        _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json({"agent_id": agent_id, "deregistered": True})
    else:
        typer.echo(f"deregistered {agent_id}")


@context_app.command("set")
def context_set(
    namespace: str = typer.Argument(...),
    key: str = typer.Argument(...),
    value: str = typer.Argument(..., help="JSON value, or a plain string if not valid JSON."),
    agent_id: str = typer.Option("cli", "--agent-id", help="Agent publishing this value."),
    ttl: int | None = typer.Option(None, "--ttl", help="Time-to-live in seconds."),
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """Publish (create or overwrite) a context value."""
    parsed_value = _parse_value(value)

    async def _run() -> dict[str, Any]:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            return await client.publish_context(namespace, key, parsed_value, agent_id, ttl)

    try:
        result = _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json(result)
    else:
        typer.echo(f"set {namespace}/{key} = {result['value']!r}")


@context_app.command("get")
def context_get(
    namespace: str = typer.Argument(...),
    key: str = typer.Argument(...),
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """Read a single context value."""

    async def _run() -> dict[str, Any]:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            return await client.get_context(namespace, key)

    try:
        result = _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json(result)
    else:
        typer.echo(f"{result['value']!r}")


@context_app.command("list")
def context_list(
    namespace: str = typer.Argument(...),
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """List all live context entries in a namespace."""

    async def _run() -> dict[str, Any]:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            return await client.list_context(namespace)

    try:
        result = _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json(result)
    else:
        entries = result.get("entries", [])
        if not entries:
            typer.echo(f"(no context entries in '{namespace}')")
        for entry in entries:
            typer.echo(f"{entry['key']}\t{entry['value']!r}\t(by {entry['updated_by']})")


@context_app.command("delete")
def context_delete(
    namespace: str = typer.Argument(...),
    key: str = typer.Argument(...),
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """Delete a context value."""

    async def _run() -> None:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            await client.delete_context(namespace, key)

    try:
        _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json({"namespace": namespace, "key": key, "deleted": True})
    else:
        typer.echo(f"deleted {namespace}/{key}")


@memory_app.command("write")
def memory_write(
    namespace: str = typer.Argument(...),
    text: str = typer.Argument(...),
    agent_id: str = typer.Option("cli", "--agent-id", help="Agent writing this memory entry."),
    metadata: str | None = typer.Option(None, "--metadata", help="JSON object string."),
    id: str | None = typer.Option(
        None, "--id", help="Explicit entry id (server generates one if unset)."
    ),
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """Write a memory entry other agents in the swarm can find later."""
    meta = _parse_metadata(metadata, json)

    async def _run() -> dict[str, Any]:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            return await client.write_memory(namespace, text, agent_id, meta, id)

    try:
        result = _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json(result)
    else:
        typer.echo(f"wrote memory {result['id']} to '{namespace}'")


@memory_app.command("query")
def memory_query(
    namespace: str = typer.Argument(...),
    query: str = typer.Argument(...),
    top_k: int = typer.Option(10, "--top-k", help="Maximum number of results to return."),
    host: str = HostOption,
    port: int = PortOption,
    json: bool = JsonOption,
) -> None:
    """Query memory entries in a namespace using keyword/BM25 ranking."""

    async def _run() -> dict[str, Any]:
        async with SwarmMeshClient(f"http://{host}:{port}") as client:
            return await client.query_memory(namespace, query, top_k)

    try:
        result = _run_async(_run())
    except Exception as exc:
        _fail(str(exc), json)
        return

    if json:
        _print_json(result)
    else:
        results = result.get("results", [])
        if not results:
            typer.echo("(no matches)")
        for item in results:
            entry = item["entry"]
            typer.echo(f"{item['score']:.4f}\t{entry['id']}\t{entry['text']}")


@app.command()
def mcp(
    host: str = typer.Option(
        DEFAULT_HOST, "--host", help="Host of the running SwarmMesh server to proxy tool calls to."
    ),
    port: int = typer.Option(
        DEFAULT_PORT, "--port", help="Port of the running SwarmMesh server to proxy tool calls to."
    ),
) -> None:
    """Start an MCP server (stdio transport) exposing SwarmMesh tools to an MCP client."""
    from swarmmesh_cli.mcp_server import run_stdio

    run_stdio(base_url=f"http://{host}:{port}")


if __name__ == "__main__":
    app()
