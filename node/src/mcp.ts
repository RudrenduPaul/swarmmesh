/**
 * MCP surface for SwarmMesh. Exposes the exact tool set documented in
 * docs/protocol.md's "MCP surface" section, each mapping 1:1 to an HTTP endpoint, with
 * input/output schemas mirroring the HTTP request/response bodies. `swarmmesh mcp`
 * starts this server over stdio.
 *
 * Tool business logic lives in `callTool`, kept separate from SDK wiring, so it can be
 * unit tested without spinning up a stdio transport.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema, type Tool } from "@modelcontextprotocol/sdk/types.js";
import { SwarmMeshClient, SwarmMeshHttpError } from "./client.js";
import type { JsonValue } from "./types.js";

const TOOLS: Tool[] = [
  {
    name: "register_agent",
    description: "Register an agent with the mesh.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string" },
        role: { type: "string" },
        metadata: { type: "object" },
      },
      required: ["agent_id", "role"],
    },
  },
  {
    name: "deregister_agent",
    description: "Deregister an agent from the mesh. Idempotent.",
    inputSchema: {
      type: "object",
      properties: { agent_id: { type: "string" } },
      required: ["agent_id"],
    },
  },
  {
    name: "list_agents",
    description: "List currently registered agents.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "publish_context",
    description: "Publish (create or overwrite) a context value in a namespace.",
    inputSchema: {
      type: "object",
      properties: {
        namespace: { type: "string" },
        key: { type: "string" },
        value: {},
        ttl_seconds: { type: ["integer", "null"] },
        agent_id: { type: "string" },
      },
      required: ["namespace", "key", "value", "agent_id"],
    },
  },
  {
    name: "get_context",
    description: "Read a single context value. Returns found: false if unset or expired.",
    inputSchema: {
      type: "object",
      properties: {
        namespace: { type: "string" },
        key: { type: "string" },
      },
      required: ["namespace", "key"],
    },
  },
  {
    name: "list_context",
    description: "List all live (non-expired) context entries in a namespace.",
    inputSchema: {
      type: "object",
      properties: { namespace: { type: "string" } },
      required: ["namespace"],
    },
  },
  {
    name: "delete_context",
    description: "Delete a context value.",
    inputSchema: {
      type: "object",
      properties: {
        namespace: { type: "string" },
        key: { type: "string" },
      },
      required: ["namespace", "key"],
    },
  },
  {
    name: "write_memory",
    description: "Write a memory entry (a finding, summary, or note) into a namespace.",
    inputSchema: {
      type: "object",
      properties: {
        namespace: { type: "string" },
        text: { type: "string" },
        agent_id: { type: "string" },
        metadata: { type: "object" },
        id: { type: "string" },
      },
      required: ["namespace", "text", "agent_id"],
    },
  },
  {
    name: "query_memory",
    description:
      "Query memory entries in a namespace using keyword/BM25-style term-frequency ranking " +
      "(not semantic/embedding search).",
    inputSchema: {
      type: "object",
      properties: {
        namespace: { type: "string" },
        query: { type: "string" },
        top_k: { type: "integer" },
      },
      required: ["namespace", "query"],
    },
  },
  {
    name: "get_status",
    description: "Get a mesh status snapshot.",
    inputSchema: { type: "object", properties: {} },
  },
];

export interface ToolCallResult {
  isError: boolean;
  text: string;
}

function asRecord(args: unknown): Record<string, unknown> {
  if (typeof args !== "object" || args === null) return {};
  return args as Record<string, unknown>;
}

function requireString(record: Record<string, unknown>, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${field} must be a non-empty string`);
  }
  return value;
}

/** Executes one MCP tool call against a running mesh via `client`. Kept independent of
 * the MCP SDK's transport/session plumbing so it is directly unit testable. */
export async function callTool(
  client: SwarmMeshClient,
  name: string,
  rawArgs: unknown,
): Promise<ToolCallResult> {
  const args = asRecord(rawArgs);
  try {
    switch (name) {
      case "register_agent": {
        const agent = await client.registerAgent(
          requireString(args, "agent_id"),
          requireString(args, "role"),
          args.metadata as Record<string, JsonValue> | undefined,
        );
        return { isError: false, text: JSON.stringify(agent) };
      }
      case "deregister_agent": {
        await client.deregisterAgent(requireString(args, "agent_id"));
        return { isError: false, text: JSON.stringify({ agent_id: args.agent_id, deregistered: true }) };
      }
      case "list_agents": {
        const agents = await client.listAgents();
        return { isError: false, text: JSON.stringify({ agents }) };
      }
      case "publish_context": {
        if (!("value" in args)) throw new Error("value is required");
        const entry = await client.publishContext(
          requireString(args, "namespace"),
          requireString(args, "key"),
          args.value as JsonValue,
          requireString(args, "agent_id"),
          args.ttl_seconds as number | null | undefined,
        );
        return { isError: false, text: JSON.stringify(entry) };
      }
      case "get_context": {
        const entry = await client.getContext(
          requireString(args, "namespace"),
          requireString(args, "key"),
        );
        if (entry === null) {
          return { isError: false, text: JSON.stringify({ found: false }) };
        }
        return { isError: false, text: JSON.stringify({ found: true, ...entry }) };
      }
      case "list_context": {
        const entries = await client.listContext(requireString(args, "namespace"));
        return { isError: false, text: JSON.stringify({ namespace: args.namespace, entries }) };
      }
      case "delete_context": {
        await client.deleteContext(requireString(args, "namespace"), requireString(args, "key"));
        return { isError: false, text: JSON.stringify({ deleted: true }) };
      }
      case "write_memory": {
        const entry = await client.writeMemory(
          requireString(args, "namespace"),
          requireString(args, "text"),
          requireString(args, "agent_id"),
          {
            metadata: args.metadata as Record<string, JsonValue> | undefined,
            id: args.id as string | undefined,
          },
        );
        return { isError: false, text: JSON.stringify(entry) };
      }
      case "query_memory": {
        const results = await client.queryMemory(
          requireString(args, "namespace"),
          requireString(args, "query"),
          args.top_k as number | undefined,
        );
        return { isError: false, text: JSON.stringify({ results }) };
      }
      case "get_status": {
        const status = await client.getStatus();
        return { isError: false, text: JSON.stringify(status) };
      }
      default:
        return { isError: true, text: `unknown tool: ${name}` };
    }
  } catch (error) {
    const message =
      error instanceof SwarmMeshHttpError
        ? error.message
        : error instanceof Error
          ? error.message
          : String(error);
    return { isError: true, text: message };
  }
}

export function createMcpServer(client: SwarmMeshClient): Server {
  const server = new Server(
    { name: "swarmmesh", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, () => ({ tools: TOOLS }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const result = await callTool(client, request.params.name, request.params.arguments);
    return {
      isError: result.isError,
      content: [{ type: "text", text: result.text }],
    };
  });

  return server;
}

/** Starts the MCP server over stdio. Invoked by `swarmmesh mcp`. */
export async function runMcpStdioServer(client: SwarmMeshClient): Promise<void> {
  const server = createMcpServer(client);
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
