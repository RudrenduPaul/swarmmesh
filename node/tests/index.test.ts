import { describe, expect, it } from "vitest";
import * as SwarmMesh from "../src/index.js";

describe("public library surface (src/index.ts)", () => {
  it("exports the client, server, and storage/ranking classes", () => {
    expect(SwarmMesh.SwarmMeshClient).toBeTypeOf("function");
    expect(SwarmMesh.SwarmMeshServer).toBeTypeOf("function");
    expect(SwarmMesh.InMemoryBackend).toBeTypeOf("function");
    expect(SwarmMesh.SqliteBackend).toBeTypeOf("function");
    expect(SwarmMesh.Bm25RankingBackend).toBeTypeOf("function");
    expect(SwarmMesh.SwarmMeshHttpError).toBeTypeOf("function");
    expect(SwarmMesh.DEFAULT_HOST).toBe("127.0.0.1");
    expect(SwarmMesh.DEFAULT_PORT).toBe(8420);
  });

  it("wires an SwarmMeshClient end-to-end against an SwarmMeshServer via the public exports", async () => {
    const server = new SwarmMesh.SwarmMeshServer({ storage: new SwarmMesh.InMemoryBackend() });
    await server.listen(0, "127.0.0.1");
    const addr = server.address();
    if (!addr) throw new Error("no address");
    const client = new SwarmMesh.SwarmMeshClient({ host: "127.0.0.1", port: addr.port });
    const status = await client.getStatus();
    expect(status.agent_count).toBe(0);
    await server.close();
  });
});
