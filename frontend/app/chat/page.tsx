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
  // Asked so the composer can warn up front when the backend is unreachable.
  const health = await backendHealth();
  return (
    <ChatView
      conversationId={null}
      initialMessages={[]}
      backendAvailable={health !== null}
    />
  );
}
