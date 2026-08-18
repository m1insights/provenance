"""Review console -- the human gate, and the only place anything is approved.

Two things happen here that happen nowhere else in the system:

1. **A person decides.** Every draft pull request and every creative waits for
   an explicit approval. The fleet can propose all night; nothing merges and
   nothing posts without a click here.

2. **A rejection is recorded with a reason**, and that reason is fed back to
   the agents as few-shot guidance on the next run. A system that is told "no"
   and learns nothing from it will make the same proposal tomorrow.

Runs on Cloud Run. Reads and writes the same Firestore collections the fleet
uses, so there is one source of truth rather than a reporting copy.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import hmac

from fastapi import Cookie, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google.cloud import firestore

from provenance import auth
from provenance.config import settings
from provenance.models import (
    Appraisal,
    Finding,
    FindingStatus,
    Paper,
    Rejection,
)
from provenance.store import firestore as store

app = FastAPI(title="Provenance console")

#: Reading is public so the work can be inspected; deciding is not.
#:
#: The decision endpoint does not touch GitHub -- there is no merge path
#: anywhere in this system and a pull request stays a draft regardless. But an
#: unauthenticated POST could still flip a finding status and, worse, write
#: into the rejection log, which is fed back to the Synthesist as guidance on
#: the next run. That is an open channel into what the fleet learns.
#:
#: Unset locally, so development is unhindered; set on Cloud Run.
WRITE_TOKEN = os.getenv("CONSOLE_WRITE_TOKEN", "")


def _may_write(supplied: str | None) -> bool:
    if not WRITE_TOKEN:
        return True
    return bool(supplied) and hmac.compare_digest(supplied, WRITE_TOKEN)

#: Rejection reasons feed back into the next run as guidance, so they are a
#: fixed vocabulary rather than free text -- an agent can act on "the evidence
#: is too weak" and cannot act on "nah".
REJECTION_REASONS = {
    "evidence_too_weak": "The evidence does not support a change of this size",
    "not_generalisable": "The population studied does not match our users",
    "already_correct": "The current value is defensible as it stands",
    "wrong_change": "The finding is real but this is the wrong fix",
    "cohort_overlap": "The supporting studies are not independent enough",
    "tone": "The copy overstates or misreads the finding",
}


def db() -> firestore.Client:
    cfg = settings()
    return firestore.Client(
        project=cfg.gcp_project,
        database=cfg.firestore_database,
        credentials=auth.credentials(cfg.gcp_project),
    )


# --------------------------------------------------------------------------- #
# Rendering. Deliberately server-rendered: the console is a decision surface,
# not an application, and a build step here would be pure ceremony.
# --------------------------------------------------------------------------- #

STYLE = """
:root{--stage:#0A0C0E;--lift:#12161A;--ink:#F5F7F9;--accent:#5AC8E8;
--line:rgba(245,247,249,.10);--ink2:rgba(245,247,249,.72);
--ink3:rgba(245,247,249,.55);--ink4:rgba(245,247,249,.38)}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--stage);color:var(--ink);font:16px/1.55 -apple-system,
BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;padding:48px 32px 96px}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:28px;letter-spacing:-.02em;margin-bottom:6px}
.sub{color:var(--ink3);font-size:15px;margin-bottom:34px}
.counts{display:flex;gap:26px;margin-bottom:34px;flex-wrap:wrap}
.count{background:var(--lift);border:1px solid var(--line);border-radius:10px;
padding:14px 20px;min-width:120px}
.count b{display:block;font-size:26px;font-variant-numeric:tabular-nums}
.count span{color:var(--ink4);font-size:12px;letter-spacing:.12em;
text-transform:uppercase}
.card{background:var(--lift);border:1px solid var(--line);border-radius:12px;
padding:26px;margin-bottom:22px}
.card h2{font-size:20px;letter-spacing:-.01em;margin-bottom:10px}
.meta{color:var(--ink4);font-size:13px;letter-spacing:.08em;
text-transform:uppercase;margin-bottom:14px}
.stmt{color:var(--ink2);margin-bottom:16px}
.change{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:14px;
background:rgba(90,200,232,.08);border-left:2px solid var(--accent);
padding:10px 14px;margin:12px 0;color:var(--ink2)}
.links a{color:var(--accent);text-decoration:none;margin-right:18px;font-size:14px}
.links a:hover{text-decoration:underline}
details{margin-top:16px}
summary{cursor:pointer;color:var(--ink3);font-size:14px}
table{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);
color:var(--ink2)}
th{color:var(--ink4);font-size:11px;letter-spacing:.1em;text-transform:uppercase}
.tier{display:inline-block;border:1px solid var(--line);border-radius:4px;
padding:1px 7px;font-size:11px;font-weight:700}
form{margin-top:20px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button{font:inherit;font-size:14px;font-weight:600;border-radius:8px;
padding:9px 18px;border:1px solid var(--line);cursor:pointer}
button.approve{background:var(--accent);color:#062730;border-color:var(--accent)}
button.reject{background:transparent;color:var(--ink2)}
select{font:inherit;font-size:14px;background:var(--stage);color:var(--ink2);
border:1px solid var(--line);border-radius:8px;padding:9px 12px}
.divider{color:var(--ink4);font-size:13px;margin:0 4px}
.empty{color:var(--ink4);padding:40px 0;text-align:center}
.warn{color:var(--ink3);font-size:13px;border-left:2px solid var(--line);
padding-left:12px;margin:12px 0}
.status{font-size:12px;letter-spacing:.1em;text-transform:uppercase;
color:var(--ink4)}
"""


def _esc(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _evidence_table(finding: Finding, appraisals, papers) -> str:
    rows = [
        (appraisals[pid], papers[pid])
        for pid in finding.supporting_paper_ids
        if pid in appraisals and pid in papers
    ]
    rows.sort(key=lambda r: (r[0].tier.value, -(r[0].sample_size or 0)))
    body = "".join(
        f"<tr><td><span class='tier'>{a.tier.value}</span></td>"
        f"<td><a href='{_esc(p.url)}' target='_blank'>{_esc(p.title)}</a><br>"
        f"<span style='color:var(--ink4)'>{_esc(p.citation())}</span></td>"
        f"<td>{_esc(a.design)}</td>"
        f"<td style='text-align:right'>{a.sample_size:,}</td></tr>"
        if a.sample_size else
        f"<tr><td><span class='tier'>{a.tier.value}</span></td>"
        f"<td><a href='{_esc(p.url)}' target='_blank'>{_esc(p.title)}</a></td>"
        f"<td>{_esc(a.design)}</td><td style='text-align:right'>—</td></tr>"
        for a, p in rows
    )
    return (
        f"<details><summary>{len(rows)} supporting studies</summary>"
        f"<table><tr><th>Tier</th><th>Study</th><th>Design</th>"
        f"<th style='text-align:right'>n</th></tr>{body}</table></details>"
    )


def _finding_card(finding: Finding, appraisals, papers, *, can_write: bool = True) -> str:
    changes = "".join(
        f"<div class='change'>{_esc(c.file_path)}<br>"
        f"{_esc(c.symbol)}: {_esc(c.current_value)} → {_esc(c.proposed_value)}</div>"
        for c in finding.proposed_changes
    )
    links = []
    if finding.issue_url:
        links.append(f"<a href='{_esc(finding.issue_url)}' target='_blank'>Issue ↗</a>")
    if finding.pr_url:
        links.append(f"<a href='{_esc(finding.pr_url)}' target='_blank'>Draft PR ↗</a>")

    options = "".join(
        f"<option value='{key}'>{_esc(label)}</option>"
        for key, label in REJECTION_REASONS.items()
    )

    tiers = ", ".join(f"{n}×{t}" for t, n in sorted(finding.tier_counts.items()))
    decided = finding.status in {FindingStatus.APPROVED, FindingStatus.REJECTED}

    if not can_write:
        actions = (
            f"<div class='status'>{finding.status.value.replace('_', ' ')}"
            f" · read only</div>"
        )
        return f"""
    <div class="card">
      <div class="meta">{_esc(finding.component_id)} · confidence
        {finding.confidence:.2f} · {_esc(tiers)}</div>
      <h2>{_esc(finding.statement[:160])}</h2>
      <div class="stmt"><b>Currently:</b> {_esc(finding.current_behavior[:300])}</div>
      {changes}
      <div class="links">{" ".join(links)}</div>
      {_evidence_table(finding, appraisals, papers)}
      {actions}
    </div>
    """

    actions = (
        f"<div class='status'>{finding.status.value.replace('_', ' ')}</div>"
        if decided else
        f"<form method='post' action='/decide'>"
        f"<input type='hidden' name='finding_id' value='{_esc(finding.finding_id)}'>"
        f"<button class='approve' name='decision' value='approve'>Approve</button>"
        f"<span class='divider'>or</span>"
        f"<select name='reason'>{options}</select>"
        f"<button class='reject' name='decision' value='reject'>Reject</button>"
        f"</form>"
    )

    return f"""
    <div class="card">
      <div class="meta">{_esc(finding.component_id)} · confidence
        {finding.confidence:.2f} · {_esc(tiers)}</div>
      <h2>{_esc(finding.statement[:160])}</h2>
      <div class="stmt"><b>Currently:</b> {_esc(finding.current_behavior[:300])}</div>
      {changes}
      <div class="links">{" ".join(links)}</div>
      {_evidence_table(finding, appraisals, papers)}
      {actions}
    </div>
    """


@app.get("/", response_class=HTMLResponse)
def index(provenance_write: str | None = Cookie(default=None)) -> str:
    can_write = _may_write(provenance_write)
    client = db()

    findings = sorted(
        (
            Finding.model_validate(doc.to_dict())
            for doc in client.collection(store.FINDINGS).stream()
        ),
        key=lambda f: (f.status is not FindingStatus.OPEN, -f.confidence),
    )
    appraisals = {
        a.paper_id: a
        for doc in client.collection(store.APPRAISALS).stream()
        if (a := Appraisal.model_validate(doc.to_dict()))
    }
    papers = {
        p.doc_id: p
        for doc in client.collection(store.PAPERS).stream()
        if (p := Paper.model_validate(doc.to_dict()))
    }
    rejections = sum(1 for _ in client.collection(store.REJECTIONS).select([]).stream())

    cards = "".join(
        _finding_card(f, appraisals, papers, can_write=can_write) for f in findings
    ) or (
        "<div class='empty'>No findings yet. The fleet opens one only when at "
        "least three independent papers challenge the same component.</div>"
    )

    return f"""<!doctype html><meta charset="utf-8">
<title>Provenance · review</title><style>{STYLE}</style>
<div class="wrap">
  <h1>Provenance</h1>
  <div class="sub">Nothing merges and nothing posts without a decision here.
    {"" if can_write else
     "<br><span style='color:var(--ink4)'>Read-only view. Decisions require the write token; "
     "no action here can reach GitHub in any case.</span>"}</div>
  <div class="counts">
    <div class="count"><b>{len(papers):,}</b><span>Papers read</span></div>
    <div class="count"><b>{len(appraisals):,}</b><span>Appraised</span></div>
    <div class="count"><b>{rejections:,}</b><span>Rejected</span></div>
    <div class="count"><b>{len(findings)}</b><span>Findings</span></div>
  </div>
  {cards}
</div>"""


@app.post("/unlock")
def unlock(token: str = Form(...)) -> RedirectResponse:
    """Exchange the write token for a cookie, so it is typed once."""
    if not _may_write(token):
        raise HTTPException(status_code=403, detail="wrong token")
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        "provenance_write", token, httponly=True, secure=True,
        samesite="strict", max_age=60 * 60 * 12,
    )
    return response


@app.post("/decide")
def decide(
    finding_id: str = Form(...),
    decision: str = Form(...),
    reason: str = Form(default=""),
    provenance_write: str | None = Cookie(default=None),
) -> RedirectResponse:
    """Record a human decision, and keep the reason where agents will read it."""
    if not _may_write(provenance_write):
        raise HTTPException(
            status_code=403,
            detail="This console is readable by anyone and decidable by nobody "
                   "without the write token.",
        )
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="unknown decision")

    client = db()
    ref = client.collection(store.FINDINGS).document(finding_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="no such finding")

    finding = Finding.model_validate(snapshot.to_dict())
    approved = decision == "approve"
    finding.status = FindingStatus.APPROVED if approved else FindingStatus.REJECTED
    store.save_finding(finding, db=client)

    # The reason selector shares a form with both buttons, so the browser sends
    # whatever it happens to be showing even when Approve was pressed. Storing
    # that verbatim produces an audit trail reading "approved because the
    # evidence is too weak", which is worse than no reason at all: the decision
    # log is the record of WHY a change to a health algorithm was accepted.
    reason_code = "" if approved else reason
    client.collection("provenance_decisions").document(
        f"{finding_id}__{decision}"
    ).set({
        "finding_id": finding_id,
        "component_id": finding.component_id,
        "decision": decision,
        "reason_code": reason_code,
        "reason": REJECTION_REASONS.get(reason_code, ""),
        "decided_at": datetime.now(timezone.utc).isoformat(),
    })

    # A rejection that teaches nothing produces the same proposal tomorrow, so
    # it is also written to the rejection log the Synthesist consults.
    if decision == "reject":
        store.save_rejections(
            [
                Rejection(
                    paper_id=f"component:{finding.component_id}",
                    title=finding.component_id,
                    stage="synthesist",
                    reason_code=f"human_{reason or 'rejected'}",
                    reason=REJECTION_REASONS.get(reason, "Rejected by a reviewer."),
                )
            ],
            db=client,
        )

    return RedirectResponse(url="/", status_code=303)


# Not /healthz. Google's frontend reserves that path and answers it itself
# with a 404 that never reaches the container -- which looks exactly like a
# service that is deployed but unroutable, and cost an afternoon of debugging
# a routing problem that did not exist. /nope returns FastAPI's own JSON 404;
# /healthz returns Google's HTML one. That difference is the tell.
@app.get("/health")
def health() -> dict:
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
