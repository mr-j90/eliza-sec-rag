"use client";

import { useEffect, useState } from "react";

import { statusWord, TICK_MS } from "@/lib/chat/thinking";

/**
 * Placeholder shown between sending a message and the first streamed token.
 * The wording lives in lib/chat/thinking.ts; this only drives the clock.
 */
export function ThinkingIndicator() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setStep((s) => s + 1), TICK_MS);
    return () => clearInterval(id);
  }, []);

  const word = statusWord(step);

  return (
    <span
      role="status"
      className="inline-flex items-center gap-2 text-muted-foreground"
    >
      {/*
       * One stable announcement for screen readers. The visible adjectives are
       * aria-hidden — piping a new word into a live region every two seconds
       * would be unusable.
       */}
      <span className="sr-only">Generating response</span>

      <span className="inline-flex items-center gap-1" aria-hidden="true">
        <span className="size-1.5 animate-pulse rounded-full bg-current" />
        <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:150ms]" />
        <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:300ms]" />
      </span>

      {/* key restarts the fade each time the word changes. */}
      <span
        key={word}
        aria-hidden="true"
        className="animate-in fade-in text-sm duration-500"
      >
        {word}…
      </span>
    </span>
  );
}
