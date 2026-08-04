import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildCli } from "../src/cli.js";
import { SwarmMeshServer } from "../src/server.js";
import { InMemoryBackend } from "../src/store.js";

let server: SwarmMeshServer;
let port: number;

beforeEach(async () => {
  server = new SwarmMeshServer({ storage: new InMemoryBackend() });
  await server.listen(0, "127.0.0.1");
  const addr = server.address();
  if (!addr) throw new Error("no address");
  port = addr.port;
});

afterEach(async () => {
  await server.close();
  process.exitCode = 0;
});

function captureStdout(): { logs: string[]; restore: () => void } {
  const logs: string[] = [];
  const spy = vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => {
    logs.push(args.map(String).join(" "));
  });
  return { logs, restore: () => spy.mockRestore() };
}

describe("swarmmesh CLI", () => {
  it("status --json prints valid, well-shaped JSON", async () => {
    const { logs, restore } = captureStdout();
    try {
      const program = buildCli();
      await program.parseAsync([
        "node",
        "swarmmesh",
        "status",
        "--json",
        "--host",
        "127.0.0.1",
        "--port",
        String(port),
      ]);
    } finally {
      restore();
    }
    expect(logs).toHaveLength(1);
    const parsed: unknown = JSON.parse(logs[0] ?? "");
    expect(parsed).toHaveProperty("agent_count");
    expect(parsed).toHaveProperty("namespaces");
    expect(process.exitCode).not.toBe(1);
  });

  it("agent register --json then agent list --json reflect the registration", async () => {
    const args = ["--host", "127.0.0.1", "--port", String(port), "--json"];
    const { logs, restore } = captureStdout();
    try {
      await buildCli().parseAsync([
        "node",
        "swarmmesh",
        "agent",
        "register",
        "cli-agent-1",
        "worker",
        ...args,
      ]);
      await buildCli().parseAsync(["node", "swarmmesh", "agent", "list", ...args]);
    } finally {
      restore();
    }
    expect(logs).toHaveLength(2);
    const registered = JSON.parse(logs[0] ?? "") as { agent_id: string };
    expect(registered.agent_id).toBe("cli-agent-1");
    const listed = JSON.parse(logs[1] ?? "") as { agents: Array<{ agent_id: string }> };
    expect(listed.agents.map((a) => a.agent_id)).toContain("cli-agent-1");
  });

  it("context set --json then context get --json round-trip a value", async () => {
    const args = ["--host", "127.0.0.1", "--port", String(port), "--json"];
    const { logs, restore } = captureStdout();
    try {
      await buildCli().parseAsync([
        "node",
        "swarmmesh",
        "context",
        "set",
        "ns1",
        "k1",
        '"hello"',
        "--agent-id",
        "cli",
        ...args,
      ]);
      await buildCli().parseAsync(["node", "swarmmesh", "context", "get", "ns1", "k1", ...args]);
    } finally {
      restore();
    }
    const set = JSON.parse(logs[0] ?? "") as { value: string };
    expect(set.value).toBe("hello");
    const got = JSON.parse(logs[1] ?? "") as { value: string };
    expect(got.value).toBe("hello");
  });

  it("sets a non-zero exit code on a failed request (e.g. connecting to a closed port)", async () => {
    const { restore } = captureStdout();
    const spyErr = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      await buildCli().parseAsync([
        "node",
        "swarmmesh",
        "status",
        "--json",
        "--host",
        "127.0.0.1",
        "--port",
        "1", // reserved/unlikely-to-be-listening port
      ]);
    } finally {
      restore();
      spyErr.mockRestore();
    }
    expect(process.exitCode).toBe(1);
  });

  it("memory write --json then memory query --json round-trip", async () => {
    const args = ["--host", "127.0.0.1", "--port", String(port), "--json"];
    const { logs, restore } = captureStdout();
    try {
      await buildCli().parseAsync([
        "node",
        "swarmmesh",
        "memory",
        "write",
        "ns1",
        "hello from the swarm",
        "--agent-id",
        "cli",
        ...args,
      ]);
      await buildCli().parseAsync([
        "node",
        "swarmmesh",
        "memory",
        "query",
        "ns1",
        "swarm",
        ...args,
      ]);
    } finally {
      restore();
    }
    const written = JSON.parse(logs[0] ?? "") as { id: string };
    expect(typeof written.id).toBe("string");
    const queried = JSON.parse(logs[1] ?? "") as { results: unknown[] };
    expect(queried.results).toHaveLength(1);
  });

  describe("human-readable output (no --json)", () => {
    const conn = ["--host", "127.0.0.1"];
    function portArgs(): string[] {
      return [...conn, "--port", String(port)];
    }

    it("prints status as labeled lines", async () => {
      const { logs, restore } = captureStdout();
      try {
        await buildCli().parseAsync(["node", "swarmmesh", "status", ...portArgs()]);
      } finally {
        restore();
      }
      expect(logs.some((l) => l.startsWith("agents:"))).toBe(true);
      expect(logs.some((l) => l.startsWith("namespaces:"))).toBe(true);
    });

    it("prints agent register/list/deregister as human text, including the empty-list case", async () => {
      const { logs, restore } = captureStdout();
      try {
        await buildCli().parseAsync(["node", "swarmmesh", "agent", "list", ...portArgs()]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "agent",
          "register",
          "human-agent",
          "worker",
          ...portArgs(),
        ]);
        await buildCli().parseAsync(["node", "swarmmesh", "agent", "list", ...portArgs()]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "agent",
          "deregister",
          "human-agent",
          ...portArgs(),
        ]);
      } finally {
        restore();
      }
      expect(logs[0]).toContain("no agents registered");
      expect(logs[1]).toContain("registered agent");
      expect(logs[2]).toContain("human-agent");
      expect(logs[3]).toContain("deregistered agent");
    });

    it("prints context set/get/list/delete as human text, including empty and 404 cases", async () => {
      const { logs, restore } = captureStdout();
      try {
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "context",
          "list",
          "human-ns",
          ...portArgs(),
        ]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "context",
          "get",
          "human-ns",
          "missing-key",
          ...portArgs(),
        ]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "context",
          "set",
          "human-ns",
          "k1",
          "plain-string-value",
          ...portArgs(),
        ]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "context",
          "get",
          "human-ns",
          "k1",
          ...portArgs(),
        ]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "context",
          "list",
          "human-ns",
          ...portArgs(),
        ]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "context",
          "delete",
          "human-ns",
          "k1",
          ...portArgs(),
        ]);
      } finally {
        restore();
      }
      expect(logs[0]).toContain("no live context entries");
      expect(logs[1]).toContain("no live value");
      expect(logs[2]).toContain("set human-ns/k1");
      expect(logs[3]).toBe('"plain-string-value"');
      expect(logs[4]).toContain("k1");
      expect(logs[5]).toContain("deleted human-ns/k1");
      expect(process.exitCode).toBe(1); // set by the 404 `context get` above
    });

    it("prints memory write/query as human text, including the no-results case", async () => {
      const { logs, restore } = captureStdout();
      try {
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "memory",
          "query",
          "human-ns",
          "nothing-will-match-this",
          ...portArgs(),
        ]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "memory",
          "write",
          "human-ns",
          "a note about the swarm",
          ...portArgs(),
        ]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "memory",
          "query",
          "human-ns",
          "swarm",
          ...portArgs(),
        ]);
      } finally {
        restore();
      }
      expect(logs[0]).toContain("no matching memory entries");
      expect(logs[1]).toContain("wrote memory");
      expect(logs[2]).toContain("a note about the swarm");
    });
  });

  describe("error handling", () => {
    const conn = ["--host", "127.0.0.1", "--port"];

    it("--json error output includes the HTTP status for a 409 conflict", async () => {
      const args = [...conn, String(port), "--json"];
      const { logs, restore } = captureStdout();
      try {
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "agent",
          "register",
          "dup-cli-agent",
          "worker",
          ...args,
        ]);
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "agent",
          "register",
          "dup-cli-agent",
          "worker",
          ...args,
        ]);
      } finally {
        restore();
      }
      const error = JSON.parse(logs[1] ?? "") as { error: string; status: number };
      expect(error.status).toBe(409);
      expect(process.exitCode).toBe(1);
    });

    it("rejects invalid --metadata JSON with a non-zero exit code", async () => {
      const { restore } = captureStdout();
      const spyErr = vi.spyOn(console, "error").mockImplementation(() => {});
      try {
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "agent",
          "register",
          "bad-metadata-agent",
          "worker",
          "--metadata",
          "{not json",
          "--host",
          "127.0.0.1",
          "--port",
          String(port),
        ]);
      } finally {
        restore();
        spyErr.mockRestore();
      }
      expect(process.exitCode).toBe(1);
    });

    it("rejects a non-integer --ttl with a non-zero exit code", async () => {
      const { restore } = captureStdout();
      const spyErr = vi.spyOn(console, "error").mockImplementation(() => {});
      try {
        await buildCli().parseAsync([
          "node",
          "swarmmesh",
          "context",
          "set",
          "ns1",
          "k1",
          "v1",
          "--ttl",
          "not-a-number",
          "--host",
          "127.0.0.1",
          "--port",
          String(port),
        ]);
      } finally {
        restore();
        spyErr.mockRestore();
      }
      expect(process.exitCode).toBe(1);
    });
  });
});
