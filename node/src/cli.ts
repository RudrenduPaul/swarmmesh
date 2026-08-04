#!/usr/bin/env node
/**
 * `swarmmesh` CLI. Every subcommand supports `--json` for structured output alongside
 * a human-readable default, and exits non-zero on error so scripting/CI callers can
 * detect failure without parsing text.
 */
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { Command } from "commander";
import {
  DEFAULT_HOST,
  DEFAULT_PORT,
  SwarmMeshClient,
  SwarmMeshHttpError,
} from "./client.js";
import { runMcpStdioServer } from "./mcp.js";
import { SwarmMeshServer } from "./server.js";
import { InMemoryBackend, SqliteBackend } from "./store.js";
import type { JsonValue } from "./types.js";

interface ConnectionOptions {
  host: string;
  port: string;
  json?: boolean;
}

function addConnectionOptions(cmd: Command): Command {
  return cmd
    .option("--host <host>", "mesh host to connect to", DEFAULT_HOST)
    .option("--port <port>", "mesh port to connect to", String(DEFAULT_PORT))
    .option("--json", "emit structured JSON output", false);
}

function clientFor(options: ConnectionOptions): SwarmMeshClient {
  return new SwarmMeshClient({ host: options.host, port: Number(options.port) });
}

function parsePortNumber(raw: string, flag: string): number {
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error(`${flag} must be an integer between 0 and 65535, got '${raw}'`);
  }
  return port;
}

function parseNonNegativeInt(raw: string, flag: string): number {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`${flag} must be a non-negative integer, got '${raw}'`);
  }
  return value;
}

function parseJsonArg(raw: string | undefined, flag: string): JsonValue | undefined {
  if (raw === undefined) return undefined;
  try {
    return JSON.parse(raw) as JsonValue;
  } catch {
    throw new Error(`${flag} must be valid JSON, got '${raw}'`);
  }
}

function printJson(data: unknown): void {
  console.log(JSON.stringify(data, null, 2));
}

/** Runs `action`, and on failure prints either a JSON or human-readable error and
 * sets a non-zero process exit code — the shared error path for every subcommand. */
async function run(json: boolean, action: () => Promise<void>): Promise<void> {
  try {
    await action();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const status = error instanceof SwarmMeshHttpError ? error.status : undefined;
    if (json) {
      printJson({ error: message, status: status ?? null });
    } else {
      console.error(`Error: ${message}`);
    }
    process.exitCode = 1;
  }
}

export function buildCli(): Command {
  const program = new Command();
  program
    .name("swarmmesh")
    .description(
      "Shared-context and memory coordination server for swarms of parallel AI agents.",
    )
    .version("0.1.1");

  program
    .command("serve")
    .description("start a SwarmMesh server")
    .option("--host <host>", "host to bind to", DEFAULT_HOST)
    .option("--port <port>", "port to bind to", String(DEFAULT_PORT))
    .option("--persist <path>", "path to a SQLite file for durable storage")
    .action(async (options: { host: string; port: string; persist?: string }) => {
      await run(false, async () => {
        const port = parsePortNumber(options.port, "--port");
        const storage = options.persist ? new SqliteBackend(options.persist) : new InMemoryBackend();
        const server = new SwarmMeshServer({ storage });
        await server.listen(port, options.host);
        console.log(
          `swarmmesh listening on http://${options.host}:${port}` +
            (options.persist ? ` (persisting to ${options.persist})` : " (in-memory)"),
        );
        const shutdown = (): void => {
          void server.close().then(() => process.exit(0));
        };
        process.on("SIGINT", shutdown);
        process.on("SIGTERM", shutdown);
      });
    });

  addConnectionOptions(
    program.command("status").description("show a mesh status snapshot"),
  ).action(async (options: ConnectionOptions) => {
    await run(options.json ?? false, async () => {
      const status = await clientFor(options).getStatus();
      if (options.json) {
        printJson(status);
      } else {
        console.log(`agents:          ${status.agent_count}`);
        console.log(`namespaces:      ${status.namespaces.join(", ") || "(none)"}`);
        console.log(`context entries: ${status.context_entry_count}`);
        console.log(`memory entries:  ${status.memory_entry_count}`);
        console.log(`uptime:          ${status.uptime_seconds.toFixed(1)}s`);
      }
    });
  });

  const agent = program.command("agent").description("manage mesh agents");

  addConnectionOptions(
    agent
      .command("register <agent_id> <role>")
      .description("register an agent with the mesh")
      .option("--metadata <json>", "agent metadata as a JSON object"),
  ).action(
    async (
      agentId: string,
      role: string,
      options: ConnectionOptions & { metadata?: string },
    ) => {
      await run(options.json ?? false, async () => {
        const metadata = parseJsonArg(options.metadata, "--metadata");
        const registered = await clientFor(options).registerAgent(
          agentId,
          role,
          metadata as Record<string, JsonValue> | undefined,
        );
        if (options.json) {
          printJson(registered);
        } else {
          console.log(`registered agent '${registered.agent_id}' (role: ${registered.role})`);
        }
      });
    },
  );

  addConnectionOptions(agent.command("list").description("list registered agents")).action(
    async (options: ConnectionOptions) => {
      await run(options.json ?? false, async () => {
        const agents = await clientFor(options).listAgents();
        if (options.json) {
          printJson({ agents });
        } else if (agents.length === 0) {
          console.log("(no agents registered)");
        } else {
          for (const a of agents) {
            console.log(`${a.agent_id}\t${a.role}\t${a.registered_at}`);
          }
        }
      });
    },
  );

  addConnectionOptions(
    agent.command("deregister <agent_id>").description("deregister an agent from the mesh"),
  ).action(async (agentId: string, options: ConnectionOptions) => {
    await run(options.json ?? false, async () => {
      await clientFor(options).deregisterAgent(agentId);
      if (options.json) {
        printJson({ agent_id: agentId, deregistered: true });
      } else {
        console.log(`deregistered agent '${agentId}'`);
      }
    });
  });

  const context = program.command("context").description("manage shared context values");

  addConnectionOptions(
    context
      .command("set <namespace> <key> <value>")
      .description("publish (create or overwrite) a context value; value is parsed as JSON, falling back to a raw string")
      .option("--ttl <seconds>", "expire this value after N seconds")
      .option("--agent-id <id>", "agent_id attributed to this write", "cli"),
  ).action(
    async (
      namespace: string,
      key: string,
      rawValue: string,
      options: ConnectionOptions & { ttl?: string; agentId: string },
    ) => {
      await run(options.json ?? false, async () => {
        let value: JsonValue;
        try {
          value = JSON.parse(rawValue) as JsonValue;
        } catch {
          value = rawValue;
        }
        const ttlSeconds =
          options.ttl !== undefined ? parseNonNegativeInt(options.ttl, "--ttl") : undefined;
        const entry = await clientFor(options).publishContext(
          namespace,
          key,
          value,
          options.agentId,
          ttlSeconds,
        );
        if (options.json) {
          printJson(entry);
        } else {
          console.log(`set ${namespace}/${key} = ${JSON.stringify(entry.value)}`);
        }
      });
    },
  );

  addConnectionOptions(
    context.command("get <namespace> <key>").description("read a single context value"),
  ).action(async (namespace: string, key: string, options: ConnectionOptions) => {
    await run(options.json ?? false, async () => {
      const entry = await clientFor(options).getContext(namespace, key);
      if (entry === null) {
        if (options.json) {
          printJson({ found: false });
        } else {
          console.log(`(no live value for ${namespace}/${key})`);
        }
        process.exitCode = 1;
        return;
      }
      if (options.json) {
        printJson(entry);
      } else {
        console.log(JSON.stringify(entry.value));
      }
    });
  });

  addConnectionOptions(
    context.command("list <namespace>").description("list live context entries in a namespace"),
  ).action(async (namespace: string, options: ConnectionOptions) => {
    await run(options.json ?? false, async () => {
      const entries = await clientFor(options).listContext(namespace);
      if (options.json) {
        printJson({ namespace, entries });
      } else if (entries.length === 0) {
        console.log(`(no live context entries in '${namespace}')`);
      } else {
        for (const entry of entries) {
          console.log(`${entry.key}\t${JSON.stringify(entry.value)}`);
        }
      }
    });
  });

  addConnectionOptions(
    context.command("delete <namespace> <key>").description("delete a context value"),
  ).action(async (namespace: string, key: string, options: ConnectionOptions) => {
    await run(options.json ?? false, async () => {
      await clientFor(options).deleteContext(namespace, key);
      if (options.json) {
        printJson({ namespace, key, deleted: true });
      } else {
        console.log(`deleted ${namespace}/${key}`);
      }
    });
  });

  const memory = program.command("memory").description("write and query shared memory");

  addConnectionOptions(
    memory
      .command("write <namespace> <text>")
      .description("write a memory entry into a namespace")
      .option("--agent-id <id>", "agent_id attributed to this write", "cli")
      .option("--metadata <json>", "metadata as a JSON object")
      .option("--id <id>", "explicit entry id (server generates a UUID if omitted)"),
  ).action(
    async (
      namespace: string,
      text: string,
      options: ConnectionOptions & { agentId: string; metadata?: string; id?: string },
    ) => {
      await run(options.json ?? false, async () => {
        const metadata = parseJsonArg(options.metadata, "--metadata");
        const entry = await clientFor(options).writeMemory(namespace, text, options.agentId, {
          metadata: metadata as Record<string, JsonValue> | undefined,
          id: options.id,
        });
        if (options.json) {
          printJson(entry);
        } else {
          console.log(`wrote memory ${entry.id} to '${namespace}'`);
        }
      });
    },
  );

  addConnectionOptions(
    memory
      .command("query <namespace> <query>")
      .description("query memory entries in a namespace (BM25 keyword ranking)")
      .option("--top-k <n>", "maximum number of results", "10"),
  ).action(
    async (
      namespace: string,
      query: string,
      options: ConnectionOptions & { topK: string },
    ) => {
      await run(options.json ?? false, async () => {
        const topK = parseNonNegativeInt(options.topK, "--top-k");
        const results = await clientFor(options).queryMemory(namespace, query, topK);
        if (options.json) {
          printJson({ results });
        } else if (results.length === 0) {
          console.log("(no matching memory entries)");
        } else {
          for (const result of results) {
            console.log(`${result.score.toFixed(4)}\t${result.entry.id}\t${result.entry.text}`);
          }
        }
      });
    },
  );

  addConnectionOptions(
    program.command("mcp").description("start the MCP server over stdio, proxying to a running mesh"),
  ).action(async (options: ConnectionOptions) => {
    await run(false, async () => {
      const client = clientFor(options);
      await runMcpStdioServer(client);
    });
  });

  return program;
}

async function main(): Promise<void> {
  const program = buildCli();
  await program.parseAsync(process.argv);
}

// Only auto-run when executed directly (not when imported by tests). Compared via
// pathToFileURL rather than a raw string concatenation, since import.meta.url
// percent-encodes characters like spaces in the path while process.argv[1] does not —
// a naive `file://${process.argv[1]}` comparison silently never matches on a path
// containing a space, and the CLI would parse zero arguments no matter what was passed.
//
// process.argv[1] is also realpath-resolved before the comparison: an npm-installed
// `bin` is a symlink (node_modules/.bin/swarmmesh -> ../swarmmesh-cli/dist/cli.js), and
// Node's ESM loader resolves import.meta.url through that symlink to the real target
// while process.argv[1] keeps the symlink path as invoked. Without resolving both sides
// the same way, this comparison never matches for any real npm/global install, and the
// CLI silently does nothing no matter what was passed — confirmed live, this shipped
// broken in 0.1.0.
function resolveMainModulePath(argvPath: string): string | undefined {
  try {
    return realpathSync(argvPath);
  } catch {
    return undefined;
  }
}

const mainModulePath = process.argv[1] !== undefined ? resolveMainModulePath(process.argv[1]) : undefined;
const isMainModule = mainModulePath !== undefined && import.meta.url === pathToFileURL(mainModulePath).href;
if (isMainModule) {
  main().catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
