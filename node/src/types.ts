/**
 * Shared wire-protocol types for SwarmMesh, mirroring docs/protocol.md exactly.
 * These types are the source of truth for request/response shapes used by the
 * HTTP server, storage backends, CLI, MCP surface, and client.
 */

/** Arbitrary JSON value. This is the one place `any` is used, deliberately: the
 * protocol's `value`/`metadata` fields are declared as "any JSON" in docs/protocol.md,
 * so a structural JSON type is what the spec actually calls for. */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = { [key: string]: JsonValue };

export interface Agent {
  agent_id: string;
  role: string;
  metadata: JsonObject;
  registered_at: string;
}

export interface ContextEntry {
  namespace: string;
  key: string;
  value: JsonValue;
  ttl_seconds: number | null;
  updated_by: string;
  updated_at: string;
}

export interface MemoryEntry {
  namespace: string;
  id: string;
  text: string;
  metadata: JsonObject;
  created_by: string;
  created_at: string;
}

export interface MemoryQueryResult {
  entry: MemoryEntry;
  score: number;
}

export interface StatusSnapshot {
  agent_count: number;
  namespaces: string[];
  context_entry_count: number;
  memory_entry_count: number;
  uptime_seconds: number;
}

// ---- Request bodies ----

export interface RegisterAgentRequest {
  agent_id: string;
  role: string;
  metadata?: JsonObject;
}

export interface PublishContextRequest {
  value: JsonValue;
  ttl_seconds?: number | null;
  agent_id: string;
}

export interface WriteMemoryRequest {
  text: string;
  metadata?: JsonObject;
  agent_id: string;
  id?: string;
}

export interface QueryMemoryRequest {
  query: string;
  top_k?: number;
}

// ---- WebSocket frames ----

export interface SubscribeFrame {
  type: "subscribe";
  namespaces?: string[];
}

export type ServerEvent =
  | {
      type: "context.updated";
      namespace: string;
      key: string;
      value: JsonValue;
      updated_by: string;
      updated_at: string;
    }
  | { type: "context.deleted"; namespace: string; key: string }
  | {
      type: "memory.written";
      namespace: string;
      id: string;
      text: string;
      created_by: string;
    }
  | { type: "agent.registered"; agent_id: string }
  | { type: "agent.deregistered"; agent_id: string };
