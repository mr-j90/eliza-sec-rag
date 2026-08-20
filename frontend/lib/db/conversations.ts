import "server-only";

import type {
  ChatMessage,
  ChatRole,
  Citation,
  RetrievalMeta,
} from "@/lib/chat/types";
import { db } from "@/lib/db/client";

/**
 * Chat-history repository. Every read and write is scoped by `userId`, so a
 * conversation id from one user's URL bar can never reach another's rows.
 */

export type { ChatMessage, ChatRole, Citation, RetrievalMeta };

export type ConversationSummary = {
  id: string;
  title: string;
  model: string | null;
  createdAt: string;
  updatedAt: string;
};

export type Conversation = ConversationSummary & {
  messages: ChatMessage[];
};

const TITLE_MAX = 60;

/**
 * Derive a conversation title from its first user message — deliberately
 * deterministic. Naming a chat is not worth an LLM call.
 */
export function titleFromMessage(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (!flat) return "New chat";
  if (flat.length <= TITLE_MAX) return flat;
  // Prefer a word boundary, but only if it isn't a harsh truncation.
  const cut = flat.slice(0, TITLE_MAX);
  const space = cut.lastIndexOf(" ");
  return `${(space > TITLE_MAX * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`;
}

function toSummary(row: Record<string, unknown>): ConversationSummary {
  return {
    id: row.id as string,
    title: row.title as string,
    model: (row.model as string | null) ?? null,
    createdAt: row.created_at as string,
    updatedAt: row.updated_at as string,
  };
}

/** A user's conversations, most recently active first. */
export function listConversations(userId: string): ConversationSummary[] {
  const rows = db()
    .prepare(
      `SELECT id, title, model, created_at, updated_at
         FROM conversations
        WHERE user_id = ?
        ORDER BY updated_at DESC`,
    )
    .all(userId);
  return rows.map(toSummary);
}

/** A conversation with its messages in order, or null if not the user's. */
export function getConversation(
  userId: string,
  id: string,
): Conversation | null {
  const row = db()
    .prepare(
      `SELECT id, title, model, created_at, updated_at
         FROM conversations
        WHERE id = ? AND user_id = ?`,
    )
    .get(id, userId);
  if (!row) return null;

  const messages = db()
    .prepare(
      `SELECT role, content, citations, retrieval_meta FROM messages
        WHERE conversation_id = ?
        ORDER BY id`,
    )
    .all(id)
    .map((m) => ({
      role: m.role as ChatRole,
      content: m.content as string,
      // Absent rather than empty: a user turn and an unreachable-backend reply both have
      // nothing behind them, and that is different from "zero sources were found".
      ...parseJson<Citation[]>(m.citations, "citations"),
      ...parseJson<RetrievalMeta>(m.retrieval_meta, "retrievalMeta"),
    }));

  return { ...toSummary(row), messages };
}

/** True when the conversation exists and belongs to the user. */
export function ownsConversation(userId: string, id: string): boolean {
  return Boolean(
    db()
      .prepare(`SELECT 1 FROM conversations WHERE id = ? AND user_id = ?`)
      .get(id, userId),
  );
}

export function createConversation(
  userId: string,
  { title, model }: { title: string; model?: string | null },
): string {
  const id = crypto.randomUUID();
  const now = new Date().toISOString();
  db()
    .prepare(
      `INSERT INTO conversations (id, user_id, title, model, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
    )
    .run(id, userId, title, model ?? null, now, now);
  return id;
}

/**
 * Stored JSON, decoded under the field name the app uses.
 *
 * Returns an empty object when there is nothing — spread into the message it leaves the key
 * absent, which is what distinguishes "no sources" from "an empty list of sources". A row
 * written before these columns existed reads as null and lands here too.
 */
function parseJson<T>(value: unknown, key: string): Record<string, T> {
  if (typeof value !== "string" || !value) return {};
  try {
    return { [key]: JSON.parse(value) as T };
  } catch {
    // Unreadable provenance must not take the conversation down with it.
    return {};
  }
}

export type MessageSources = {
  citations?: Citation[];
  retrievalMeta?: RetrievalMeta;
};

/** Append a message and bump the conversation's activity timestamp. */
export function appendMessage(
  conversationId: string,
  role: ChatRole,
  content: string,
  sources: MessageSources = {},
): void {
  const now = new Date().toISOString();
  db()
    .prepare(
      `INSERT INTO messages (conversation_id, role, content, citations, retrieval_meta, created_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
    )
    .run(
      conversationId,
      role,
      content,
      sources.citations?.length ? JSON.stringify(sources.citations) : null,
      sources.retrievalMeta ? JSON.stringify(sources.retrievalMeta) : null,
      now,
    );
  db()
    .prepare(`UPDATE conversations SET updated_at = ? WHERE id = ?`)
    .run(now, conversationId);
}

/** Returns false when the conversation isn't the user's (caller can 404). */
export function renameConversation(
  userId: string,
  id: string,
  title: string,
): boolean {
  const clean = title.replace(/\s+/g, " ").trim().slice(0, 200);
  if (!clean) return false;
  const { changes } = db()
    .prepare(
      `UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?`,
    )
    .run(clean, id, userId);
  return Number(changes) > 0;
}

/** Messages go with it via ON DELETE CASCADE (foreign_keys pragma is on). */
export function deleteConversation(userId: string, id: string): boolean {
  const { changes } = db()
    .prepare(`DELETE FROM conversations WHERE id = ? AND user_id = ?`)
    .run(id, userId);
  return Number(changes) > 0;
}
