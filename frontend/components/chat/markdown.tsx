"use client";

/* eslint-disable @typescript-eslint/no-unused-vars --
   `node` is destructured out of each renderer so react-markdown's AST node
   isn't spread onto the DOM element; the binding itself is intentionally unused. */
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

// Tailwind-styled renderers for the assistant's markdown (GFM tables included).
// `node` is destructured out so it isn't spread onto the DOM element.
const COMPONENTS: Components = {
  h1: ({ node, ...p }) => (
    <h1 className="mb-2 mt-3 text-base font-bold first:mt-0" {...p} />
  ),
  h2: ({ node, ...p }) => (
    <h2 className="mb-2 mt-3 text-sm font-bold first:mt-0" {...p} />
  ),
  h3: ({ node, ...p }) => (
    <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0" {...p} />
  ),
  p: ({ node, ...p }) => (
    <p className="my-2 leading-relaxed first:mt-0 last:mb-0" {...p} />
  ),
  ul: ({ node, ...p }) => (
    <ul className="my-2 list-disc space-y-1 pl-5" {...p} />
  ),
  ol: ({ node, ...p }) => (
    <ol className="my-2 list-decimal space-y-1 pl-5" {...p} />
  ),
  li: ({ node, ...p }) => <li className="leading-relaxed" {...p} />,
  strong: ({ node, ...p }) => <strong className="font-semibold" {...p} />,
  a: ({ node, ...p }) => (
    <a
      className="text-primary underline underline-offset-2"
      target="_blank"
      rel="noreferrer"
      {...p}
    />
  ),
  code: ({ node, className, children, ...p }) => {
    const isBlock = /language-/.test(className ?? "");
    return (
      <code
        className={cn(
          "font-mono text-[0.85em]",
          !isBlock && "rounded bg-foreground/10 px-1 py-0.5",
          className,
        )}
        {...p}
      >
        {children}
      </code>
    );
  },
  pre: ({ node, ...p }) => (
    <pre
      className="my-2 overflow-x-auto rounded-md bg-foreground/5 p-3 text-xs"
      {...p}
    />
  ),
  table: ({ node, ...p }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs" {...p} />
    </div>
  ),
  thead: ({ node, ...p }) => <thead className="border-b" {...p} />,
  th: ({ node, ...p }) => (
    <th className="px-2 py-1 text-left font-semibold" {...p} />
  ),
  td: ({ node, ...p }) => <td className="border-t px-2 py-1 align-top" {...p} />,
  blockquote: ({ node, ...p }) => (
    <blockquote
      className="my-2 border-l-2 border-border pl-3 text-muted-foreground"
      {...p}
    />
  ),
  hr: () => <hr className="my-3 border-border" />,
};

export function Markdown({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
      {content}
    </ReactMarkdown>
  );
}
