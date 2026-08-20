"""Citation handles, checked rather than trusted.

The whole value proposition of this system is that every claim is traceable to a filing. A
`[C7]` in an answer where only six passages were retrieved is a **false claim of
groundedness** — strictly worse than no citation, because it looks like provenance.

Measured across thirteen saved runs before this existed: **zero fabricated handles.** So this
is not fixing a live defect. It exists because "every citation resolves" is the claim the
system is built on, and a claim that is checked is worth more than one that has merely held so
far. It also makes the count on screen a *verified* count rather than a reported one.

**Flag, do not strip.** Removing a bad handle produces clean prose and silently edits the
model's answer; a stripped answer looks identical whether or not the check ran. Surfacing the
failure is both more honest and the better demo — it proves the check exists.

**A refusal cites nothing, and that is correct.** The refusal path deliberately emits two
sections and no handles, over twenty retrieved passages that are all about companies nobody
asked about. Treating that as a failure would penalise the single most important behaviour in
the system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `[C1]`, `[C14]`. Matches the handle format `prompt.handle` emits and the one
# `frontend/components/chat/sources.tsx` parses.
HANDLE = re.compile(r"\[(C\d+)\]")


@dataclass(frozen=True)
class CitationCheck:
    """The verdict on one answer's citations."""

    cited: tuple[str, ...]
    """Handles the answer used that resolve to a retrieved passage, first-appearance order."""

    fabricated: tuple[str, ...]
    """Handles the answer used that resolve to nothing. Should always be empty."""

    available: int
    """Passages that were put in front of the model."""

    @property
    def ok(self) -> bool:
        return not self.fabricated

    @property
    def is_uncited(self) -> bool:
        """No handles at all — a refusal, or a contract violation.

        Deliberately not called a failure. Which of the two it is cannot be told from the
        handles alone, and the answer-contract tests judge that on the prose.
        """
        return not self.cited and not self.fabricated

    def as_dict(self) -> dict[str, object]:
        return {
            "cited": list(self.cited),
            "fabricated": list(self.fabricated),
            "n_cited": len(self.cited),
            "n_available": self.available,
            "verified": self.ok,
        }


def verify_citations(answer: str, handles: list[str]) -> CitationCheck:
    """Check every handle the answer emitted against the ones actually supplied.

    `handles` is the ids of the retrieved passages, in the order they were given to the model.
    """
    available = set(handles)
    cited: list[str] = []
    fabricated: list[str] = []
    seen: set[str] = set()

    for match in HANDLE.finditer(answer):
        handle = match.group(1)
        if handle in seen:
            continue
        seen.add(handle)
        (cited if handle in available else fabricated).append(handle)

    return CitationCheck(
        cited=tuple(cited), fabricated=tuple(fabricated), available=len(available)
    )
