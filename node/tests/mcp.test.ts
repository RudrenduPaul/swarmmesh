import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SwarmMeshClient } from "../src/client.js";
import { callTool } from "../src/mcp.js";
import { SwarmMeshServer } from "../src/server.js";
import { InMemoryBackend } from "../src/store.js";

let server: SwarmMeshServer;
let client: SwarmMeshClient;

beforeEach(async () => {
  server = new SwarmMeshServer({ storage: new InMemoryBackend() });
  await server.listen(0, "127.0.0.1");
  const addr = server.address();
  if (!addr) throw new Error("no address");
  client = new SwarmMeshClient({ host: "127.0.0.1", port: addr.port });
});

afterEach(async () => {
  await server.close();
});

describe("callTool", () => {
  it("register_agent, list_agents, and deregister_agent round-trip", async () => {
    const registered = await callTool(client, "register_agent", { agent_id: "a1", role: "worker" });
    expect(registered.isError).toBe(false);
    expect(JSON.parse(registered.text)).toMatchObject({ agent_id: "a1", role: "worker" });

    const listed = await callTool(client, "list_agents", {});
    expect(JSON.parse(listed.text)).toMatchObject({ agents: [{ agent_id: "a1" }] });

    const deregistered = await callTool(client, "deregister_agent", { agent_id: "a1" });
    expect(deregistered.isError).toBe(false);
    expect(JSON.parse(deregistered.text)).toMatchObject({ deregistered: true });
  });

  it("publish_context, get_context, list_context, delete_context round-trip", async () => {
    const published = await callTool(client, "publish_context", {
      namespace: "ns1",
      key: "k1",
      value: { greeting: "hi" },
      agent_id: "a1",
    });
    expect(published.isError).toBe(false);

    const fetched = await callTool(client, "get_context", { namespace: "ns1", key: "k1" });
    expect(JSON.parse(fetched.text)).toMatchObject({ found: true, key: "k1" });

    const missing = await callTool(client, "get_context", { namespace: "ns1", key: "nope" });
    expect(JSON.parse(missing.text)).toEqual({ found: false });

    const listed = await callTool(client, "list_context", { namespace: "ns1" });
    expect(JSON.parse(listed.text)).toMatchObject({ entries: [{ key: "k1" }] });

    const deleted = await callTool(client, "delete_context", { namespace: "ns1", key: "k1" });
    expect(JSON.parse(deleted.text)).toEqual({ deleted: true });
  });

  it("write_memory and query_memory round-trip", async () => {
    await callTool(client, "write_memory", { namespace: "ns1", text: "hello swarm", agent_id: "a1" });
    const results = await callTool(client, "query_memory", { namespace: "ns1", query: "swarm" });
    const parsed = JSON.parse(results.text) as { results: unknown[] };
    expect(parsed.results).toHaveLength(1);
  });

  it("get_status returns a snapshot", async () => {
    const status = await callTool(client, "get_status", {});
    expect(status.isError).toBe(false);
    expect(JSON.parse(status.text)).toHaveProperty("agent_count");
  });

  it("returns isError for a missing required field", async () => {
    const result = await callTool(client, "register_agent", { role: "worker" });
    expect(result.isError).toBe(true);
  });

  it("returns isError for an unknown tool name", async () => {
    const result = await callTool(client, "not_a_real_tool", {});
    expect(result.isError).toBe(true);
    expect(result.text).toContain("unknown tool");
  });

  it("surfaces an HTTP error (e.g. 409 duplicate agent) as isError", async () => {
    await callTool(client, "register_agent", { agent_id: "dup", role: "x" });
    const second = await callTool(client, "register_agent", { agent_id: "dup", role: "x" });
    expect(second.isError).toBe(true);
  });
});
