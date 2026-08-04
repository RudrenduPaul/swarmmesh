"""Tests for the /v1/events WebSocket pub/sub channel.

Uses Starlette's synchronous TestClient (not the async httpx client used
elsewhere) because it is the supported way to drive a WebSocket connection
alongside ordinary HTTP calls against the same app.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from swarmmesh_cli.server import create_app
from swarmmesh_cli.store import InMemoryBackend


def test_context_update_broadcasts_to_subscribed_client():
    app = create_app(storage_backend=InMemoryBackend())
    with TestClient(app) as client:
        with client.websocket_connect("/v1/events") as websocket:
            websocket.send_json({"type": "subscribe", "namespaces": ["demo"]})

            response = client.put(
                "/v1/context/demo/phase", json={"value": "planning", "agent_id": "agent-1"}
            )
            assert response.status_code == 200

            event = websocket.receive_json()
            assert event["type"] == "context.updated"
            assert event["namespace"] == "demo"
            assert event["key"] == "phase"
            assert event["value"] == "planning"
            assert event["updated_by"] == "agent-1"


def test_subscriber_does_not_receive_events_for_other_namespaces():
    app = create_app(storage_backend=InMemoryBackend())
    with TestClient(app) as client:
        with client.websocket_connect("/v1/events") as websocket:
            websocket.send_json({"type": "subscribe", "namespaces": ["watched"]})

            client.put("/v1/context/other-ns/key", json={"value": 1, "agent_id": "a1"})
            # The event for "watched" arrives, proving the earlier "other-ns"
            # write was never delivered to this subscriber.
            client.put("/v1/context/watched/key", json={"value": 2, "agent_id": "a1"})

            event = websocket.receive_json()
            assert event["namespace"] == "watched"


def test_empty_namespaces_list_subscribes_to_everything():
    app = create_app(storage_backend=InMemoryBackend())
    with TestClient(app) as client:
        with client.websocket_connect("/v1/events") as websocket:
            websocket.send_json({"type": "subscribe", "namespaces": []})

            client.put("/v1/context/any-ns/key", json={"value": 1, "agent_id": "a1"})

            event = websocket.receive_json()
            assert event["namespace"] == "any-ns"


def test_context_delete_broadcasts_context_deleted_event():
    app = create_app(storage_backend=InMemoryBackend())
    with TestClient(app) as client:
        client.put("/v1/context/demo/key", json={"value": 1, "agent_id": "a1"})
        with client.websocket_connect("/v1/events") as websocket:
            websocket.send_json({"type": "subscribe", "namespaces": []})
            client.delete("/v1/context/demo/key")

            event = websocket.receive_json()
            assert event["type"] == "context.deleted"
            assert event["namespace"] == "demo"
            assert event["key"] == "key"


def test_memory_write_broadcasts_memory_written_event():
    app = create_app(storage_backend=InMemoryBackend())
    with TestClient(app) as client:
        with client.websocket_connect("/v1/events") as websocket:
            websocket.send_json({"type": "subscribe", "namespaces": []})
            client.post("/v1/memory/demo", json={"text": "a finding", "agent_id": "a1"})

            event = websocket.receive_json()
            assert event["type"] == "memory.written"
            assert event["namespace"] == "demo"
            assert event["text"] == "a finding"
            assert event["created_by"] == "a1"


def test_agent_registered_event_broadcast_regardless_of_namespace_filter():
    app = create_app(storage_backend=InMemoryBackend())
    with TestClient(app) as client:
        with client.websocket_connect("/v1/events") as websocket:
            websocket.send_json({"type": "subscribe", "namespaces": ["only-this-ns"]})
            client.post("/v1/agents", json={"agent_id": "agent-x", "role": "worker"})

            event = websocket.receive_json()
            assert event["type"] == "agent.registered"
            assert event["agent_id"] == "agent-x"
