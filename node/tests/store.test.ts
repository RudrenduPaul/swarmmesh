import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Bm25RankingBackend, InMemoryBackend, SqliteBackend } from "../src/store.js";
import type { Agent, ContextEntry, MemoryEntry } from "../src/types.js";

function makeAgent(id: string): Agent {
  return { agent_id: id, role: "worker", metadata: {}, registered_at: new Date().toISOString() };
}

function makeContext(
  namespace: string,
  key: string,
  value: string,
  ttlSeconds: number | null = null,
  updatedAt = new Date().toISOString(),
): ContextEntry {
  return { namespace, key, value, ttl_seconds: ttlSeconds, updated_by: "agent-1", updated_at: updatedAt };
}

function makeMemory(namespace: string, id: string, text: string): MemoryEntry {
  return { namespace, id, text, metadata: {}, created_by: "agent-1", created_at: new Date().toISOString() };
}

describe("InMemoryBackend", () => {
  let backend: InMemoryBackend;

  beforeEach(() => {
    backend = new InMemoryBackend();
  });

  it("registers an agent and rejects a duplicate agent_id", () => {
    expect(backend.registerAgent(makeAgent("a1"))).not.toBeNull();
    expect(backend.registerAgent(makeAgent("a1"))).toBeNull();
    expect(backend.listAgents()).toHaveLength(1);
  });

  it("deregisters an agent, reporting whether one was found", () => {
    backend.registerAgent(makeAgent("a1"));
    expect(backend.deregisterAgent("a1")).toBe(true);
    expect(backend.deregisterAgent("a1")).toBe(false);
    expect(backend.listAgents()).toHaveLength(0);
  });

  it("stores and retrieves a context entry", () => {
    backend.putContext(makeContext("ns", "k1", "v1"));
    expect(backend.getContext("ns", "k1")?.value).toBe("v1");
    expect(backend.getContext("ns", "missing")).toBeNull();
  });

  it("expires a context entry once its TTL has elapsed", () => {
    const past = new Date(Date.now() - 10_000).toISOString();
    backend.putContext(makeContext("ns", "k1", "v1", 1, past));
    expect(backend.getContext("ns", "k1")).toBeNull();
    expect(backend.listContext("ns")).toHaveLength(0);
  });

  it("does not expire a context entry with a null ttl", () => {
    const past = new Date(Date.now() - 1_000_000).toISOString();
    backend.putContext(makeContext("ns", "k1", "v1", null, past));
    expect(backend.getContext("ns", "k1")).not.toBeNull();
  });

  it("lists only live entries in a namespace", () => {
    backend.putContext(makeContext("ns", "k1", "v1"));
    backend.putContext(makeContext("other-ns", "k2", "v2"));
    const entries = backend.listContext("ns");
    expect(entries).toHaveLength(1);
    expect(entries[0]?.key).toBe("k1");
  });

  it("deletes a context entry and reports whether one existed", () => {
    backend.putContext(makeContext("ns", "k1", "v1"));
    expect(backend.deleteContext("ns", "k1")).toBe(true);
    expect(backend.deleteContext("ns", "k1")).toBe(false);
  });

  it("stores memory entries per namespace and counts across namespaces", () => {
    backend.putMemory(makeMemory("ns1", "m1", "hello world"));
    backend.putMemory(makeMemory("ns2", "m2", "goodbye world"));
    expect(backend.listMemory("ns1")).toHaveLength(1);
    expect(backend.countMemoryEntries()).toBe(2);
  });

  it("reports agent/context/memory counts and namespaces for status", () => {
    backend.registerAgent(makeAgent("a1"));
    backend.putContext(makeContext("ns1", "k1", "v1"));
    backend.putMemory(makeMemory("ns2", "m1", "text"));
    expect(backend.countAgents()).toBe(1);
    expect(backend.countContextEntries()).toBe(1);
    expect(backend.countMemoryEntries()).toBe(1);
    expect(backend.listNamespaces()).toEqual(["ns1", "ns2"]);
  });
});

describe("SqliteBackend", () => {
  let dir: string;
  let dbPath: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "swarmmesh-test-"));
    dbPath = join(dir, "mesh.db");
  });

  afterEach(() => {
    if (existsSync(dir)) rmSync(dir, { recursive: true, force: true });
  });

  it("persists agents, context, and memory across a simulated restart", () => {
    const first = new SqliteBackend(dbPath);
    first.registerAgent(makeAgent("a1"));
    first.putContext(makeContext("ns", "k1", "v1"));
    first.putMemory(makeMemory("ns", "m1", "hello world"));
    first.close();

    const reopened = new SqliteBackend(dbPath);
    expect(reopened.listAgents()).toHaveLength(1);
    expect(reopened.getContext("ns", "k1")?.value).toBe("v1");
    expect(reopened.listMemory("ns")).toHaveLength(1);
    reopened.close();
  });

  it("rejects a duplicate agent_id and expires TTL'd context on read", () => {
    const backend = new SqliteBackend(dbPath);
    expect(backend.registerAgent(makeAgent("a1"))).not.toBeNull();
    expect(backend.registerAgent(makeAgent("a1"))).toBeNull();

    const past = new Date(Date.now() - 10_000).toISOString();
    backend.putContext(makeContext("ns", "k1", "v1", 1, past));
    expect(backend.getContext("ns", "k1")).toBeNull();
    backend.close();
  });

  it("overwrites a context value with the same namespace/key (PUT semantics)", () => {
    const backend = new SqliteBackend(dbPath);
    backend.putContext(makeContext("ns", "k1", "v1"));
    backend.putContext(makeContext("ns", "k1", "v2"));
    expect(backend.getContext("ns", "k1")?.value).toBe("v2");
    expect(backend.listContext("ns")).toHaveLength(1);
    backend.close();
  });
});

describe("Bm25RankingBackend", () => {
  it("orders three documents sensibly for a keyword query", () => {
    const ranker = new Bm25RankingBackend();
    const entries = [
      makeMemory("ns", "doc-cats", "cats are wonderful independent animals that purr"),
      makeMemory("ns", "doc-cats-dogs", "cats and dogs are both popular pets, cats especially"),
      makeMemory("ns", "doc-unrelated", "the quarterly financial report is due next week"),
    ];

    const results = ranker.query(entries, "cats", 10);

    expect(results.map((r) => r.entry.id)).not.toContain("doc-unrelated");
    expect(results[0]?.entry.id).toBe("doc-cats-dogs");
    for (let i = 1; i < results.length; i++) {
      expect(results[i - 1]!.score).toBeGreaterThanOrEqual(results[i]!.score);
    }
  });

  it("returns no results for an empty corpus or empty query", () => {
    const ranker = new Bm25RankingBackend();
    expect(ranker.query([], "cats", 10)).toEqual([]);
    expect(ranker.query([makeMemory("ns", "m1", "cats")], "   ", 10)).toEqual([]);
  });

  it("respects top_k", () => {
    const ranker = new Bm25RankingBackend();
    const entries = [
      makeMemory("ns", "m1", "alpha beta"),
      makeMemory("ns", "m2", "alpha gamma"),
      makeMemory("ns", "m3", "alpha delta"),
    ];
    expect(ranker.query(entries, "alpha", 2)).toHaveLength(2);
  });
});
