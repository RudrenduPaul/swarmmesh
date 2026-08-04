import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { WebSocket } from "ws";
import { SwarmMeshServer } from "../src/server.js";
import { InMemoryBackend } from "../src/store.js";
import type { ServerEvent } from "../src/types.js";

let server: SwarmMeshServer;
let baseUrl: string;

beforeEach(async () => {
  server = new SwarmMeshServer({ storage: new InMemoryBackend() });
  await server.listen(0, "127.0.0.1");
  const addr = server.address();
  if (!addr) throw new Error("server did not report an address");
  baseUrl = `http://127.0.0.1:${addr.port}`;
});

afterEach(async () => {
  await server.close();
});

async function json(path: string, init?: RequestInit): Promise<{ status: number; body: unknown }> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await response.text();
  return { status: response.status, body: text.length > 0 ? JSON.parse(text) : null };
}

describe("agent endpoints", () => {
  it("registers, lists, and deregisters an agent", async () => {
    const register = await json("/v1/agents", {
      method: "POST",
      body: JSON.stringify({ agent_id: "a1", role: "worker" }),
    });
    expect(register.status).toBe(201);
    expect((register.body as { agent_id: string }).agent_id).toBe("a1");

    const list = await json("/v1/agents");
    expect(list.status).toBe(200);
    expect((list.body as { agents: unknown[] }).agents).toHaveLength(1);

    const del = await fetch(`${baseUrl}/v1/agents/a1`, { method: "DELETE" });
    expect(del.status).toBe(204);

    const delAgain = await fetch(`${baseUrl}/v1/agents/a1`, { method: "DELETE" });
    expect(delAgain.status).toBe(404);
  });

  it("rejects a duplicate agent_id with 409", async () => {
    await json("/v1/agents", { method: "POST", body: JSON.stringify({ agent_id: "dup", role: "x" }) });
    const second = await json("/v1/agents", {
      method: "POST",
      body: JSON.stringify({ agent_id: "dup", role: "x" }),
    });
    expect(second.status).toBe(409);
  });

  it("rejects an invalid register body with 400", async () => {
    const result = await json("/v1/agents", { method: "POST", body: JSON.stringify({ role: "x" }) });
    expect(result.status).toBe(400);
  });
});

describe("context endpoints", () => {
  it("sets, gets, lists, and deletes a context value", async () => {
    const put = await json("/v1/context/ns1/greeting", {
      method: "PUT",
      body: JSON.stringify({ value: "hello", agent_id: "a1" }),
    });
    expect(put.status).toBe(200);
    expect((put.body as { value: string }).value).toBe("hello");

    const get = await json("/v1/context/ns1/greeting");
    expect(get.status).toBe(200);
    expect((get.body as { value: string }).value).toBe("hello");

    const list = await json("/v1/context/ns1");
    expect(list.status).toBe(200);
    expect((list.body as { entries: unknown[] }).entries).toHaveLength(1);

    const del = await fetch(`${baseUrl}/v1/context/ns1/greeting`, { method: "DELETE" });
    expect(del.status).toBe(204);

    const getAfterDelete = await json("/v1/context/ns1/greeting");
    expect(getAfterDelete.status).toBe(404);
  });

  it("returns 404 for a context key that never existed", async () => {
    const result = await json("/v1/context/ns1/missing");
    expect(result.status).toBe(404);
  });

  it("expires a context value once its TTL elapses", async () => {
    await json("/v1/context/ns1/temp", {
      method: "PUT",
      body: JSON.stringify({ value: "soon-gone", agent_id: "a1", ttl_seconds: 1 }),
    });
    const immediate = await json("/v1/context/ns1/temp");
    expect(immediate.status).toBe(200);

    await new Promise((resolve) => setTimeout(resolve, 1100));

    const afterExpiry = await json("/v1/context/ns1/temp");
    expect(afterExpiry.status).toBe(404);
    const list = await json("/v1/context/ns1");
    expect((list.body as { entries: unknown[] }).entries).toHaveLength(0);
  });

  it("rejects a publish body missing agent_id with 400", async () => {
    const result = await json("/v1/context/ns1/k1", {
      method: "PUT",
      body: JSON.stringify({ value: "x" }),
    });
    expect(result.status).toBe(400);
  });
});

describe("memory endpoints", () => {
  it("writes and queries memory entries with BM25 ranking", async () => {
    await json("/v1/memory/ns1", {
      method: "POST",
      body: JSON.stringify({ text: "the swarm agent published a shared context update", agent_id: "a1" }),
    });
    await json("/v1/memory/ns1", {
      method: "POST",
      body: JSON.stringify({ text: "context context context sharing across the swarm", agent_id: "a1" }),
    });
    await json("/v1/memory/ns1", {
      method: "POST",
      body: JSON.stringify({ text: "totally unrelated financial quarterly report", agent_id: "a1" }),
    });

    const query = await json("/v1/memory/ns1/query", {
      method: "POST",
      body: JSON.stringify({ query: "context", top_k: 10 }),
    });
    expect(query.status).toBe(200);
    const results = (query.body as { results: Array<{ entry: { text: string }; score: number }> }).results;
    expect(results.length).toBe(2);
    expect(results[0]?.entry.text).toContain("context context context");
    expect(results[0]!.score).toBeGreaterThan(results[1]!.score);
  });

  it("generates a UUID id when none is supplied", async () => {
    const result = await json("/v1/memory/ns1", {
      method: "POST",
      body: JSON.stringify({ text: "hello", agent_id: "a1" }),
    });
    expect(result.status).toBe(201);
    expect(typeof (result.body as { id: string }).id).toBe("string");
    expect((result.body as { id: string }).id.length).toBeGreaterThan(0);
  });
});

describe("status endpoint", () => {
  it("reports counts across agents, context, and memory", async () => {
    await json("/v1/agents", { method: "POST", body: JSON.stringify({ agent_id: "a1", role: "x" }) });
    await json("/v1/context/ns1/k1", {
      method: "PUT",
      body: JSON.stringify({ value: "v", agent_id: "a1" }),
    });
    await json("/v1/memory/ns2", { method: "POST", body: JSON.stringify({ text: "hi", agent_id: "a1" }) });

    const status = await json("/v1/status");
    expect(status.status).toBe(200);
    const body = status.body as {
      agent_count: number;
      context_entry_count: number;
      memory_entry_count: number;
      namespaces: string[];
    };
    expect(body.agent_count).toBe(1);
    expect(body.context_entry_count).toBe(1);
    expect(body.memory_entry_count).toBe(1);
    expect(body.namespaces.sort()).toEqual(["ns1", "ns2"]);
  });
});

describe("WebSocket /v1/events", () => {
  it("broadcasts context.updated to a subscribed client", async () => {
    const addr = server.address();
    if (!addr) throw new Error("no address");
    const ws = new WebSocket(`ws://127.0.0.1:${addr.port}/v1/events`);

    await new Promise<void>((resolve) => ws.once("open", () => resolve()));
    ws.send(JSON.stringify({ type: "subscribe", namespaces: ["ns1"] }));
    // Give the server a tick to process the subscribe frame before we publish.
    await new Promise((resolve) => setTimeout(resolve, 50));

    const eventPromise = new Promise<ServerEvent>((resolve) => {
      ws.once("message", (raw: Buffer) => resolve(JSON.parse(raw.toString("utf8")) as ServerEvent));
    });

    await json("/v1/context/ns1/k1", {
      method: "PUT",
      body: JSON.stringify({ value: "hello", agent_id: "a1" }),
    });

    const event = await eventPromise;
    expect(event.type).toBe("context.updated");
    if (event.type === "context.updated") {
      expect(event.namespace).toBe("ns1");
      expect(event.key).toBe("k1");
      expect(event.value).toBe("hello");
    }

    ws.close();
  });

  it("does not deliver events for namespaces a client did not subscribe to", async () => {
    const addr = server.address();
    if (!addr) throw new Error("no address");
    const ws = new WebSocket(`ws://127.0.0.1:${addr.port}/v1/events`);
    await new Promise<void>((resolve) => ws.once("open", () => resolve()));
    ws.send(JSON.stringify({ type: "subscribe", namespaces: ["only-this-ns"] }));
    await new Promise((resolve) => setTimeout(resolve, 50));

    let received = false;
    ws.on("message", () => {
      received = true;
    });

    await json("/v1/context/other-ns/k1", {
      method: "PUT",
      body: JSON.stringify({ value: "hello", agent_id: "a1" }),
    });
    await new Promise((resolve) => setTimeout(resolve, 100));

    expect(received).toBe(false);
    ws.close();
  });

  it("subscribing with an empty namespaces array receives events from every namespace", async () => {
    const addr = server.address();
    if (!addr) throw new Error("no address");
    const ws = new WebSocket(`ws://127.0.0.1:${addr.port}/v1/events`);
    await new Promise<void>((resolve) => ws.once("open", () => resolve()));
    ws.send(JSON.stringify({ type: "subscribe", namespaces: [] }));
    await new Promise((resolve) => setTimeout(resolve, 50));

    const eventPromise = new Promise<ServerEvent>((resolve) => {
      ws.once("message", (raw: Buffer) => resolve(JSON.parse(raw.toString("utf8")) as ServerEvent));
    });

    await json("/v1/agents", { method: "POST", body: JSON.stringify({ agent_id: "wildcard", role: "x" }) });

    const event = await eventPromise;
    expect(event.type).toBe("agent.registered");
    ws.close();
  });
});

describe("malformed JSON", () => {
  it("responds 400 for an unparsable request body", async () => {
    const response = await fetch(`${baseUrl}/v1/agents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{not valid json",
    });
    expect(response.status).toBe(400);
  });
});
