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

from .models import Appraisal, Finding, Paper

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


def decision_email(
    finding: Finding,
    appraisals: dict[str, Appraisal],
    papers: dict[str, Paper],
    config: MailConfig,
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

    token = sign(finding.finding_id, config.signing_key)
    review_url = f"{config.console_url}/review/{token}"

    html = f"""<body style="{STYLE_BODY}">
<div style="{STYLE_CARD}">
  <p style="margin:0 0 6px;font-size:12px;letter-spacing:.14em;color:#1F7F9C;">
    PROVENANCE · {_escape(finding.component_id.upper())}</p>
  <h1 style="margin:0 0 18px;font-size:23px;line-height:1.3;font-weight:600;">
    {_escape(finding.statement[:180])}</h1>

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
