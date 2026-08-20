"use client";

import { useState } from "react";
import { IconChevronRight, IconFileText } from "@tabler/icons-react";

import type { Citation, RetrievalMeta } from "@/lib/chat/types";

/**
 * The sources behind an answer.
 *
 * SPEC §8 treats this as the highest-value thing on screen: being able to show *which
 * filings produced this claim* is what separates a cited working document from an unusable
 * summary.
 *
 * So the citations the answer actually used are listed plainly and always, while the
 * passages that were retrieved but never cited sit behind a disclosure. Retrieval returns
 * `top_k` candidates and a good answer uses a subset — presenting all of them with equal
 * weight would bury the nine that support the text under eleven that do not. Both counts
 * stay visible, because "20 considered, 9 used" is itself informative.
 */

/** `[C1]`, `[C14]` — the handles the model actually cited, in first-appearance order. */
function citedIds(answer: string): string[] {
  const seen = new Set<string>();
  for (const match of answer.matchAll(/\[(C\d+)\]/g)) seen.add(match[1]);
  return [...seen];
}

function Provenance({ citation }: { citation: Citation }) {
  return (
    <li className="text-xs">
      <div className="flex flex-wrap items-baseline gap-x-1.5">
        <span className="rounded bg-primary/10 px-1 py-0.5 font-mono font-medium text-primary">
          [{citation.id}]
        </span>
        <span className="font-medium">{citation.company}</span>
        <span className="text-muted-foreground">
          {citation.form_type} FY{citation.fiscal_year} · {citation.section}
        </span>
      </div>
      <p className="mt-1 line-clamp-2 text-muted-foreground">{citation.excerpt}</p>
      <p className="mt-0.5 font-mono text-[10px] text-muted-foreground/70">
        {citation.source_file}
      </p>
    </li>
  );
}

function Facts({ meta, used, total }: { meta?: RetrievalMeta; used: number; total: number }) {
  const facts: string[] = [`${used} of ${total} passages cited`];
  const latency = meta?.latency_ms;

  // What the question was understood to ask for. Shown because a reader checking whether the
  // answer covered all three companies should not have to infer it from the source list.
  if (meta?.entities_detected?.length) {
    facts.push(`companies: ${meta.entities_detected.join(", ")}`);
  }
  if (meta?.fiscal_years?.length === 2) {
    const [from, to] = meta.fiscal_years;
    facts.push(from === to ? `FY${from}` : `FY${from}-${to}`);
  }
  if (meta?.form_type) facts.push(meta.form_type);
  if (meta?.retrieval) facts.push(meta.retrieval);
  if (latency?.retrieval !== undefined)
    facts.push(`retrieval ${Math.round(latency.retrieval)} ms`);
  if (latency?.generation !== undefined)
    facts.push(`generation ${(latency.generation / 1000).toFixed(1)} s`);
  if (meta?.generation_model) facts.push(meta.generation_model);
  if (meta?.prompt_version) facts.push(`prompt ${meta.prompt_version}`);

  return <p className="mt-2 text-xs text-muted-foreground">{facts.join(" · ")}</p>;
}

export function Sources({
  answer,
  citations,
  meta,
}: {
  answer: string;
  citations?: Citation[];
  meta?: RetrievalMeta;
}) {
  const [showRest, setShowRest] = useState(false);

  // Nothing behind the answer — an unreachable backend, or a turn that never had sources.
  // Renders nothing rather than an empty panel implying zero were found.
  if (!citations?.length) return null;

  const cited = new Set(citedIds(answer));
  const used = citations.filter((c) => cited.has(c.id));
  const unused = citations.filter((c) => !cited.has(c.id));

  // An answer that cites nothing is worth surfacing rather than hiding: it means the model
  // ignored the citation rule, which the whole contract exists to enforce.
  const headline = used.length ? used : citations;

  return (
    <div className="mt-3 rounded-lg border bg-muted/30 px-3 py-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <IconFileText className="size-3.5" aria-hidden />
        {used.length ? "Sources" : "Retrieved passages (the answer cited none)"}
      </div>

      {meta?.unresolved_mentions?.length ? (
        <p className="mt-1.5 text-xs text-amber-600 dark:text-amber-500">
          Not in this corpus: {meta.unresolved_mentions.join(", ")}
        </p>
      ) : null}

      <ul className="mt-2 space-y-2">
        {headline.map((citation) => (
          <Provenance key={citation.id} citation={citation} />
        ))}
      </ul>

      {used.length > 0 && unused.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setShowRest((was) => !was)}
            aria-expanded={showRest}
            className="mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <IconChevronRight
              className={`size-3.5 transition-transform ${showRest ? "rotate-90" : ""}`}
              aria-hidden
            />
            {unused.length} retrieved but not cited
          </button>
          {showRest && (
            <ul className="mt-2 space-y-2 border-t pt-2">
              {unused.map((citation) => (
                <Provenance key={citation.id} citation={citation} />
              ))}
            </ul>
          )}
        </>
      )}

      <Facts meta={meta} used={used.length} total={citations.length} />
    </div>
  );
}
