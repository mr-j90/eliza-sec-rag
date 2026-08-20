import {
  askBackend,
  BackendRefused,
  BackendUnreachable,
} from "@/lib/ai/provider";
import { requireUserId } from "@/lib/auth";
import {
  appendMessage,
  createConversation,
  getConversation,
  titleFromMessage,
} from "@/lib/db/conversations";

// node:sqlite is a Node builtin, so this handler must not run on the edge.
export const runtime = "nodejs";

/**
 * Chat endpoint, and the only writer of chat history.
 *
 * Under D001 this route **makes no LLM call**. It asks the Python backend, which makes
 * exactly one, and returns the answer with the citations behind it.
 *
 * The response is **JSON, not a stream**. `/ask` produces a finished answer in one piece, and
 * re-emitting that string through a `ReadableStream` only made it look like tokens while
 * leaving no channel for citations. Sending JSON is honest about what happens and is what lets
 * the sources appear alongside the answer they support.
 *
 * Prior turns are deliberately not sent to the backend. Each question is retrieved and
 * answered independently: conversational follow-up is a stated non-goal, and feeding prior
 * assistant output back as context would put uncited text in front of a model whose first rule
 * is to answer only from cited context. History is still persisted, for the sidebar.
 */

/** No answer, and no pretending otherwise. */
function failureText(error: unknown): string {
  const reason = error instanceof Error ? error.message : String(error);
  return `**The answer backend did not respond.**\n\n${reason}`;
}

export async function POST(req: Request) {
  const userId = await requireUserId();

  const { conversationId, message } = (await req.json().catch(() => ({}))) as {
    conversationId?: unknown;
    message?: unknown;
  };

  const text = typeof message === "string" ? message.trim() : "";
  if (!text) {
    return Response.json({ error: "Expected a non-empty message" }, { status: 400 });
  }

  // Verify ownership up front; creation waits until the model that answered is known, so the
  // conversation row records what actually replied.
  let existingId: string | null = null;
  if (typeof conversationId === "string" && conversationId) {
    const existing = getConversation(userId, conversationId);
    if (!existing) {
      return Response.json({ error: "Unknown conversation" }, { status: 404 });
    }
    existingId = existing.id;
  }

  // One attempt, and the error itself carries the reason — asking twice to recover a message
  // would double the work and could spend a second generation call.
  let result: Awaited<ReturnType<typeof askBackend>> | null = null;
  let answer: string;
  try {
    result = await askBackend(text);
    answer = result.answer;
  } catch (error) {
    if (!(error instanceof BackendUnreachable || error instanceof BackendRefused)) throw error;
    answer = failureText(error);
  }

  const model = result?.generationModel ?? "unavailable";

  const id =
    existingId ?? createConversation(userId, { title: titleFromMessage(text), model });

  // Both turns land together, so history never holds a user turn with no reply — including
  // when the backend failed, where the reply *is* the failure.
  appendMessage(id, "user", text);
  appendMessage(id, "assistant", answer, {
    citations: result?.citations,
    retrievalMeta: result?.retrievalMeta,
  });

  return Response.json(
    {
      conversationId: id,
      answer,
      // Absent rather than empty when the backend never answered, so the UI shows "no
      // sources" instead of an empty sources panel implying zero were found.
      citations: result?.citations,
      retrievalMeta: result?.retrievalMeta,
      backendError: result ? undefined : true,
    },
    { status: 200 },
  );
}
