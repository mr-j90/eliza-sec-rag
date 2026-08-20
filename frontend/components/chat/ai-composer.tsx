"use client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  IconAlertTriangle,
  IconArrowUp,
  IconGavel,
  IconLoader2,
  IconScale,
  IconTrendingUp,
} from "@tabler/icons-react";
import { useRef, useState } from "react";

// Composer adapted from the blocks.so `ai-02` block — wired to the /api/chat
// send flow. There is no model picker: the model is fixed server-side.

/**
 * Suggested prompts on the empty state. Each one is a deliberate demo case:
 * cross-company comparison, a temporal trend, and a sector-wide question — the
 * three shapes the retrieval path has to handle differently.
 */
const PROMPTS = [
  {
    icon: IconScale,
    text: "Compare risk factors",
    prompt:
      "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?",
  },
  {
    icon: IconTrendingUp,
    text: "Revenue trend",
    prompt:
      "How has NVIDIA's revenue and growth outlook changed over the last two years?",
  },
  {
    icon: IconGavel,
    text: "Regulatory risk",
    prompt:
      "What regulatory risks do the banks in this corpus disclose, and where do they overlap?",
  },
];

export function AiComposer({
  onSend,
  backendAvailable,
  disabled = false,
  showPrompts = false,
}: {
  /** Called with the message text. */
  onSend: (text: string) => void;
  /**
   * Whether the RAG backend answered /health. False puts a warning in the
   * footer, so an unreachable backend is visible before a question is typed
   * rather than after it's sent. The model name is deliberately not shown:
   * it's fixed server-side and not actionable here.
   */
  backendAvailable: boolean;
  /** Disables sending (e.g. while a response is streaming). */
  disabled?: boolean;
  /** Show the suggested-prompt pills under the composer (empty state). */
  showPrompts?: boolean;
}) {
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handlePromptClick = (prompt: string) => {
    setInputValue(prompt);
    inputRef.current?.focus();
  };

  const submit = () => {
    const text = inputValue.trim();
    if (!text || disabled) return;
    onSend(text);
    setInputValue("");
  };

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <div className="flex min-h-[120px] flex-col rounded-2xl cursor-text bg-card border border-border shadow-md">
        <div className="flex-1 relative overflow-y-auto max-h-[258px]">
          <Textarea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Ask anything"
            autoFocus
            className="w-full border-0 p-3 transition-[padding] duration-200 ease-in-out min-h-[48.4px] outline-none text-[16px] text-foreground resize-none shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 bg-transparent! whitespace-pre-wrap break-words"
          />
        </div>

        <div className="flex min-h-[40px] items-center gap-2 p-2 pb-1">
          {!backendAvailable && (
            <span className="flex items-center gap-1.5 text-sm text-warning">
              <IconAlertTriangle className="h-4 w-4" />
              Backend unavailable
            </span>
          )}

          <div className="ml-auto flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              onClick={submit}
              className={cn(
                "h-8 w-8 rounded-full transition-colors duration-100 ease-out cursor-pointer bg-primary",
                inputValue && "bg-primary hover:bg-primary/90!",
              )}
              disabled={!inputValue.trim() || disabled}
              aria-label="Send message"
            >
              {disabled ? (
                <IconLoader2 className="h-4 w-4 animate-spin text-primary-foreground" />
              ) : (
                <IconArrowUp className="h-4 w-4 text-primary-foreground" />
              )}
            </Button>
          </div>
        </div>
      </div>

      {showPrompts && (
        <div className="flex flex-wrap justify-center gap-2">
          {PROMPTS.map((button) => {
            const IconComponent = button.icon;
            return (
              <Button
                key={button.text}
                variant="ghost"
                className="group flex items-center gap-2 rounded-full border px-3 py-2 text-sm text-foreground transition-colors duration-200 ease-out hover:bg-muted/30 h-auto bg-transparent dark:bg-muted"
                onClick={() => handlePromptClick(button.prompt)}
              >
                <IconComponent className="h-4 w-4 text-muted-foreground transition-colors group-hover:text-foreground" />
                <span>{button.text}</span>
              </Button>
            );
          })}
        </div>
      )}
    </div>
  );
}
