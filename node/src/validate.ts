/**
 * Request-body validation for the HTTP surface. Nothing from a client is trusted
 * blindly, even though the server binds to localhost by default (see docs/protocol.md
 * security section) — malformed or malicious bodies still get rejected with 400 rather
 * than crashing the process or corrupting stored state.
 */
import type {
  JsonObject,
  JsonValue,
  PublishContextRequest,
  QueryMemoryRequest,
  RegisterAgentRequest,
  WriteMemoryRequest,
} from "./types.js";

export type ValidationResult<T> = { ok: true; value: T } | { ok: false; error: string };

function ok<T>(value: T): ValidationResult<T> {
  return { ok: true, value };
}

function fail<T>(error: string): ValidationResult<T> {
  return { ok: false, error };
}

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function validateRegisterAgent(body: unknown): ValidationResult<RegisterAgentRequest> {
  if (!isPlainRecord(body)) return fail("request body must be a JSON object");
  if (!isNonEmptyString(body.agent_id)) return fail("agent_id must be a non-empty string");
  if (!isNonEmptyString(body.role)) return fail("role must be a non-empty string");
  if (body.metadata !== undefined && !isJsonObject(body.metadata)) {
    return fail("metadata must be a JSON object");
  }
  return ok({
    agent_id: body.agent_id,
    role: body.role,
    metadata: body.metadata ?? {},
  });
}

export function validatePublishContext(body: unknown): ValidationResult<PublishContextRequest> {
  if (!isPlainRecord(body)) return fail("request body must be a JSON object");
  if (!("value" in body)) return fail("value is required");
  if (!isNonEmptyString(body.agent_id)) return fail("agent_id must be a non-empty string");
  if (
    body.ttl_seconds !== undefined &&
    body.ttl_seconds !== null &&
    !(Number.isInteger(body.ttl_seconds) && (body.ttl_seconds as number) >= 0)
  ) {
    return fail("ttl_seconds must be a non-negative integer or null");
  }
  return ok({
    value: body.value as JsonValue,
    ttl_seconds: (body.ttl_seconds as number | null | undefined) ?? null,
    agent_id: body.agent_id,
  });
}

export function validateWriteMemory(body: unknown): ValidationResult<WriteMemoryRequest> {
  if (!isPlainRecord(body)) return fail("request body must be a JSON object");
  if (!isNonEmptyString(body.text)) return fail("text must be a non-empty string");
  if (!isNonEmptyString(body.agent_id)) return fail("agent_id must be a non-empty string");
  if (body.metadata !== undefined && !isJsonObject(body.metadata)) {
    return fail("metadata must be a JSON object");
  }
  if (body.id !== undefined && !isNonEmptyString(body.id)) {
    return fail("id must be a non-empty string");
  }
  return ok({
    text: body.text,
    agent_id: body.agent_id,
    metadata: body.metadata ?? {},
    id: body.id,
  });
}

export function validateQueryMemory(body: unknown): ValidationResult<QueryMemoryRequest> {
  if (!isPlainRecord(body)) return fail("request body must be a JSON object");
  if (!isNonEmptyString(body.query)) return fail("query must be a non-empty string");
  if (
    body.top_k !== undefined &&
    !(Number.isInteger(body.top_k) && (body.top_k as number) > 0)
  ) {
    return fail("top_k must be a positive integer");
  }
  return ok({
    query: body.query,
    top_k: (body.top_k as number | undefined) ?? 10,
  });
}
