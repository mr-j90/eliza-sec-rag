"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Flower2 } from "lucide-react";

import { AiComposer } from "@/components/chat/ai-composer";
import type { ChatMessage } from "@/lib/chat/types";

import { Markdown } from "./markdown";
import { Sources } from "./sources";
import { ThinkingIndicator } from "./thinking-indicator";

export function ChatView({
  conversationId,
  initialMessages,
  modelLabel,
}: {
  /** Null for a new chat — /api/chat mints the id on the first message. */
  conversationId: string | null;
  /** Transcript loaded from SQLite; empty for a new chat. */
  initialMessages: ChatMessage[];
  /** Model name to show in the composer. Fixed server-side; display only. */
  modelLabel: string;
}) {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  // Nothing streams any more — this is simply "a request is in flight".
  const [awaiting, setAwaiting] = useState(false);
  // The server owns the conversation id, but the client has to remember it
  // between the first and second message of a new chat.
  const [id, setId] = useState(conversationId);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the newest turn in view as messages arrive.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function send(text: string) {
    if (!text || awaiting) return;

    // The empty assistant turn goes in immediately, not when the response lands — the wait
    // is exactly when the user needs to see that something is happening.
    setMessages((m) => [
      ...m,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    setAwaiting(true);

    // Replace the trailing assistant turn in place, so nothing appends twice.
    const setAnswer = (message: ChatMessage) =>
      setMessages((m) => [...m.slice(0, -1), message]);

    let conversation = id;

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversationId: conversation, message: text }),
      });

      if (!res.ok) throw new Error(`Request failed: ${res.status}`);

      // JSON rather than a stream: /ask returns a finished answer, and its citations have to
      // arrive with it. See app/api/chat/route.ts.
      const body = (await res.json()) as {
        conversationId: string;
        answer: string;
        citations?: ChatMessage["citations"];
        retrievalMeta?: ChatMessage["retrievalMeta"];
      };

      conversation = body.conversationId ?? conversation;
      if (conversation !== id) setId(conversation);

      setAnswer({
        role: "assistant",
        content: body.answer,
        citations: body.citations,
        retrievalMeta: body.retrievalMeta,
      });
    } catch {
      setAnswer({
        role: "assistant",
        content: "Sorry — I couldn't reach the assistant. Please try again.",
      });
    } finally {
      setAwaiting(false);

      // Both turns are now in SQLite. Move a brand-new chat onto its own URL and refresh so
      // the sidebar picks it up. Done after the answer, never during it.
      if (conversation && conversation !== conversationId) {
        router.replace(`/chat/${conversation}`);
      }
      router.refresh();
    }
  }

  // Empty state: centered hero with the composer and suggested prompts.
  if (messages.length === 0) {
    return (
      <main className="mx-auto flex h-[calc(100vh-4rem)] w-full max-w-2xl flex-col items-center justify-center gap-8 px-6 pb-[12vh]">
        <h1 className="flex items-center gap-2.5 text-3xl font-semibold tracking-tight">
          <Flower2 className="size-7 text-primary" />
          How can I help?
        </h1>
        <AiComposer
          onSend={send}
          modelLabel={modelLabel}
          disabled={awaiting}
          showPrompts
        />
      </main>
    );
  }

  return (
    <main className="mx-auto flex h-[calc(100vh-4rem)] w-full max-w-3xl flex-col px-6 pb-6">
      <div className="flex items-center gap-2 border-b py-3">
        <Flower2 className="size-4 text-primary" />
        <span className="text-sm font-semibold">Assistant</span>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-6 overflow-y-auto py-6">
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={i} className="text-sm leading-relaxed">
              {m.content ? (
                <>
                  <Markdown content={m.content} />
                  <Sources
                    answer={m.content}
                    citations={m.citations}
                    meta={m.retrievalMeta}
                  />
                </>
              ) : awaiting ? (
                <ThinkingIndicator />
              ) : (
                // Empty and not awaiting: the request died without writing
                // anything. Say so rather than leaving a silent gap.
                <span className="text-sm text-muted-foreground">
                  No response was returned.
                </span>
              )}
            </div>
          ),
        )}
      </div>

      <AiComposer
        onSend={send}
        modelLabel={modelLabel}
        disabled={awaiting}
      />
    </main>
  );
}
