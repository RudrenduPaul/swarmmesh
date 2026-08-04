/**
 * SwarmMesh HTTP + WebSocket server. Implements every endpoint and the `/v1/events`
 * pub/sub socket documented in docs/protocol.md exactly — no additional endpoints, no
 * deviation from the documented request/response shapes.
 *
 * Binds to localhost by default (see docs/protocol.md security section): SwarmMesh has
 * no authentication in v1 and is designed to run on the same trust boundary as a local
 * Redis or SQLite file, not exposed to the public internet. That does not mean client
 * input is trusted — every request body is still validated (src/validate.ts).
 */
import { randomUUID } from "node:crypto";
import { createServer as createHttpServer, type Server as HttpServer } from "node:http";
import express, { type NextFunction, type Request, type Response } from "express";
import { WebSocket, WebSocketServer } from "ws";
import { Bm25RankingBackend, InMemoryBackend, type RankingBackend, type StorageBackend } from "./store.js";
import type { Agent, ContextEntry, MemoryEntry, ServerEvent, SubscribeFrame } from "./types.js";
import {
  validatePublishContext,
  validateQueryMemory,
  validateRegisterAgent,
  validateWriteMemory,
} from "./validate.js";

export interface SwarmMeshServerOptions {
  storage?: StorageBackend;
  ranking?: RankingBackend;
}

interface SubscriberState {
  subscribed: boolean;
  all: boolean;
  namespaces: Set<string>;
}

function isSubscribeFrame(value: unknown): value is SubscribeFrame {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  if (record.type !== "subscribe") return false;
  if (record.namespaces === undefined) return true;
  return Array.isArray(record.namespaces) && record.namespaces.every((n) => typeof n === "string");
}

/** The running SwarmMesh mesh: an Express HTTP server plus a `/v1/events` WebSocket
 * pub/sub server, sharing one underlying `node:http` server and one storage backend. */
export class SwarmMeshServer {
  readonly storage: StorageBackend;
  private readonly ranking: RankingBackend;
  private readonly app = express();
  private readonly httpServer: HttpServer;
  private readonly wss: WebSocketServer;
  private readonly subscribers = new Map<WebSocket, SubscriberState>();
  private readonly startedAt = Date.now();

  constructor(options: SwarmMeshServerOptions = {}) {
    this.storage = options.storage ?? new InMemoryBackend();
    this.ranking = options.ranking ?? new Bm25RankingBackend();
    this.httpServer = createHttpServer(this.app);
    this.wss = new WebSocketServer({ server: this.httpServer, path: "/v1/events" });

    this.app.use(express.json());
    this.registerRoutes();
    this.registerErrorHandler();
    this.registerWebSocket();
  }

  private registerRoutes(): void {
    const router = express.Router();

    router.post("/v1/agents", (req: Request, res: Response) => {
      const result = validateRegisterAgent(req.body as unknown);
      if (!result.ok) {
        res.status(400).json({ error: result.error });
        return;
      }
      const agent: Agent = {
        agent_id: result.value.agent_id,
        role: result.value.role,
        metadata: result.value.metadata ?? {},
        registered_at: new Date().toISOString(),
      };
      const stored = this.storage.registerAgent(agent);
      if (!stored) {
        res.status(409).json({
          error: `agent_id '${agent.agent_id}' already registered; use PUT /v1/agents/${agent.agent_id} to update metadata`,
        });
        return;
      }
      this.broadcast({ type: "agent.registered", agent_id: stored.agent_id });
      res.status(201).json(stored);
    });

    router.delete("/v1/agents/:agent_id", (req: Request, res: Response) => {
      const agentId = req.params.agent_id ?? "";
      const removed = this.storage.deregisterAgent(agentId);
      if (!removed) {
        res.status(404).json({ error: `agent_id '${agentId}' is not registered` });
        return;
      }
      this.broadcast({ type: "agent.deregistered", agent_id: agentId });
      res.status(204).end();
    });

    router.get("/v1/agents", (_req: Request, res: Response) => {
      res.status(200).json({ agents: this.storage.listAgents() });
    });

    router.put("/v1/context/:namespace/:key", (req: Request, res: Response) => {
      const namespace = req.params.namespace ?? "";
      const key = req.params.key ?? "";
      const result = validatePublishContext(req.body as unknown);
      if (!result.ok) {
        res.status(400).json({ error: result.error });
        return;
      }
      const entry: ContextEntry = {
        namespace,
        key,
        value: result.value.value,
        ttl_seconds: result.value.ttl_seconds ?? null,
        updated_by: result.value.agent_id,
        updated_at: new Date().toISOString(),
      };
      const stored = this.storage.putContext(entry);
      this.broadcast(
        {
          type: "context.updated",
          namespace: stored.namespace,
          key: stored.key,
          value: stored.value,
          updated_by: stored.updated_by,
          updated_at: stored.updated_at,
        },
        stored.namespace,
      );
      res.status(200).json(stored);
    });

    router.get("/v1/context/:namespace/:key", (req: Request, res: Response) => {
      const namespace = req.params.namespace ?? "";
      const key = req.params.key ?? "";
      const entry = this.storage.getContext(namespace, key);
      if (!entry) {
        res.status(404).json({ error: `no live context entry for ${namespace}/${key}` });
        return;
      }
      res.status(200).json(entry);
    });

    router.get("/v1/context/:namespace", (req: Request, res: Response) => {
      const namespace = req.params.namespace ?? "";
      const entries = this.storage.listContext(namespace);
      res.status(200).json({ namespace, entries });
    });

    router.delete("/v1/context/:namespace/:key", (req: Request, res: Response) => {
      const namespace = req.params.namespace ?? "";
      const key = req.params.key ?? "";
      const deleted = this.storage.deleteContext(namespace, key);
      if (deleted) {
        this.broadcast({ type: "context.deleted", namespace, key }, namespace);
      }
      res.status(204).end();
    });

    router.post("/v1/memory/:namespace", (req: Request, res: Response) => {
      const namespace = req.params.namespace ?? "";
      const result = validateWriteMemory(req.body as unknown);
      if (!result.ok) {
        res.status(400).json({ error: result.error });
        return;
      }
      const entry: MemoryEntry = {
        namespace,
        id: result.value.id ?? randomUUID(),
        text: result.value.text,
        metadata: result.value.metadata ?? {},
        created_by: result.value.agent_id,
        created_at: new Date().toISOString(),
      };
      const stored = this.storage.putMemory(entry);
      this.broadcast(
        {
          type: "memory.written",
          namespace: stored.namespace,
          id: stored.id,
          text: stored.text,
          created_by: stored.created_by,
        },
        stored.namespace,
      );
      res.status(201).json(stored);
    });

    router.post("/v1/memory/:namespace/query", (req: Request, res: Response) => {
      const namespace = req.params.namespace ?? "";
      const result = validateQueryMemory(req.body as unknown);
      if (!result.ok) {
        res.status(400).json({ error: result.error });
        return;
      }
      const entries = this.storage.listMemory(namespace);
      const results = this.ranking.query(entries, result.value.query, result.value.top_k ?? 10);
      res.status(200).json({ results });
    });

    router.get("/v1/status", (_req: Request, res: Response) => {
      res.status(200).json({
        agent_count: this.storage.countAgents(),
        namespaces: this.storage.listNamespaces(),
        context_entry_count: this.storage.countContextEntries(),
        memory_entry_count: this.storage.countMemoryEntries(),
        uptime_seconds: (Date.now() - this.startedAt) / 1000,
      });
    });

    this.app.use(router);
  }

  private registerErrorHandler(): void {
    // Express error-handling middleware must take exactly 4 params to be recognized
    // as such. Catches malformed-JSON bodies from express.json() and any handler that
    // throws synchronously.
    this.app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
      if (err instanceof SyntaxError) {
        res.status(400).json({ error: "request body must be valid JSON" });
        return;
      }
      res.status(500).json({ error: "internal server error" });
    });
  }

  private registerWebSocket(): void {
    this.wss.on("connection", (ws: WebSocket) => {
      this.subscribers.set(ws, { subscribed: false, all: false, namespaces: new Set() });

      ws.on("message", (raw: Buffer) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(raw.toString("utf8"));
        } catch {
          return;
        }
        if (!isSubscribeFrame(parsed)) return;
        const namespaces = parsed.namespaces ?? [];
        this.subscribers.set(ws, {
          subscribed: true,
          all: namespaces.length === 0,
          namespaces: new Set(namespaces),
        });
      });

      ws.on("close", () => {
        this.subscribers.delete(ws);
      });
    });
  }

  private broadcast(event: ServerEvent, namespace?: string): void {
    const payload = JSON.stringify(event);
    for (const [ws, state] of this.subscribers) {
      if (ws.readyState !== WebSocket.OPEN) continue;
      if (!state.subscribed) continue;
      const interested = namespace === undefined || state.all || state.namespaces.has(namespace);
      if (!interested) continue;
      ws.send(payload);
    }
  }

  listen(port: number, host: string): Promise<void> {
    return new Promise((resolve) => {
      this.httpServer.listen(port, host, () => resolve());
    });
  }

  address(): { host: string; port: number } | null {
    const addr = this.httpServer.address();
    if (addr === null || typeof addr === "string") return null;
    return { host: addr.address, port: addr.port };
  }

  close(): Promise<void> {
    return new Promise((resolve, reject) => {
      for (const ws of this.subscribers.keys()) ws.terminate();
      this.wss.close(() => {
        this.httpServer.close((err) => {
          this.storage.close();
          if (err) reject(err);
          else resolve();
        });
      });
    });
  }
}
