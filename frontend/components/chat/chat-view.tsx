"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Flower2 } from "lucide-react";

import { AiComposer } from "@/components/chat/ai-composer";
import { citationAnchorId } from "@/lib/chat/citation-anchors";
import type { ChatMessage } from "@/lib/chat/types";

import { Markdown } from "./markdown";
import { Sources } from "./sources";
import { ThinkingIndicator } from "./thinking-indicator";

/**
 * One assistant turn: the answer, and the sources it stands on.
 *
 * Its own component because the `[Cn]` handles in the answer link to entries in the panel
 * below, and the two need to agree on which entry is which. The state lives at the turn rather
 * than at the transcript: handles restart at C1 in every answer, so `C3` means a different
 * passage two turns down and one shared "focused citation" would highlight the wrong one.
 */
function AssistantTurn({ message, index }: { message: ChatMessage; index: number }) {
  const [focused, setFocused] = useState<string | null>(null);

  // Only handles that resolve to a retrieved passage become links. A fabricated one stays
  // plain text: a link implies provenance, and offering it for a citation the backend could
  // not verify is the failure the citation check exists to catch.
  const resolvable = useMemo(
    () => new Set((message.citations ?? []).map((citation) => citation.id)),
    [message.citations],
  );

  const prefix = `turn-${index}`;
  const select = useCallback(
    (citationId: string) => {
      setFocused(citationId);
      // The transcript scrolls in its own container, so this is a scroll rather than a hash
      // navigation. `nearest` keeps the answer in view when the entry is already on screen.
      document
        .getElementById(citationAnchorId(prefix, citationId))
        ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    },
    [prefix],
  );

  return (
    <div className="text-sm leading-relaxed">
      <Markdown
        content={message.content}
        citations={{ prefix, resolvable, onSelect: select }}
      />
      <Sources
        answer={message.content}
        citations={message.citations}
        meta={message.retrievalMeta}
        anchorPrefix={prefix}
        focusedCitationId={focused}
      />
    </div>
  );
}


export function ChatView({
  conversationId,
  initialMessages,
  backendAvailable,
}: {
  /** Null for a new chat — /api/chat mints the id on the first message. */
  conversationId: string | null;
  /** Transcript loaded from SQLite; empty for a new chat. */
  initialMessages: ChatMessage[];
  /** Whether the backend answered /health; false shows a composer warning. */
  backendAvailable: boolean;
}) {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  // Nothing streams any more — this is simply "a request is in flight".
  const [awaiting, setAwaiting] = useState(false);
  // The server owns the conversation id, but the client has to remember it
  // between the first and second message of a new chat.
  const [id, setId] = useState(conversationId);
  const lastQuestionRef = useRef<HTMLDivElement>(null);
  const firstPaint = useRef(true);

  // Pin the newest question to the top of the transcript — deliberately not the bottom.
  // An answer here is five sections plus a sources panel, so scrolling to the end of the
  // transcript landed the reader *past* everything they asked for and left them scrolling
  // back up to read it. Pinning the question puts the answer's first line under it instead.
  //
  // Runs on every message change, including the answer replacing the placeholder: at send
  // time the transcript is too short to move the question far, and the arriving answer is
  // what makes the room.
  useEffect(() => {
    lastQuestionRef.current?.scrollIntoView({
      // No animation on the first paint: opening a conversation from the sidebar would
      // otherwise animate down through the whole transcript.
      behavior: firstPaint.current ? "instant" : "smooth",
      block: "start",
    });
    firstPaint.current = false;
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

  // The turn the view pins to. `reduce` rather than `findLastIndex` to stay inside the
  // project's TS lib target.
  const lastQuestion = messages.reduce(
    (last, m, i) => (m.role === "user" ? i : last),
    -1,
  );

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
          backendAvailable={backendAvailable}
          disabled={awaiting}
          showPrompts
        />
      </main>
    );
  }

  return (
    <main className="mx-auto flex h-[calc(100vh-4rem)] w-full max-w-3xl flex-col px-6 pb-6">
      <div className="no-scrollbar flex-1 space-y-6 overflow-y-auto py-6">
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div
              key={i}
              ref={i === lastQuestion ? lastQuestionRef : undefined}
              className="flex scroll-mt-6 justify-end"
            >
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground">
                {m.content}
              </div>
            </div>
          ) : m.content ? (
            <AssistantTurn key={i} message={m} index={i} />
          ) : (
            <div key={i} className="text-sm leading-relaxed">
              {awaiting ? (
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
        backendAvailable={backendAvailable}
        disabled={awaiting}
      />
    </main>
  );
}
