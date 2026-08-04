"""CLI invocation tests via Typer's CliRunner, against a real live_server.

Covers `--json` output being valid, parseable JSON, human-readable default
output, and real non-zero exit codes on error.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from swarmmesh_cli.cli import app

runner = CliRunner()


def test_status_json_output_is_valid_json(live_server):
    host, port = live_server
    result = runner.invoke(app, ["status", "--host", host, "--port", str(port), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["agent_count"] == 0
    assert data["namespaces"] == []


def test_status_human_readable_output(live_server):
    host, port = live_server
    result = runner.invoke(app, ["status", "--host", host, "--port", str(port)])
    assert result.exit_code == 0
    assert "agents:" in result.stdout


def test_agent_register_json_output_is_valid_json(live_server):
    host, port = live_server
    result = runner.invoke(
        app,
        ["agent", "register", "agent-1", "worker", "--host", host, "--port", str(port), "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["agent_id"] == "agent-1"
    assert data["role"] == "worker"


def test_agent_register_with_metadata_json_string(live_server):
    host, port = live_server
    result = runner.invoke(
        app,
        [
            "agent",
            "register",
            "agent-meta",
            "worker",
            "--metadata",
            '{"team": "swarm-a"}',
            "--host",
            host,
            "--port",
            str(port),
            "--json",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["metadata"] == {"team": "swarm-a"}


def test_agent_register_duplicate_exits_nonzero(live_server):
    host, port = live_server
    runner.invoke(app, ["agent", "register", "dup", "worker", "--host", host, "--port", str(port)])
    result = runner.invoke(
        app, ["agent", "register", "dup", "worker", "--host", host, "--port", str(port), "--json"]
    )
    assert result.exit_code != 0


def test_agent_register_invalid_metadata_json_exits_nonzero(live_server):
    host, port = live_server
    result = runner.invoke(
        app,
        [
            "agent",
            "register",
            "agent-x",
            "worker",
            "--metadata",
            "{not valid json",
            "--host",
            host,
            "--port",
            str(port),
        ],
    )
    assert result.exit_code != 0


def test_agent_list_json_output_is_valid_json(live_server):
    host, port = live_server
    runner.invoke(
        app, ["agent", "register", "agent-a", "worker", "--host", host, "--port", str(port)]
    )
    result = runner.invoke(app, ["agent", "list", "--host", host, "--port", str(port), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert any(a["agent_id"] == "agent-a" for a in data["agents"])


def test_agent_deregister(live_server):
    host, port = live_server
    runner.invoke(
        app, ["agent", "register", "to-remove", "worker", "--host", host, "--port", str(port)]
    )
    result = runner.invoke(
        app, ["agent", "deregister", "to-remove", "--host", host, "--port", str(port), "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["deregistered"] is True


def test_agent_deregister_unknown_exits_nonzero(live_server):
    host, port = live_server
    result = runner.invoke(
        app, ["agent", "deregister", "never-existed", "--host", host, "--port", str(port)]
    )
    assert result.exit_code != 0


def test_context_set_and_get_json_roundtrip(live_server):
    host, port = live_server
    set_result = runner.invoke(
        app,
        [
            "context",
            "set",
            "demo",
            "phase",
            '"planning"',
            "--agent-id",
            "agent-1",
            "--host",
            host,
            "--port",
            str(port),
            "--json",
        ],
    )
    assert set_result.exit_code == 0
    set_data = json.loads(set_result.stdout)
    assert set_data["value"] == "planning"

    get_result = runner.invoke(
        app, ["context", "get", "demo", "phase", "--host", host, "--port", str(port), "--json"]
    )
    assert get_result.exit_code == 0
    get_data = json.loads(get_result.stdout)
    assert get_data["value"] == "planning"


def test_context_set_with_plain_string_value(live_server):
    host, port = live_server
    result = runner.invoke(
        app,
        [
            "context",
            "set",
            "demo",
            "label",
            "not-json-just-text",
            "--agent-id",
            "agent-1",
            "--host",
            host,
            "--port",
            str(port),
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["value"] == "not-json-just-text"


def test_context_list_json_output(live_server):
    host, port = live_server
    runner.invoke(
        app,
        [
            "context",
            "set",
            "listns",
            "k1",
            '"v1"',
            "--agent-id",
            "a1",
            "--host",
            host,
            "--port",
            str(port),
        ],
    )
    result = runner.invoke(
        app, ["context", "list", "listns", "--host", host, "--port", str(port), "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["namespace"] == "listns"
    assert len(data["entries"]) == 1


def test_context_delete_json_output(live_server):
    host, port = live_server
    runner.invoke(
        app,
        [
            "context",
            "set",
            "delns",
            "k1",
            '"v1"',
            "--agent-id",
            "a1",
            "--host",
            host,
            "--port",
            str(port),
        ],
    )
    result = runner.invoke(
        app, ["context", "delete", "delns", "k1", "--host", host, "--port", str(port), "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["deleted"] is True


def test_memory_write_and_query_json_roundtrip(live_server):
    host, port = live_server
    write_result = runner.invoke(
        app,
        [
            "memory",
            "write",
            "memns",
            "a race condition in the retry loop",
            "--agent-id",
            "agent-1",
            "--host",
            host,
            "--port",
            str(port),
            "--json",
        ],
    )
    assert write_result.exit_code == 0
    write_data = json.loads(write_result.stdout)
    assert write_data["text"] == "a race condition in the retry loop"

    query_result = runner.invoke(
        app,
        [
            "memory",
            "query",
            "memns",
            "race condition",
            "--host",
            host,
            "--port",
            str(port),
            "--json",
        ],
    )
    assert query_result.exit_code == 0
    query_data = json.loads(query_result.stdout)
    assert len(query_data["results"]) == 1
    assert query_data["results"][0]["entry"]["text"] == "a race condition in the retry loop"


def test_memory_query_human_readable_no_matches(live_server):
    host, port = live_server
    result = runner.invoke(
        app, ["memory", "query", "empty-ns", "nothing", "--host", host, "--port", str(port)]
    )
    assert result.exit_code == 0
    assert "no matches" in result.stdout


def test_status_unreachable_server_exits_nonzero():
    # Port 1 is reserved/unlikely to have a SwarmMesh server listening.
    result = runner.invoke(app, ["status", "--host", "127.0.0.1", "--port", "1", "--json"])
    assert result.exit_code != 0
