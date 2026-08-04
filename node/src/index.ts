/**
 * Public library surface for `swarmmesh-cli`. Import from here to script against a
 * SwarmMesh mesh, or to embed the server, from TypeScript/JavaScript.
 */
export {
  DEFAULT_HOST,
  DEFAULT_PORT,
  SwarmMeshClient,
  SwarmMeshHttpError,
  type SwarmMeshClientOptions,
} from "./client.js";
export { SwarmMeshServer, type SwarmMeshServerOptions } from "./server.js";
export {
  Bm25RankingBackend,
  InMemoryBackend,
  SqliteBackend,
  type EmbeddingRankingBackend,
  type RankingBackend,
  type StorageBackend,
} from "./store.js";
export * from "./types.js";
