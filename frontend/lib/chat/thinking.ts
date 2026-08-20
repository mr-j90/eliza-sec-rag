/**
 * Wording for the "waiting for the first token" placeholder.
 *
 * Pure and JSX-free so it can be unit tested; the component in
 * components/chat/thinking-indicator.tsx just ticks a counter and renders what
 * this returns.
 *
 * The phases escalate with elapsed time rather than cycling at random: a
 * reasoning model can sit silent for a while, and "Still working on it" at
 * thirty seconds reassures where a chirpy "Pondering" would read as stuck.
 * Nothing here claims progress it cannot observe — no percentage, no
 * "almost done" — because the client genuinely does not know.
 */

export const TICK_MS = 2200;

export const PHASES: { afterMs: number; words: string[] }[] = [
  {
    afterMs: 0,
    words: ["Thinking", "Pondering", "Considering", "Mulling it over"],
  },
  {
    afterMs: 9_000,
    words: [
      "Reasoning it through",
      "Weighing the evidence",
      "Working through it",
      "Connecting the dots",
    ],
  },
  {
    afterMs: 24_000,
    words: [
      "Still working on it",
      "This one's taking a while",
      "Hang tight",
      "Not forgotten — still going",
    ],
  },
];

/**
 * The word to show on tick `step` (0-based, one tick per TICK_MS). Picks the
 * latest phase whose threshold has elapsed, then rotates within it.
 */
export function statusWord(step: number): string {
  const tick = Math.max(0, Math.floor(step));
  const elapsed = tick * TICK_MS;

  let phase = PHASES[0];
  for (const candidate of PHASES) {
    if (elapsed >= candidate.afterMs) phase = candidate;
  }

  return phase.words[tick % phase.words.length];
}
