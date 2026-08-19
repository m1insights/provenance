"""The second job: the corpus is a content backlog, not only an audit trail.

A Finding exists to change the algorithm, and it demands convergence -- three
papers pointing the same way before anything is proposed. That bar is correct
for editing a constant and far too high for saying something true on the
internet. Of 113 appraisals in the store, exactly one has ever converged into a
Finding; the other 112 were read, graded, and quoted, and then sat there.

This module ranks that pool for publication. Nothing here re-reads a paper or
re-derives a number: every candidate is an appraisal that already passed
grounding, so the claims carry a verbatim span from the abstract and the figures
came out of that span. Selection is the only judgement being made.

The gate that matters is tier. A single weak study is a fine thing to have read
and a bad thing to post -- "one small trial suggests" is how supplement
marketing works -- so Tier C and D are excluded unless explicitly asked for, and
the tier travels onto the asset itself as a chip.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import Alignment, Appraisal, EvidenceTier, Paper

log = logging.getLogger(__name__)

#: Publication record. The memory that stops a paper being posted twice.
POSTS = "provenance_posts"

#: Tier is the floor, not a score: below this a paper is not publishable at all,
#: however interesting it looks.
PUBLISHABLE_TIERS = (EvidenceTier.A, EvidenceTier.B)

_TIER_POINTS = {
    EvidenceTier.A: 40.0,   # randomised or systematic
    EvidenceTier.B: 26.0,   # prospective cohort
    EvidenceTier.C: 6.0,
    EvidenceTier.D: 0.0,
}

#: What makes a post worth watching, as opposed to worth filing. A study that
#: cuts against the received advice is the one people stop scrolling for;
#: agreement is reassuring and forgettable. This ranks attention, never truth --
#: nothing here changes how a claim is stated, only which claim gets made first.
_ALIGNMENT_POINTS = {
    Alignment.CHALLENGES: 18.0,
    Alignment.EXTENDS: 12.0,
    Alignment.SUPPORTS: 7.0,
    Alignment.NEUTRAL: 3.0,
}


@dataclass
class Candidate:
    """One publishable paper, with the motion its claims imply."""

    appraisal: Appraisal
    paper: Paper | None
    score: float
    motion: str
    reasons: list[str]

    @property
    def paper_id(self) -> str:
        return self.appraisal.paper_id

    @property
    def title(self) -> str:
        return self.paper.title if self.paper else self.appraisal.paper_id

    @property
    def numeric_claims(self) -> list:
        return [c for c in self.appraisal.claims if c.value is not None]


def pick_motion(appraisal: Appraisal) -> str:
    """Choose a motion from the shape of the claims, never for variety.

    Deliberately conservative: the count and spread of the reported figures is
    all this can see from an abstract, so it picks the motion that is honest for
    that shape and leaves the interesting calls to the operator, who can read
    the paper. `narrow` wins over `grow` when a confidence interval is present,
    because an interval is a statement about uncertainty and drawing it as a bar
    throws that away.
    """
    numeric = [c for c in appraisal.claims if c.value is not None]
    if not numeric:
        return "type"
    if any(c.ci_low is not None and c.ci_high is not None for c in numeric) and len(numeric) == 1:
        return "narrow"
    # Two kinds of null, and the first rule only ever caught the easy one.
    #
    # A ratio sitting on 1.0 is a null against no-exposure. But most of this
    # corpus reports the other kind: two exposures that both work, and work the
    # SAME -- weekend-warrior 0.76 against regularly-active 0.77. Both are far
    # from 1.0, so a rule watching for 1.0 sees a strong effect and reaches for
    # a bar chart, which then draws a difference of one percentage point as a
    # visible gap. That is the exact lie Hold exists to prevent, and it was
    # firing on nothing: zero Hold candidates across 74 publishable papers while
    # the equivalence literature is the largest block in the pool.
    #
    # The appraiser already wrote the answer in plain language when it stated
    # the claim, so read that rather than trying to infer it from the figures.
    equivalence = (
        "similar", "comparable", "no significant difference", "no difference",
        "did not differ", "equivalent", "nearly identical", "approximately equal",
        "no statistically significant",
    )
    text = " ".join(c.statement.lower() for c in appraisal.claims)
    if any(phrase in text for phrase in equivalence):
        return "hold"

    ratios = [c.value for c in numeric if c.value is not None and 0.5 < c.value < 2.0]
    if len(ratios) >= 3 and all(abs(v - 1.0) <= 0.08 for v in ratios):
        return "hold"
    if len(numeric) >= 2:
        return "grow"
    return "narrow"


def score(appraisal: Appraisal, paper: Paper | None, *, posted: set[str]) -> tuple[float, list[str]]:
    """Rank by publishability. Returns the score and why it got it."""
    reasons: list[str] = []
    if appraisal.paper_id in posted:
        return (-1.0, ["already posted"])

    total = _TIER_POINTS.get(appraisal.tier, 0.0)
    reasons.append(f"tier {appraisal.tier.value}")

    total += _ALIGNMENT_POINTS.get(appraisal.alignment, 0.0)
    if appraisal.alignment in (Alignment.CHALLENGES, Alignment.EXTENDS):
        reasons.append(f"{appraisal.alignment.value} the current rule")

    numeric = [c for c in appraisal.claims if c.value is not None]
    total += min(len(numeric), 4) * 6.0
    if numeric:
        reasons.append(f"{len(numeric)} figure{'s' if len(numeric) > 1 else ''}")
    else:
        # Copy-only posts are legitimate but they are not why this pool exists.
        total -= 14.0

    if any(c.ci_low is not None for c in numeric):
        total += 5.0
        reasons.append("reports its uncertainty")

    if pick_motion(appraisal) == "hold":
        # "Two things you think differ do not" is the most watchable finding a
        # cohort study can produce, and the hardest to fake.
        total += 10.0
        reasons.append("an equivalence result")

    if appraisal.sample_size:
        # Scale, not linearly -- 400k is not forty times more convincing than
        # 10k, but it is more convincing, and it reads well on a slide.
        if appraisal.sample_size >= 100_000:
            total += 12.0
        elif appraisal.sample_size >= 20_000:
            total += 8.0
        elif appraisal.sample_size >= 5_000:
            total += 4.0
        reasons.append(f"n={appraisal.sample_size:,}")

    if paper and paper.published:
        age_days = (datetime.now(timezone.utc).date() - paper.published).days
        if age_days <= 120:
            total += 8.0
            reasons.append("published recently")
        elif age_days > 900:
            total -= 6.0

    return (total, reasons)


def posted_ids(*, db) -> set[str]:
    """Papers already turned into an asset. The store is the memory."""
    try:
        return {doc.id for doc in db.collection(POSTS).select([]).stream()}
    except Exception:  # a missing collection must not stop a listing
        log.warning("content: could not read the posted set; assuming none")
        return set()


def mark_posted(paper_id: str, *, db, asset: str = "", note: str = "") -> None:
    db.collection(POSTS).document(paper_id).set({
        "paper_id": paper_id,
        "asset": asset,
        "note": note,
        "posted_at": datetime.now(timezone.utc),
    })


def candidates(
    appraisals: list[Appraisal],
    papers: dict[str, Paper],
    *,
    posted: set[str] | None = None,
    component: str | None = None,
    include_weak: bool = False,
    limit: int = 20,
) -> list[Candidate]:
    """The ranked publishable pool."""
    posted = posted or set()
    out: list[Candidate] = []

    for appraisal in appraisals:
        if component and component not in appraisal.component_ids:
            continue
        if not include_weak and appraisal.tier not in PUBLISHABLE_TIERS:
            continue
        value, reasons = score(appraisal, papers.get(appraisal.paper_id), posted=posted)
        if value < 0:
            continue
        out.append(Candidate(
            appraisal=appraisal,
            paper=papers.get(appraisal.paper_id),
            score=value,
            motion=pick_motion(appraisal),
            reasons=reasons,
        ))

    out.sort(key=lambda c: c.score, reverse=True)

    # Spread the queue across components. Ranking on merit alone returns six
    # weekend-warrior cohorts in a row, because that is genuinely where the
    # evidence has been piling up -- and posting them in sequence reads as one
    # idea repeated, which is a worse feed than a weaker paper on a new subject.
    # Merit still decides who represents a component; this only decides how
    # often a component gets to speak.
    if component is None:
        seen: dict[str, int] = {}
        spread: list[Candidate] = []
        for candidate in out:
            key = candidate.appraisal.component_ids[0] if candidate.appraisal.component_ids else "?"
            rank = seen.get(key, 0)
            seen[key] = rank + 1
            spread.append((candidate, rank))
        spread.sort(key=lambda pair: (pair[1], -pair[0].score))
        out = [candidate for candidate, _ in spread]

    return out[:limit]
