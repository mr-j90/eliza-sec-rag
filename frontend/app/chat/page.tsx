import { ChatView } from "@/components/chat/chat-view";
import { backendHealth } from "@/lib/ai/provider";
import { requireAuth } from "@/lib/auth";

/**
 * A fresh chat. No conversation row exists yet — /api/chat creates one when the
 * first message is sent and hands its id back, at which point the client swaps
 * the URL to /chat/{id}.
 */
export default async function NewChatPage() {
  await requireAuth();
  // The model comes from the backend that would answer, not from local config —
  // a label naming a model that didn't answer is worse than saying nothing.
  const health = await backendHealth();
  return (
    <ChatView
      conversationId={null}
      initialMessages={[]}
      modelLabel={health?.generationModel ?? "backend unavailable"}
    />
  );
}
