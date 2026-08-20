import { notFound } from "next/navigation";

import { ChatView } from "@/components/chat/chat-view";
import { backendHealth } from "@/lib/ai/provider";
import { requireUserId } from "@/lib/auth";
import { getConversation } from "@/lib/db/conversations";

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const userId = await requireUserId();

  // getConversation is user-scoped, so someone else's id is a 404 here rather
  // than a leak.
  const conversation = getConversation(userId, id);
  if (!conversation) notFound();

  const health = await backendHealth();

  return (
    <ChatView
      // Remount on conversation switch so no state bleeds between transcripts.
      key={conversation.id}
      conversationId={conversation.id}
      initialMessages={conversation.messages}
      backendAvailable={health !== null}
    />
  );
}
