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

STYLE_BODY = (
    "margin:0;padding:0;background:#F4F6F8;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;"
    "color:#101820;line-height:1.55;"
)
STYLE_CARD = (
    "max-width:560px;margin:32px auto;background:#FFFFFF;border:1px solid #DCE3E8;"
    "border-radius:10px;padding:32px 30px;"
)
STYLE_BUTTON = (
    "display:inline-block;padding:13px 26px;border-radius:8px;"
    "font-size:15px;font-weight:600;text-decoration:none;"
)
STYLE_MUTED = "color:#77858F;font-size:13px;line-height:1.5;"


def _escape(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


#: How an audit verdict reads in the email. The point of showing it is that a
#: reviewer should never approve without knowing an independent model had
#: reservations -- so CONCERNS and DEFECT are stated plainly, not softened.
_VERDICT_COPY = {
    "clean": ("#1F7F9C", "Independent review found nothing to raise."),
    "concerns": ("#8A6A1F", "Independent review raised concerns. Read them before deciding."),
    "defect": ("#8A2F2F", "Independent review found a defect. This should not be merged as written."),
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
            f'<p style="margin:0 0 6px;font-size:13px;color:#77858F;">PROPOSED</p>'
            f'<p style="margin:0 0 22px;font-family:ui-monospace,Menlo,monospace;'
            f'font-size:15px;background:#EDF1F4;padding:12px 14px;border-radius:6px;">'
            f'{_escape(c.symbol)}: {_escape(c.current_value)} → '
            f'<strong>{_escape(c.proposed_value)}</strong></p>'
        )

    lead = ""
    if strongest:
        appraisal, paper = strongest
        size = f", n={appraisal.sample_size:,}" if appraisal.sample_size else ""
        lead = (
            f'<p style="{STYLE_MUTED}margin:0 0 4px;">STRONGEST STUDY</p>'
            f'<p style="margin:0 0 22px;font-size:14px;">'
            f'<a href="{_escape(paper.url)}" style="color:#1F7F9C;">'
            f'{_escape(paper.title[:110])}</a><br>'
            f'<span style="{STYLE_MUTED}">Tier {appraisal.tier.value} · '
            f'{_escape(appraisal.design)}{size}</span></p>'
        )

    audit = ""
    if verdict:
        colour, headline = _VERDICT_COPY.get(
            verdict.lower(), ("#46545F", "Independent review completed.")
        )
        audit = (
            f'<div style="margin:0 0 22px;padding:14px 16px;border-radius:8px;'
            f'background:#EDF1F4;border-left:3px solid {colour};">'
            f'<p style="margin:0 0 4px;font-size:12px;letter-spacing:.12em;'
            f'color:{colour};font-weight:700;">OPUS · {_escape(verdict.upper())}</p>'
            f'<p style="margin:0;font-size:14px;color:#46545F;">{_escape(headline)}'
            f'{" " + _escape(audit_summary) if audit_summary else ""}</p></div>'
        )

    token = sign(finding.finding_id, config.signing_key)
    review_url = f"{config.console_url}/review/{token}"

    html = f"""<body style="{STYLE_BODY}">
<div style="{STYLE_CARD}">
  <p style="margin:0 0 6px;font-size:12px;letter-spacing:.14em;color:#1F7F9C;">
    PROVENANCE · {_escape(finding.component_id.upper())}</p>
  <h1 style="margin:0 0 18px;font-size:23px;line-height:1.3;font-weight:600;">
    {_escape(finding.statement[:180])}</h1>

  {audit}

  {change}

  <p style="{STYLE_MUTED}margin:0 0 4px;">CURRENTLY</p>
  <p style="margin:0 0 22px;font-size:14px;color:#46545F;">
    {_escape(finding.current_behavior[:260])}</p>

  {lead}

  <p style="margin:0 0 26px;font-size:14px;color:#46545F;">
    <strong>{len(rows)} studies</strong> ({_escape(tiers)}) ·
    confidence {finding.confidence:.2f}. Every quoted claim was checked
    verbatim against its source.</p>

  <a href="{_escape(review_url)}"
     style="{STYLE_BUTTON}background:#1F7F9C;color:#FFFFFF;">Review and decide →</a>

  <p style="{STYLE_MUTED}margin:26px 0 0;">
    The link opens the proposal with the evidence and the argument against it.
    Nothing is decided by opening it.
    {f'<br><a href="{_escape(finding.pr_url)}" style="color:#77858F;">See the pull request</a>' if finding.pr_url else ''}
  </p>
</div>
</body>"""

    subject = f"Provenance: {finding.component_id} — {len(rows)} studies disagree with a current value"
    return subject, html


#: Tier and alignment are the two facts that decide whether a paper matters, so
#: they get colour. Everything else in the briefing is ink on paper.
_TIER_COPY = {
    "A": ("#1F7F9C", "Randomised or systematic"),
    "B": ("#2E7D6B", "Prospective cohort"),
    "C": ("#77858F", "Weaker design"),
}
_ALIGN_COPY = {
    "supports": ("#2E7D6B", "agrees with our rule"),
    "challenges": ("#8A6A1F", "argues against our rule"),
    "neutral": ("#77858F", "neither way"),
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
    size = "26px" if emphasis else "22px"
    colour = "#101820" if emphasis else "#3C4A54"
    return (
        f'<td style="padding:0 16px 0 0;vertical-align:top;">'
        f'<div style="font-size:{size};font-weight:700;color:{colour};'
        f'line-height:1.2;">{_escape(value)}</div>'
        f'<div style="{STYLE_MUTED}margin-top:2px;">{_escape(label)}</div>'
        f"</td>"
    )


def _paper_block(paper: Paper | None, appraisal: Appraisal) -> str:
    """One appraised paper: what it is, how strong, and what it actually said.

    The quote is the whole point. A summary of a summary is how a briefing
    becomes something you stop reading, and the verbatim span is the same one
    the grounding check verified -- so the email shows the evidence rather than
    a paraphrase of it.
    """
    title = _escape(paper.title if paper else appraisal.paper_id)
    journal = _escape(paper.journal if paper else "")
    tier_colour, tier_text = _TIER_COPY.get(appraisal.tier.value, ("#77858F", ""))
    align_colour, align_text = _ALIGN_COPY.get(appraisal.alignment.value, ("#77858F", ""))

    meta = " · ".join(
        bit for bit in (
            journal,
            f"n={appraisal.sample_size:,}" if appraisal.sample_size else "",
            _escape(appraisal.follow_up),
        ) if bit
    )

    chips = (
        f'<span style="display:inline-block;padding:3px 9px;border-radius:20px;'
        f'background:{tier_colour}18;color:{tier_colour};font-size:12px;'
        f'font-weight:700;">Tier {_escape(appraisal.tier.value)} · {tier_text}</span>'
        f'<span style="display:inline-block;padding:3px 9px;border-radius:20px;'
        f'background:{align_colour}18;color:{align_colour};font-size:12px;'
        f'font-weight:700;margin-left:6px;">{align_text}</span>'
    )

    claims = ""
    for claim in appraisal.claims[:2]:
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
                f'<div style="font-family:ui-monospace,Menlo,monospace;font-size:14px;'
                f'font-weight:700;color:#101820;margin:0 0 4px;">'
                f"{claim.value:g}{spacer}{unit}{ci}</div>"
            )
        claims += (
            f'<div style="margin:12px 0 0;padding:10px 12px;background:#F4F6F8;'
            f'border-left:3px solid #1F7F9C;border-radius:4px;">'
            f"{figure}"
            f'<div style="font-size:14px;color:#101820;margin:0 0 6px;">'
            f"{_escape(claim.statement)}</div>"
            f'<div style="{STYLE_MUTED}font-style:italic;">'
            f"\u201c{_escape(claim.quote)}\u201d</div>"
            f"</div>"
        )

    link = (
        f'<div style="margin-top:10px;"><a href="{_escape(paper.url)}" '
        f'style="color:#1F7F9C;font-size:13px;text-decoration:none;">'
        f"Read the paper \u2192</a></div>"
        if paper and paper.url else ""
    )

    return (
        f'<div style="padding:18px 0;border-top:1px solid #E6EBEF;">'
        f'<div style="font-size:16px;font-weight:600;color:#101820;'
        f'line-height:1.4;margin:0 0 6px;">{title}</div>'
        f'<div style="{STYLE_MUTED}margin:0 0 10px;">{meta}</div>'
        f"{chips}{claims}{link}</div>"
    )


def briefing_email(
    run: dict,
    appraised: list[tuple[Paper | None, Appraisal]],
    rejected: list[Rejection],
    open_findings: list[Finding],
    config: MailConfig,
) -> tuple[str, str]:
    """The morning briefing: what was read last night, and what it amounted to.

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
        f'<table cellpadding="0" cellspacing="0" style="margin:0 0 4px;"><tr>'
        + _stat("read", str(read), emphasis=True)
        + _stat("kept", str(kept), emphasis=True)
        + _stat("thrown out", str(len(rejected)), emphasis=True)
        + _stat("seen before", str(run.get("already_seen", 0) or 0))
        + "</tr></table>"
    )

    papers_html = "".join(_paper_block(paper, a) for paper, a in appraised[:5])
    if papers_html:
        papers_html = (
            '<h2 style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;'
            'color:#77858F;margin:26px 0 0;">What it kept</h2>' + papers_html
        )

    # The rejections are the credibility of the whole thing: anything can
    # produce findings, the number worth showing is what was refused.
    reasons = Counter(r.reason_code for r in rejected)
    rejects_html = ""
    if reasons:
        rows = "".join(
            f'<tr><td style="{STYLE_MUTED}padding:3px 12px 3px 0;">'
            f'{_escape(code.replace("_", " "))}</td>'
            f'<td style="{STYLE_MUTED}font-weight:700;color:#3C4A54;">{count}</td></tr>'
            for code, count in reasons.most_common(6)
        )
        rejects_html = (
            '<h2 style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;'
            'color:#77858F;margin:26px 0 8px;">What it threw out</h2>'
            f'<table cellpadding="0" cellspacing="0">{rows}</table>'
        )

    pending_html = ""
    if open_findings:
        items = "".join(
            f'<li style="margin:0 0 6px;font-size:14px;color:#101820;">'
            f"<strong>{_escape(f.component_id)}</strong> \u2014 "
            f"{_escape(_first_sentence(f.statement))} "
            f'<span style="{STYLE_MUTED}">'
            f'({_escape(f.status.value.replace("_", " "))}'
            f'{", " + str(round(f.confidence * 100)) + "% confidence" if f.confidence else ""})'
            f"</span>"
            + (f'<br><a href="{_escape(f.pr_url)}" style="color:#1F7F9C;font-size:13px;'
               f'text-decoration:none;">Open the pull request \u2192</a>' if f.pr_url else "")
            + f"</li>"
            for f in open_findings[:5]
        )
        pending_html = (
            '<h2 style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;'
            'color:#77858F;margin:26px 0 8px;">Still on the table</h2>'
            f'<ul style="margin:0;padding-left:18px;">{items}</ul>'
        )

    gated = run.get("components_gated", 0) or 0
    footer = (
        f'<p style="{STYLE_MUTED}margin:26px 0 0;padding-top:16px;'
        f'border-top:1px solid #E6EBEF;">'
        f"{gated} component{'s' if gated != 1 else ''} watched and left alone tonight. "
        f"Run finished in {run.get('seconds', 0):.0f}s against "
        f"{_escape(run.get('algorithm_version', ''))}."
        f"<br>No approvals are requested in this email.</p>"
    )

    html = (
        f'<body style="{STYLE_BODY}"><div style="{STYLE_CARD}">'
        f'<div style="{STYLE_MUTED}margin:0 0 4px;">{_escape(date_line)}</div>'
        f'<h1 style="font-size:23px;line-height:1.25;margin:0 0 10px;color:#101820;">'
        f"{_escape(headline)}</h1>"
        f'<p style="font-size:15px;color:#3C4A54;margin:0 0 22px;">{lede}</p>'
        f"{stats}{papers_html}{rejects_html}{pending_html}{footer}"
        f"</div></body>"
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
        f'<tr><td style="padding:6px 0;font-size:14px;color:#46545F;">'
        f'{_escape(k.replace("_", " "))}</td>'
        f'<td style="padding:6px 0;font-size:14px;text-align:right;'
        f'font-variant-numeric:tabular-nums;">{v:,}</td></tr>'
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:6]
    )

    pending_block = ""
    if pending:
        items = "".join(
            f'<li style="margin:0 0 8px;font-size:14px;">'
            f'<strong>{_escape(f.component_id)}</strong> — '
            f'{_escape(f.statement[:110])}'
            f'{f" · <a href=\"{_escape(f.pr_url)}\" style=\"color:#1F7F9C;\">PR</a>" if f.pr_url else ""}'
            f'</li>'
            for f in pending
        )
        pending_block = (
            f'<p style="{STYLE_MUTED}margin:26px 0 8px;">WAITING ON YOU</p>'
            f'<ul style="margin:0;padding-left:20px;">{items}</ul>'
        )
    else:
        pending_block = (
            f'<p style="margin:26px 0 0;font-size:14px;color:#46545F;">'
            f'Nothing is waiting on you.</p>'
        )

    html = f"""<body style="{STYLE_BODY}">
<div style="{STYLE_CARD}">
  <p style="margin:0 0 6px;font-size:12px;letter-spacing:.14em;color:#1F7F9C;">
    PROVENANCE · WEEK IN REVIEW</p>
  <h1 style="margin:0 0 20px;font-size:23px;line-height:1.3;font-weight:600;">
    {read:,} papers read. {rejected:,} refused.</h1>

  <p style="margin:0 0 6px;{STYLE_MUTED}">WHY THINGS WERE REFUSED</p>
  <table style="width:100%;border-collapse:collapse;margin:0 0 8px;">{reason_rows}</table>

  {pending_block}

  <p style="{STYLE_MUTED}margin:28px 0 0;">
    This is the only scheduled message. Everything else arrives because a
    proposal is waiting.
    {f'<br><a href="{_escape(config.console_url)}" style="color:#77858F;">Open the console</a>' if config.console_url else ''}
  </p>
</div>
</body>"""

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
