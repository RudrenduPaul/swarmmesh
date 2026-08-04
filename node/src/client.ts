/**
 * A small HTTP client wrapping every SwarmMesh endpoint documented in
 * docs/protocol.md. Used internally by the CLI (src/cli.ts) and the MCP surface
 * (src/mcp.ts), and exported for anyone who wants to script against a running mesh
 * from TypeScript or JavaScript.
 */
import { fetch } from "undici";
import type {
  Agent,
  ContextEntry,
  JsonValue,
  MemoryEntry,
  MemoryQueryResult,
  StatusSnapshot,
} from "./types.js";

/** Default port a `swarmmesh serve` process listens on when `--port` is omitted. */
export const DEFAULT_PORT = 8420;
/** Default host, matching docs/protocol.md's localhost-only security posture. */
export const DEFAULT_HOST = "127.0.0.1";

export interface SwarmMeshClientOptions {
  host?: string;
  port?: number;
  /** Full base URL, overrides host/port when set. */
  baseUrl?: string;
}

/** Thrown for any non-2xx HTTP response. Carries the status code so callers (e.g. the
 * CLI) can map it to an exit code or a specific message. */
export class SwarmMeshHttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "SwarmMeshHttpError";
    this.status = status;
  }
}

export class SwarmMeshClient {
  private readonly baseUrl: string;

  constructor(options: SwarmMeshClientOptions = {}) {
    this.baseUrl =
      options.baseUrl ?? `http://${options.host ?? DEFAULT_HOST}:${options.port ?? DEFAULT_PORT}`;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<{ status: number; json: T | null }> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    const json = text.length > 0 ? (JSON.parse(text) as T) : null;
    return { status: response.status, json };
  }

  private async requestOrThrow<T>(method: string, path: string, body?: unknown): Promise<T> {
    const { status, json } = await this.request<T>(method, path, body);
    if (status >= 200 && status < 300) {
      return json as T;
    }
    const message =
      json !== null && typeof json === "object" && "error" in json
        ? String((json as { error: unknown }).error)
        : `request to ${path} failed with status ${status}`;
    throw new SwarmMeshHttpError(status, message);
  }

  async registerAgent(agentId: string, role: string, metadata?: Record<string, JsonValue>): Promise<Agent> {
    return this.requestOrThrow<Agent>("POST", "/v1/agents", {
      agent_id: agentId,
      role,
      metadata,
    });
  }

  async deregisterAgent(agentId: string): Promise<void> {
    await this.requestOrThrow<null>("DELETE", `/v1/agents/${encodeURIComponent(agentId)}`);
  }

  async listAgents(): Promise<Agent[]> {
    const result = await this.requestOrThrow<{ agents: Agent[] }>("GET", "/v1/agents");
    return result.agents;
  }

  async publishContext(
    namespace: string,
    key: string,
    value: JsonValue,
    agentId: string,
    ttlSeconds?: number | null,
  ): Promise<ContextEntry> {
    return this.requestOrThrow<ContextEntry>(
      "PUT",
      `/v1/context/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`,
      { value, agent_id: agentId, ttl_seconds: ttlSeconds ?? undefined },
    );
  }

  /** Returns `null` for a 404 (unset or expired), matching the protocol's semantics
   * rather than throwing for an expected "not found" case. */
  async getContext(namespace: string, key: string): Promise<ContextEntry | null> {
    const { status, json } = await this.request<ContextEntry>(
      "GET",
      `/v1/context/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`,
    );
    if (status === 404) return null;
    if (status < 200 || status >= 300) {
      throw new SwarmMeshHttpError(status, `failed to get context ${namespace}/${key}`);
    }
    return json;
  }

  async listContext(namespace: string): Promise<ContextEntry[]> {
    const result = await this.requestOrThrow<{ namespace: string; entries: ContextEntry[] }>(
      "GET",
      `/v1/context/${encodeURIComponent(namespace)}`,
    );
    return result.entries;
  }

  async deleteContext(namespace: string, key: string): Promise<void> {
    await this.requestOrThrow<null>(
      "DELETE",
      `/v1/context/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`,
    );
  }

  async writeMemory(
    namespace: string,
    text: string,
    agentId: string,
    options?: { metadata?: Record<string, JsonValue>; id?: string },
  ): Promise<MemoryEntry> {
    return this.requestOrThrow<MemoryEntry>("POST", `/v1/memory/${encodeURIComponent(namespace)}`, {
      text,
      agent_id: agentId,
      metadata: options?.metadata,
      id: options?.id,
    });
  }

  async queryMemory(namespace: string, query: string, topK?: number): Promise<MemoryQueryResult[]> {
    const result = await this.requestOrThrow<{ results: MemoryQueryResult[] }>(
      "POST",
      `/v1/memory/${encodeURIComponent(namespace)}/query`,
      { query, top_k: topK },
    );
    return result.results;
  }

  async getStatus(): Promise<StatusSnapshot> {
    return this.requestOrThrow<StatusSnapshot>("GET", "/v1/status");
  }
}
