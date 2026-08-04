import { describe, expect, it } from "vitest";
import {
  validatePublishContext,
  validateQueryMemory,
  validateRegisterAgent,
  validateWriteMemory,
} from "../src/validate.js";

describe("validateRegisterAgent", () => {
  it("rejects a non-object body", () => {
    expect(validateRegisterAgent("nope").ok).toBe(false);
    expect(validateRegisterAgent(null).ok).toBe(false);
  });

  it("rejects a non-JSON-object metadata field", () => {
    const result = validateRegisterAgent({ agent_id: "a1", role: "x", metadata: "not-an-object" });
    expect(result.ok).toBe(false);
  });

  it("defaults metadata to {} when omitted", () => {
    const result = validateRegisterAgent({ agent_id: "a1", role: "x" });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.metadata).toEqual({});
  });
});

describe("validatePublishContext", () => {
  it("requires a value field", () => {
    const result = validatePublishContext({ agent_id: "a1" });
    expect(result.ok).toBe(false);
  });

  it("accepts an explicit null value", () => {
    const result = validatePublishContext({ value: null, agent_id: "a1" });
    expect(result.ok).toBe(true);
  });

  it("rejects a negative ttl_seconds", () => {
    const result = validatePublishContext({ value: "x", agent_id: "a1", ttl_seconds: -5 });
    expect(result.ok).toBe(false);
  });

  it("rejects a non-integer ttl_seconds", () => {
    const result = validatePublishContext({ value: "x", agent_id: "a1", ttl_seconds: 1.5 });
    expect(result.ok).toBe(false);
  });

  it("accepts a null ttl_seconds", () => {
    const result = validatePublishContext({ value: "x", agent_id: "a1", ttl_seconds: null });
    expect(result.ok).toBe(true);
  });
});

describe("validateWriteMemory", () => {
  it("rejects a non-JSON-object metadata field", () => {
    const result = validateWriteMemory({ text: "hi", agent_id: "a1", metadata: 42 });
    expect(result.ok).toBe(false);
  });

  it("rejects an empty-string id", () => {
    const result = validateWriteMemory({ text: "hi", agent_id: "a1", id: "" });
    expect(result.ok).toBe(false);
  });

  it("accepts a valid explicit id", () => {
    const result = validateWriteMemory({ text: "hi", agent_id: "a1", id: "custom-id" });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.id).toBe("custom-id");
  });
});

describe("validateQueryMemory", () => {
  it("rejects a zero or negative top_k", () => {
    expect(validateQueryMemory({ query: "x", top_k: 0 }).ok).toBe(false);
    expect(validateQueryMemory({ query: "x", top_k: -1 }).ok).toBe(false);
  });

  it("rejects a non-integer top_k", () => {
    expect(validateQueryMemory({ query: "x", top_k: 1.5 }).ok).toBe(false);
  });

  it("defaults top_k to 10 when omitted", () => {
    const result = validateQueryMemory({ query: "x" });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.top_k).toBe(10);
  });

  it("rejects an empty query", () => {
    expect(validateQueryMemory({ query: "" }).ok).toBe(false);
  });
});
