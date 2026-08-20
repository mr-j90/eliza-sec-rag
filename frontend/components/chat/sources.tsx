"use client";

import { useState } from "react";
import { IconChevronRight, IconFileText } from "@tabler/icons-react";

import { citationAnchorId } from "@/lib/chat/citation-anchors";
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

/**
 * What period this passage is from.
 *
 * The period end, not a bare `FY2025`. For the 18 of 54 issuers in this corpus whose fiscal
 * year does not end in December, the two disagree: NVIDIA calls the quarter ending
 * 2025-10-26 "fiscal year 2026", so the old label sat directly above an excerpt naming a
 * different year — the kind of contradiction a reader spots immediately and that then puts
 * every other figure on screen in doubt.
 *
 * A date is a fact and cannot contradict the passage. Falls back to the year for the one
 * filing whose period end is not recoverable.
 */
function periodLabel(citation: Citation): string {
  if (!citation.period_end) return `FY${citation.fiscal_year}`;
  return `period ending ${citation.period_end}`;
}

function Provenance({
  citation,
  anchorPrefix,
  focused,
}: {
  citation: Citation;
  /** Set when the handles in the answer link here. Absent for a turn without linking. */
  anchorPrefix?: string;
  /** This is the entry the reader just jumped to. */
  focused?: boolean;
}) {
  return (
    <li
      id={anchorPrefix ? citationAnchorId(anchorPrefix, citation.id) : undefined}
      // `scroll-mt` keeps the entry clear of the top edge when jumped to, and the ring marks
      // which one was asked for — arriving at a list of near-identical entries with no
      // indication of that is barely better than not jumping at all. It stays until another
      // handle is clicked, so a reader comparing the claim with its passage can look back and
      // forth without losing their place.
      className={`scroll-mt-4 rounded text-xs transition-shadow duration-500 ${
        focused ? "ring-2 ring-primary/40" : "ring-0"
      }`}
    >
      <div className="flex flex-wrap items-baseline gap-x-1.5">
        <span className="rounded bg-primary/10 px-1 py-0.5 font-mono font-medium text-primary">
          [{citation.id}]
        </span>
        <span className="font-medium">{citation.company}</span>
        <span className="text-muted-foreground">
          {citation.form_type} · {periodLabel(citation)} · {citation.section}
        </span>
      </div>
      <p className="mt-1 line-clamp-2 text-muted-foreground">{citation.excerpt}</p>
      <p className="mt-0.5 font-mono text-[10px] text-muted-foreground/70">
        {citation.source_file}
      </p>
    </li>
  );
}

/**
 * Shown only when the backend found a handle that resolves to nothing.
 *
 * Surfaced rather than silently corrected: the whole value of this system is that a claim can
 * be traced to a filing, so a citation that cannot be is the most important thing on screen.
 * An answer with a bad handle stripped out would look exactly like one that passed.
 */
function FabricatedCitationWarning({
  check,
}: {
  check?: RetrievalMeta["citation_check"];
}) {
  const fabricated = check?.fabricated ?? [];
  if (!fabricated.length) return null;
  return (
    <p className="mt-1.5 text-xs font-medium text-red-600 dark:text-red-500">
      {fabricated.length === 1 ? "Citation" : "Citations"} {fabricated.join(", ")} in the answer
      {fabricated.length === 1 ? " does" : " do"} not correspond to any retrieved passage and
      cannot be verified.
    </p>
  );
}

/**
 * What the answer stood on — the backend's computed sentence, rendered verbatim.
 *
 * Verbatim is the point. The same string is given to the model so its prose can hedge in
 * proportion to the evidence, but a coverage claim the model paraphrased would be a claim
 * nobody checked. This copy is authoritative.
 *
 * It goes amber when the corpus holds a single filing for some company, because that is the
 * case a reader most needs to notice: the panel's pharmaceutical question resolves to two
 * companies with real coverage and four with one filing each, and an answer that reads as an
 * industry survey is standing on far less than it appears to.
 */
function CoverageNote({ coverage }: { coverage?: RetrievalMeta["coverage"] }) {
  const sentence = coverage?.sentence;
  if (!sentence) return null;

  const thin = (coverage?.thin?.length ?? 0) > 0 || (coverage?.named_but_absent?.length ?? 0) > 0;

  return (
    <p
      className={`mt-1.5 text-xs ${
        thin ? "text-amber-600 dark:text-amber-500" : "text-muted-foreground"
      }`}
    >
      {sentence}
    </p>
  );
}

function Facts({ meta, used, total }: { meta?: RetrievalMeta; used: number; total: number }) {
  // Prefer the backend's verified count over the client-side parse. Both read the same
  // answer, but only one of them checked the handles against what was actually retrieved —
  // and two independent counts of the same thing is how they drift.
  const verifiedCount = meta?.citation_check?.n_cited;
  const facts: string[] = [
    verifiedCount === undefined
      ? `${used} of ${total} passages cited`
      : `${verifiedCount} of ${meta?.citation_check?.n_available ?? total} passages cited (verified)`,
  ];
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
  anchorPrefix,
  focusedCitationId,
}: {
  answer: string;
  citations?: Citation[];
  meta?: RetrievalMeta;
  /**
   * Namespaces the DOM id of each entry so the `[Cn]` links in this turn's answer reach this
   * turn's sources — every answer in a conversation numbers its handles from C1.
   */
  anchorPrefix?: string;
  /** The entry the reader most recently jumped to, highlighted until they jump to another. */
  focusedCitationId?: string | null;
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

      <CoverageNote coverage={meta?.coverage} />
      <FabricatedCitationWarning check={meta?.citation_check} />

      <ul className="mt-2 space-y-2">
        {headline.map((citation) => (
          <Provenance
            key={citation.id}
            citation={citation}
            anchorPrefix={anchorPrefix}
            focused={citation.id === focusedCitationId}
          />
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
                <Provenance
                  key={citation.id}
                  citation={citation}
                  anchorPrefix={anchorPrefix}
                  focused={citation.id === focusedCitationId}
                />
              ))}
            </ul>
          )}
        </>
      )}

      <Facts meta={meta} used={used.length} total={citations.length} />
    </div>
  );
}
