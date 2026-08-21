"""Email, and only when it needs you.

Two things arrive. A decision request, sent the morning after a proposal opens.
And a Sunday digest of what was read and refused, which exists as much to prove
the pipeline is alive as to inform -- total silence and a silently broken cron
job look identical from the outside.

Nothing else. A daily "nothing to report" is how a system teaches its reader to
swipe past the one message that mattered.

**The links in these emails do not act.** Mail scanners, link previewers and
spam filters follow every URL in a message, so a one-click approve link gets
clicked by software before a person sees it. The link opens a page that is
already authenticated; the decision still needs a button pressed on it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from collections import Counter

from .models import Appraisal, Finding, Paper, Rejection

log = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"

#: A review link is a credential. Long enough to act on over a weekend, short
#: enough that a forwarded email stops working.
LINK_TTL_HOURS = 96


@dataclass(frozen=True)
class MailConfig:
    api_key: str
    sender: str
    recipient: str
    console_url: str
    signing_key: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.sender and self.recipient)


def mail_config() -> MailConfig:
    return MailConfig(
        api_key=os.getenv("RESEND_API_KEY", ""),
        sender=os.getenv("NOTIFY_FROM", ""),
        recipient=os.getenv("NOTIFY_TO", ""),
        console_url=os.getenv("CONSOLE_URL", "").rstrip("/"),
        signing_key=os.getenv("CONSOLE_WRITE_TOKEN", ""),
    )


# --------------------------------------------------------------------------- #
# Signed review links
# --------------------------------------------------------------------------- #

def sign(finding_id: str, key: str, *, ttl_hours: int = LINK_TTL_HOURS) -> str:
    """A link token that authenticates a reader for one specific finding.

    Scoped to one finding rather than granting console-wide write, so a
    forwarded or leaked email cannot decide anything else.
    """
    expires = int((datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).timestamp())
    payload = f"{finding_id}|{expires}"
    digest = hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest()[:16]
    raw = f"{payload}|{base64.urlsafe_b64encode(digest).decode().rstrip('=')}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def verify(token: str, key: str) -> str | None:
    """Return the finding id a token is good for, or ``None``."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        finding_id, expires, signature = raw.rsplit("|", 2)
    except Exception:
        return None

    if int(expires) < datetime.now(timezone.utc).timestamp():
        return None

    expected = hmac.new(
        key.encode(), f"{finding_id}|{expires}".encode(), hashlib.sha256
    ).digest()[:16]
    expected_b64 = base64.urlsafe_b64encode(expected).decode().rstrip("=")
    if not hmac.compare_digest(signature, expected_b64):
        return None
    return finding_id


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #

# The brand, inherited from the console and the creatives rather than invented
# here: one accent, hierarchy by opacity. Every value is a solid hex -- rgba()
# and CSS variables are unreliable across mail clients, so the blends are
# pre-computed against the stage colour instead.
STAGE = "#0A0C0E"    # page
LIFT = "#12161A"     # card
LIFT2 = "#171D22"    # a block inside a card
INK = "#F5F7F9"      # primary text
INK2 = "#9BA6AD"     # secondary
INK3 = "#6D7880"     # labels, furniture
LINE = "#1F262C"
ACCENT = "#5AC8E8"
ACCENT_WASH = "#12262C"  # accent at ~8% over the lift colour
ACCENT_DEEP = "#062730"  # text on an accent fill

FONT = (
    "-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',"
    "Helvetica,Arial,sans-serif"
)

STYLE_BODY = (
    f"margin:0;padding:0;background:{STAGE};font-family:{FONT};"
    f"color:{INK};line-height:1.55;-webkit-font-smoothing:antialiased;"
)
STYLE_CARD = (
    f"max-width:600px;margin:0 auto;background:{LIFT};border:1px solid {LINE};"
    "border-radius:14px;padding:34px 32px;"
)
STYLE_BUTTON = (
    "display:inline-block;padding:14px 28px;border-radius:9px;"
    "font-size:15px;font-weight:600;text-decoration:none;letter-spacing:.01em;"
)
STYLE_MUTED = f"color:{INK2};font-size:13px;line-height:1.5;"
STYLE_LABEL = (
    f"color:{INK3};font-size:11px;letter-spacing:.16em;text-transform:uppercase;"
    "font-weight:600;"
)


def _shell(inner: str) -> str:
    """The dark stage every message sits on.

    Mail clients disagree about what a bare ``<body>`` background means, so the
    stage colour is painted on a full-width table as well -- otherwise a dark
    card lands on a white page in exactly the clients least likely to be
    forgiving about it.
    """
    return (
        f'<body style="{STYLE_BODY}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{STAGE};padding:28px 14px;"><tr><td>'
        f"{inner}"
        f"</td></tr></table></body>"
    )


def _escape(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


#: How an audit verdict reads in the email. The point of showing it is that a
#: reviewer should never approve without knowing an independent model had
#: reservations -- so CONCERNS and DEFECT are stated plainly, not softened.
#:
#: Severity is carried by the weight of the rule and the words, not by hue: the
#: house rule is no red/amber/green, and a reader who is colourblind or reading
#: in a client that mangles colour still has to get the same message.
_VERDICT_COPY = {
    "clean": ("1px", "Independent review found nothing to raise."),
    "concerns": ("3px", "Independent review raised concerns. Read them before deciding."),
    "defect": ("5px", "Independent review found a defect. This should not be merged as written."),
}


def decision_email(
    finding: Finding,
    appraisals: dict[str, Appraisal],
    papers: dict[str, Paper],
    config: MailConfig,
    *,
    verdict: str = "",
    audit_summary: str = "",
) -> tuple[str, str]:
    """Subject and HTML for "something needs deciding"."""
    rows = [
        (appraisals[pid], papers[pid])
        for pid in finding.supporting_paper_ids
        if pid in appraisals and pid in papers
    ]
    rows.sort(key=lambda r: (r[0].tier.value, -(r[0].sample_size or 0)))
    strongest = rows[0] if rows else None
    tiers = ", ".join(f"{n}×{t}" for t, n in sorted(finding.tier_counts.items()))

    change = ""
    if finding.proposed_changes:
        c = finding.proposed_changes[0]
        change = (
            f'<p style="{STYLE_LABEL}margin:0 0 8px;">Proposed</p>'
            f'<p style="margin:0 0 24px;font-family:ui-monospace,Menlo,monospace;'
            f'font-size:15px;color:{INK};background:{LIFT2};border:1px solid {LINE};'
            f'padding:14px 16px;border-radius:8px;">'
            f'{_escape(c.symbol)}: {_escape(c.current_value)} → '
            f'<strong style="color:{ACCENT};">{_escape(c.proposed_value)}</strong></p>'
        )

    lead = ""
    if strongest:
        appraisal, paper = strongest
        size = f", n={appraisal.sample_size:,}" if appraisal.sample_size else ""
        lead = (
            f'<p style="{STYLE_LABEL}margin:0 0 8px;">Strongest study</p>'
            f'<p style="margin:0 0 24px;font-size:15px;color:{INK};">'
            f'<a href="{_escape(paper.url)}" style="color:{INK};text-decoration:none;'
            f'border-bottom:1px solid {LINE};">'
            f'{_escape(paper.title[:110])}</a><br>'
            f'<span style="{STYLE_MUTED}">Tier {appraisal.tier.value} · '
            f'{_escape(appraisal.design)}{size}</span></p>'
        )

    audit = ""
    if verdict:
        rule, headline = _VERDICT_COPY.get(
            verdict.lower(), ("1px", "Independent review completed.")
        )
        audit = (
            f'<div style="margin:0 0 24px;padding:16px 18px;border-radius:8px;'
            f'background:{LIFT2};border-left:{rule} solid {ACCENT};">'
            f'<p style="margin:0 0 6px;{STYLE_LABEL}color:{ACCENT};">'
            f'Opus · {_escape(verdict.upper())}</p>'
            f'<p style="margin:0;font-size:14px;color:{INK2};">{_escape(headline)}'
            f'{" " + _escape(audit_summary) if audit_summary else ""}</p></div>'
        )

    token = sign(finding.finding_id, config.signing_key)
    review_url = f"{config.console_url}/review/{token}"

    html = _shell(f"""<div style="{STYLE_CARD}">
  <p style="margin:0 0 10px;{STYLE_LABEL}color:{ACCENT};">
    Provenance · {_escape(finding.component_id.upper())}</p>
  <h1 style="margin:0 0 20px;font-size:24px;line-height:1.3;font-weight:600;
    letter-spacing:-.01em;color:{INK};">
    {_escape(finding.statement[:180])}</h1>

  {audit}

  {change}

  <p style="{STYLE_LABEL}margin:0 0 8px;">Currently</p>
  <p style="margin:0 0 24px;font-size:14px;color:{INK2};">
    {_escape(finding.current_behavior[:260])}</p>

  {lead}

  <p style="margin:0 0 28px;font-size:14px;color:{INK2};">
    <strong style="color:{INK};">{len(rows)} studies</strong> ({_escape(tiers)}) ·
    confidence {finding.confidence:.2f}. Every quoted claim was checked
    verbatim against its source.</p>

  <a href="{_escape(review_url)}"
     style="{STYLE_BUTTON}background:{ACCENT};color:{ACCENT_DEEP};">Review and decide →</a>

  <p style="{STYLE_MUTED}margin:26px 0 0;color:{INK3};">
    The link opens the proposal with the evidence and the argument against it.
    Nothing is decided by opening it.
    {f'<br><a href="{_escape(finding.pr_url)}" style="color:{INK2};">See the pull request</a>' if finding.pr_url else ''}
  </p>
</div>""")

    subject = f"Provenance: {finding.component_id} — {len(rows)} studies disagree with a current value"
    return subject, html


#: Tier and alignment are the two facts that decide whether a paper matters.
#: They are separated by weight and fill, never by hue -- the house rule is one
#: accent, and a traffic-light palette would also be the first thing to fall
#: apart in a client that rewrites colours for dark mode.
#:
#: The second string is the tier in words. "Tier B" means nothing to a reader
#: who has not read the rubric, and the rubric is not in the email.
_TIER_COPY = {
    "A": (True, "randomised trials, or a review of them"),
    "B": (True, "a trial, or a large cohort followed for years"),
    "C": (False, "smaller, shorter, or a stand-in measure"),
    "D": (False, "lab, animal, or uncontrolled work"),
}
_ALIGN_COPY = {
    "supports": (False, "agrees with our rule"),
    "challenges": (True, "argues against our rule"),
    "extends": (False, "covers ground our rule ignores"),
    "neutral": (False, "neither way"),
}

#: How the alignment reads inside a sentence, rather than on a chip.
_ALIGN_VERB = {
    "supports": "backs up",
    "challenges": "argues against",
    "extends": "covers ground missing from",
    "neutral": "bears on",
}


def _first_sentence(text: str, limit: int = 170) -> str:
    """The synthesist writes paragraphs; a briefing line needs one sentence."""
    clean = " ".join(str(text or "").split())
    cut = clean.find(". ")
    if 0 < cut < limit:
        return clean[: cut + 1]
    return clean[:limit].rstrip(" ,;") + ("\u2026" if len(clean) > limit else "")


def _stat(label: str, value: str, *, emphasis: bool = False) -> str:
    """One number in the strip across the top."""
    size = "30px" if emphasis else "24px"
    colour = INK if emphasis else INK2
    return (
        f'<td style="padding:0 22px 0 0;vertical-align:top;">'
        f'<div style="font-size:{size};font-weight:700;color:{colour};'
        f'line-height:1.1;letter-spacing:-.02em;'
        f'font-variant-numeric:tabular-nums;">{_escape(value)}</div>'
        f'<div style="{STYLE_LABEL}margin-top:6px;">{_escape(label)}</div>'
        f"</td>"
    )


def _heading(title: str, count: str = "") -> str:
    """A section rule. The count sits with the title so the section is scannable
    without reading anything under it."""
    tail = (
        f'<span style="color:{INK3};font-weight:400;letter-spacing:.1em;"> · '
        f"{_escape(count)}</span>" if count else ""
    )
    return (
        f'<div style="margin:30px 0 14px;padding-top:22px;'
        f'border-top:1px solid {LINE};{STYLE_LABEL}color:{INK2};">'
        f"{_escape(title)}{tail}</div>"
    )


#: Reason codes are written for the rejection log, which a person does not read.
#: In an email they have to say what happened.
_REJECT_COPY = {
    "not_relevant": "did not bear on any rule we watch",
    "no_abstract": "no abstract to read",
    "no_appraisal": "could not be graded",
    "unappraisable_type": "not a study we can grade",
    "no_quantitative_result": "no number in it to act on",
    "ungrounded_claim": "a quoted number was not in the source",
    "no_grounded_claims": "nothing in it survived the quote check",
    "single_source": "only one study says it",
    "insufficient_convergence": "the studies do not yet agree",
    "no_strong_evidence": "nothing strong enough to act on",
    "no_change_proposed": "read, but implies no change",
    "pillar_collision": "would fight a change already proposed",
    "deferred_for_capacity": "held back for a quieter night",
    "settled_by_reviewer": "you have already decided this one",
}


def _chip(text: str, *, strong: bool) -> str:
    """A one-fact label. Filled only when it is the fact that decides."""
    style = (
        f"background:{ACCENT_WASH};color:{ACCENT};border:1px solid #1D4A57;"
        if strong else f"background:transparent;color:{INK3};border:1px solid {LINE};"
    )
    return (
        f'<span style="display:inline-block;padding:4px 10px;border-radius:20px;'
        f'font-size:11.5px;font-weight:600;letter-spacing:.02em;'
        f'margin:0 6px 6px 0;{style}">{text}</span>'
    )


def _why_kept(appraisal: Appraisal, components: dict[str, str] | None = None) -> str:
    """Why this paper survived, assembled from what actually decided it.

    Written by code, not by a model, on purpose. Keeping a paper is not a
    judgement made in prose: it is the record of three checks that already
    happened -- it bears on a named rule, it was gradable against the rubric,
    and its numbers were found verbatim in the source. A model asked to explain
    the decision afterwards is free to write a better reason than the one that
    was applied, which is precisely the failure this project exists to avoid.
    """
    names = [
        (components or {}).get(cid, cid.replace("_", " "))
        for cid in appraisal.component_ids
    ]
    if not names:
        rule = "a rule the score is built on"
    elif len(names) == 1:
        rule = f"the {names[0]} rule"
    elif len(names) == 2:
        rule = f"the {names[0]} and {names[1]} rules"
    else:
        rule = f"the {names[0]} rule, among others"

    verb = _ALIGN_VERB.get(appraisal.alignment.value, "bears on")

    design = (appraisal.design or "").strip().rstrip(".")
    detail = (design[0].upper() + design[1:]) if design else "Study"
    if appraisal.sample_size:
        detail += f" of {appraisal.sample_size:,} people"
    if appraisal.follow_up:
        detail += f", followed {appraisal.follow_up.strip().rstrip('.')}"

    count = len(appraisal.claims)
    if count == 1:
        checked = "its headline number was found word-for-word in the abstract"
    elif count == 2:
        checked = "both of its headline numbers were found word-for-word in the abstract"
    else:
        checked = (
            f"all {count} of its headline numbers were found word-for-word "
            "in the abstract"
        )
    return f"It {verb} {rule}. {detail}, and {checked}."


def _plain_line(appraisal: Appraisal) -> str:
    """The one sentence a non-specialist actually reads.

    Falls back to the plain-language claim statement, which is all a record
    appraised before ``plain_summary`` existed has to offer. A briefing that
    rendered nothing for those would look broken rather than honest.
    """
    if appraisal.plain_summary.strip():
        return appraisal.plain_summary.strip()
    if appraisal.claims:
        return _first_sentence(appraisal.claims[0].statement, limit=200)
    return ""


def _paper_block(
    paper: Paper | None,
    appraisal: Appraisal,
    *,
    index: int = 0,
    components: dict[str, str] | None = None,
) -> str:
    """One appraised paper: what it found, why it was kept, and the proof.

    Top to bottom that is plain English first, then the reason it survived,
    then the verbatim span the grounding check verified. The quote stays --
    it is the evidence, and a summary of a summary is how a briefing becomes
    something you stop reading -- but it now sits underneath a sentence that
    can be understood without it.
    """
    title = _escape(paper.title if paper else appraisal.paper_id)
    journal = _escape(paper.journal if paper else "")
    tier_strong, tier_text = _TIER_COPY.get(appraisal.tier.value, (False, "ungraded"))
    align_strong, align_text = _ALIGN_COPY.get(
        appraisal.alignment.value, (False, "neither way")
    )

    meta = " · ".join(
        bit for bit in (
            journal,
            f"n={appraisal.sample_size:,}" if appraisal.sample_size else "",
            _escape(appraisal.follow_up),
        ) if bit
    )

    chips = (
        _chip(f"Tier {_escape(appraisal.tier.value)} · {tier_text}", strong=tier_strong)
        + _chip(align_text, strong=align_strong)
    )

    plain = _plain_line(appraisal)
    summary = (
        f'<div style="font-size:17px;line-height:1.45;color:{INK};'
        f'margin:10px 0 12px;letter-spacing:-.005em;">{_escape(plain)}</div>'
        if plain else ""
    )

    why = (
        f'<div style="margin:0 0 14px;padding:12px 14px;background:{ACCENT_WASH};'
        f'border-left:2px solid {ACCENT};border-radius:0 6px 6px 0;">'
        f'<div style="{STYLE_LABEL}color:{ACCENT};margin:0 0 5px;">Why it was kept</div>'
        f'<div style="font-size:13.5px;line-height:1.5;color:{INK2};">'
        f"{_escape(_why_kept(appraisal, components))}</div></div>"
    )

    claims = ""
    for claim in appraisal.claims[:2]:
        # When the summary above IS this claim -- which is what a record
        # appraised before ``plain_summary`` existed falls back to -- printing
        # it again reads as a rendering bug rather than as emphasis.
        statement = "" if claim.statement.strip() == plain.strip() else (
            f'<div style="font-size:13.5px;color:{INK2};line-height:1.5;margin:0 0 8px;">'
            f"{_escape(claim.statement)}</div>"
        )
        figure = ""
        if claim.value is not None:
            # "to", not an en dash: a negative bound turns a dash range into
            # "-28.27--3.17", which reads as a typo rather than an interval.
            ci = (
                f" (95% CI {claim.ci_low:g} to {claim.ci_high:g})"
                if claim.ci_low is not None and claim.ci_high is not None else ""
            )
            unit = _escape(claim.unit)
            # "%" and friends sit tight against the figure; a word does not.
            spacer = "" if (not unit or unit[0] in "%\u00b0/") else " "
            figure = (
                f'<div style="font-family:ui-monospace,Menlo,monospace;font-size:15px;'
                f'font-weight:700;color:{ACCENT};margin:0 0 6px;'
                f'font-variant-numeric:tabular-nums;">'
                f"{claim.value:g}{spacer}{unit}"
                f'<span style="color:{INK3};font-weight:400;font-size:13px;">{ci}</span>'
                f"</div>"
            )
        claims += (
            f'<div style="margin:0 0 10px;padding:12px 14px;background:{STAGE};'
            f'border:1px solid {LINE};border-radius:8px;">'
            f"{figure}{statement}"
            f'<div style="font-size:13px;color:{INK3};font-style:italic;line-height:1.5;">'
            f"\u201c{_escape(claim.quote)}\u201d</div>"
            f"</div>"
        )
    if claims:
        claims = (
            f'<div style="{STYLE_LABEL}margin:0 0 8px;">Checked against the source</div>'
            + claims
        )

    link = (
        f'<div style="margin-top:12px;"><a href="{_escape(paper.url)}" '
        f'style="color:{ACCENT};font-size:13px;font-weight:600;text-decoration:none;">'
        f"Read the paper \u2192</a></div>"
        if paper and paper.url else ""
    )

    return (
        f'<div style="margin:0 0 14px;padding:20px 22px;background:{LIFT2};'
        f'border:1px solid {LINE};border-radius:12px;">'
        f'<div style="{STYLE_LABEL}margin:0 0 10px;">Study {index:02d}</div>'
        f"{chips}{summary}"
        f'<div style="font-size:13.5px;color:{INK2};line-height:1.45;margin:0 0 3px;">'
        f"{title}</div>"
        f'<div style="{STYLE_MUTED}color:{INK3};margin:0 0 14px;">{meta}</div>'
        f"{why}{claims}{link}</div>"
    )


def briefing_email(
    run: dict,
    appraised: list[tuple[Paper | None, Appraisal]],
    rejected: list[Rejection],
    open_findings: list[Finding],
    config: MailConfig,
    *,
    components: dict[str, str] | None = None,
) -> tuple[str, str]:
    """The morning briefing: what was read last night, and what it amounted to.

    ``components`` maps component ids to the names a person uses -- ``mvpa`` to
    "Cardio". Optional, because the briefing must still render from stored
    records alone, but without it the reader is told a paper bears on "mvpa",
    which is the sort of detail that makes a report feel like a log file.

    This is deliberately NOT a decision email. Nothing here has a button and
    nothing here is asking for approval -- a proposal still has to be written
    and independently audited before it earns that. This exists because a
    system that only speaks when it wants something is indistinguishable, on a
    quiet morning, from a system that has silently died.

    The subject line carries the verdict, so a glance at the inbox is usually
    the whole interaction.
    """
    new_findings = run.get("findings_new", 0) or 0
    read = run.get("retrieved_new", 0) or 0
    kept = run.get("appraised", 0) or 0

    if new_findings:
        headline = f"{new_findings} new finding{'s' if new_findings > 1 else ''}"
        lede = (
            "Evidence converged on a rule in the algorithm. Nothing has been "
            "written or reviewed yet \u2014 run <code>/provenance</code> to draft "
            "the change and have it audited."
        )
    elif kept:
        headline = f"{kept} paper{'s' if kept > 1 else ''} kept, nothing to propose"
        lede = (
            "Worth reading, but not enough to move a constant. Evidence has to "
            "converge across studies before a proposal is opened."
        )
    elif read:
        headline = "Nothing survived triage"
        lede = "Papers came back, none of them bore on the rules being watched."
    else:
        headline = "Nothing new to read"
        lede = "No papers published in the window that the agenda had not already seen."

    date_line = datetime.now(timezone.utc).strftime("%A %d %B")

    stats = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:0;padding:18px 20px;background:{LIFT2};'
        f'border:1px solid {LINE};border-radius:12px;"><tr>'
        + _stat("read", str(read), emphasis=True)
        + _stat("kept", str(kept), emphasis=True)
        + _stat("thrown out", str(len(rejected)), emphasis=True)
        + _stat("seen before", str(run.get("already_seen", 0) or 0))
        + "</tr></table>"
    )

    # Strongest evidence first, and within a tier the papers that argue against
    # a current rule -- that ordering is the reader's attention budget spent on
    # the two things that could actually change the algorithm.
    ranked = sorted(
        appraised,
        key=lambda pair: (
            pair[1].tier.value,
            0 if pair[1].alignment.value == "challenges" else 1,
            -(pair[1].sample_size or 0),
        ),
    )
    papers_html = "".join(
        _paper_block(paper, a, index=i, components=components)
        for i, (paper, a) in enumerate(ranked[:5], start=1)
    )
    if papers_html:
        more = len(ranked) - 5
        papers_html = (
            _heading("What it kept", f"{len(ranked)} studies" if len(ranked) > 1 else "")
            + papers_html
            + (f'<p style="{STYLE_MUTED}color:{INK3};margin:0 0 4px;">'
               f"And {more} more in the console.</p>" if more > 0 else "")
        )

    # The papers whose data could be SHOWN, not just cited. A sweep reel needs
    # a curve to travel -- risk falling as the dose climbs -- and that shape is
    # rare enough that a night which lands one is worth flagging by name. This
    # is the supply line for the next 10k-steps reel; the tier floor still
    # applies, because a reel is a publication.
    from . import content as _content

    sweepables = [
        (paper, appraisal, signals)
        for paper, appraisal in appraised
        if appraisal.tier in _content.PUBLISHABLE_TIERS
        and (signals := _content.sweep_signals(appraisal))
    ]
    sweep_html = ""
    if sweepables:
        rows = "".join(
            f'<li style="margin:0 0 12px;font-size:14px;color:{INK};line-height:1.5;">'
            f"<strong>{_escape((paper.title if paper else appraisal.paper_id)[:110])}</strong>"
            f'<br><span style="{STYLE_MUTED}color:{INK2};">'
            f"{_escape(_plain_line(appraisal))}</span>"
            f'<br><span style="{STYLE_MUTED}color:{INK3};">'
            f"Tier {appraisal.tier.value}"
            + (f" · n={appraisal.sample_size:,}" if appraisal.sample_size else "")
            + f" · curve markers: {_escape(', '.join(signals[:3]))}</span></li>"
            for paper, appraisal, signals in sweepables[:3]
        )
        sweep_html = (
            _heading("Reel-ready", f"{len(sweepables)} sweep-shaped")
            + f'<ul style="margin:0;padding-left:18px;">{rows}</ul>'
            + f'<p style="{STYLE_MUTED}color:{INK3};margin:0 0 4px;">'
            f"Dose-response data that can be animated the way the 10k-steps "
            f"reel was — the number arrives with the motion. Run "
            f"<code>/social</code> (or <code>python -m provenance content "
            f"--sweepable</code>) to see the ranked queue.</p>"
        )

    # The rejections are the credibility of the whole thing: anything can
    # produce findings, the number worth showing is what was refused.
    reasons = Counter(r.reason_code for r in rejected)
    rejects_html = ""
    if reasons:
        rows = "".join(
            f'<tr><td style="{STYLE_MUTED}color:{INK2};padding:7px 0;'
            f'border-bottom:1px solid {LINE};">'
            f'{_escape(_REJECT_COPY.get(code, code.replace("_", " ")))}</td>'
            f'<td style="{STYLE_MUTED}color:{INK};font-weight:700;text-align:right;'
            f'font-variant-numeric:tabular-nums;padding:7px 0;'
            f'border-bottom:1px solid {LINE};">{count}</td></tr>'
            for code, count in reasons.most_common(6)
        )
        rejects_html = (
            _heading("What it threw out", f"{sum(reasons.values())} papers")
            + f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
              f'style="width:100%;">{rows}</table>'
        )

    pending_html = ""
    if open_findings:
        items = "".join(
            f'<li style="margin:0 0 12px;font-size:14px;color:{INK};line-height:1.5;">'
            f"<strong>"
            f'{_escape((components or {}).get(f.component_id, f.component_id))}</strong>'
            f" \u2014 {_escape(_first_sentence(f.statement))} "
            f'<span style="{STYLE_MUTED}color:{INK3};">'
            f'({_escape(f.status.value.replace("_", " "))}'
            f'{", " + str(round(f.confidence * 100)) + "% confidence" if f.confidence else ""})'
            f"</span>"
            + (f'<br><a href="{_escape(f.pr_url)}" style="color:{ACCENT};font-size:13px;'
               f'font-weight:600;text-decoration:none;">Open the pull request \u2192</a>'
               if f.pr_url else "")
            + f"</li>"
            for f in open_findings[:5]
        )
        pending_html = (
            _heading("Still on the table", f"{len(open_findings)} open")
            + f'<ul style="margin:0;padding-left:18px;">{items}</ul>'
        )

    gated = run.get("components_gated", 0) or 0
    footer = (
        f'<p style="{STYLE_MUTED}color:{INK3};margin:28px 0 0;padding-top:18px;'
        f'border-top:1px solid {LINE};">'
        f"{gated} component{'s' if gated != 1 else ''} watched and left alone tonight. "
        f"Run finished in {run.get('seconds', 0):.0f}s against "
        f"{_escape(run.get('algorithm_version', ''))}."
        f"<br>No approvals are requested in this email."
        + (f'<br><a href="{_escape(config.console_url)}" style="color:{INK2};">'
           f"Open the console</a>" if config.console_url else "")
        + "</p>"
    )

    html = _shell(
        f'<div style="{STYLE_CARD}">'
        f'<p style="{STYLE_LABEL}color:{ACCENT};margin:0 0 6px;">'
        f"Provenance \u00b7 Morning briefing</p>"
        f'<p style="{STYLE_MUTED}color:{INK3};margin:0 0 14px;">{_escape(date_line)}</p>'
        f'<h1 style="font-size:26px;line-height:1.22;margin:0 0 12px;color:{INK};'
        f'font-weight:600;letter-spacing:-.02em;">{_escape(headline)}</h1>'
        f'<p style="font-size:15px;line-height:1.55;color:{INK2};margin:0 0 24px;">'
        f"{lede}</p>"
        f"{stats}{sweep_html}{papers_html}{rejects_html}{pending_html}{footer}"
        f"</div>"
    )
    return (f"Provenance \u2014 {headline}", html)


def digest_email(summary: dict, pending: list[Finding], config: MailConfig) -> tuple[str, str]:
    """Subject and HTML for the weekly note.

    The rejections are the point. Anyone can build something that produces
    findings; the number worth showing is how much was read and thrown away.
    """
    read = summary.get("papers_read", 0)
    rejected = summary.get("rejected_total", 0)
    reasons = summary.get("reasons", {})

    reason_rows = "".join(
        f'<tr><td style="padding:9px 0;font-size:14px;color:{INK2};'
        f'border-bottom:1px solid {LINE};">'
        f'{_escape(_REJECT_COPY.get(k, k.replace("_", " ")))}</td>'
        f'<td style="padding:9px 0;font-size:14px;text-align:right;color:{INK};'
        f'font-weight:700;font-variant-numeric:tabular-nums;'
        f'border-bottom:1px solid {LINE};">{v:,}</td></tr>'
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:6]
    )

    pending_block = ""
    if pending:
        items = "".join(
            f'<li style="margin:0 0 10px;font-size:14px;color:{INK};line-height:1.5;">'
            f'<strong>{_escape(f.component_id)}</strong> — '
            f'<span style="color:{INK2};">{_escape(f.statement[:110])}</span>'
            f'{f" · <a href=\"{_escape(f.pr_url)}\" style=\"color:{ACCENT};text-decoration:none;font-weight:600;\">PR</a>" if f.pr_url else ""}'
            f'</li>'
            for f in pending
        )
        pending_block = (
            _heading("Waiting on you", f"{len(pending)} open")
            + f'<ul style="margin:0;padding-left:20px;">{items}</ul>'
        )
    else:
        pending_block = (
            f'<p style="margin:28px 0 0;font-size:14px;color:{INK2};">'
            f'Nothing is waiting on you.</p>'
        )

    html = _shell(f"""<div style="{STYLE_CARD}">
  <p style="margin:0 0 12px;{STYLE_LABEL}color:{ACCENT};">
    Provenance · Week in review</p>
  <h1 style="margin:0 0 24px;font-size:26px;line-height:1.25;font-weight:600;
    letter-spacing:-.02em;color:{INK};">
    {read:,} papers read.<br>{rejected:,} refused.</h1>

  <div style="{STYLE_LABEL}margin:0 0 4px;">Why things were refused</div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"
    style="width:100%;border-collapse:collapse;margin:0;">{reason_rows}</table>

  {pending_block}

  <p style="{STYLE_MUTED}color:{INK3};margin:30px 0 0;padding-top:18px;
    border-top:1px solid {LINE};">
    This is the only scheduled message. Everything else arrives because a
    proposal is waiting.
    {f'<br><a href="{_escape(config.console_url)}" style="color:{INK2};">Open the console</a>' if config.console_url else ''}
  </p>
</div>""")

    subject = f"Provenance: {read:,} read, {len(pending)} waiting on you"
    return subject, html


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #

def send(subject: str, html: str, config: MailConfig | None = None) -> str | None:
    """Send one email. Returns the id, or ``None`` when not configured."""
    config = config or mail_config()
    if not config.configured:
        log.info("notify: email not configured; would have sent %r", subject)
        return None

    response = httpx.post(
        RESEND_ENDPOINT,
        headers={"Authorization": f"Bearer {config.api_key}"},
        json={
            "from": config.sender,
            "to": [config.recipient],
            "subject": subject,
            "html": html,
        },
        timeout=30.0,
    )
    if response.status_code >= 400:
        log.warning("notify: send failed %s: %s", response.status_code, response.text[:200])
        return None
    return response.json().get("id")
