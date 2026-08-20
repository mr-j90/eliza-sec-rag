import "server-only";

/**
 * Where the RAG backend lives.
 *
 * This app names **no model of its own**. Under D001 the Python backend owns
 * generation, so the model that answered is read from the backend's `/health`
 * rather than configured here — one source of truth instead of two that drift.
 */
export const RAG_API_URL =
  process.env.RAG_API_URL?.trim() || "http://127.0.0.1:8000";
