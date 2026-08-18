"""The nightly run, as one command.

Cloud Scheduler triggers a Cloud Run Job that calls this. Everything it does is
the same code path the CLI exercises, so a scheduled run and a hand-run produce
identical results -- there is no separate "production" branch that can drift
from the one that gets tested.

The sequence is deliberately fail-soft. A sweep that partially fails still
persists what it found; an appraisal batch that errors does not discard the
papers. The one thing that must not happen automatically is a proposal reaching
GitHub without the evidence behind it, so engineering is gated on a Finding
actually opening.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from datetime import datetime, timezone

from .agenda import build_agenda
from .agents.appraiser import appraise, triage
from .agents.scout import sweep
from .agents.synthesist import synthesise
from .config import SUBJECTS, SubjectApp
from .models import Appraisal, Finding, FindingStatus, Paper
from .store import firestore as store

log = logging.getLogger(__name__)

#: 18 months. Not "since yesterday": PubMed indexes papers days to weeks after
#: publication and irregularly, so a narrow window silently misses most of
#: them. Novelty comes from identity -- every paper carries a DOI-first id and
#: the sweep drops what it already holds -- which makes re-querying a wide
#: window cheap and correct rather than wasteful.
DEFAULT_WINDOW_DAYS = 540

#: Per source, per component. Eleven components across two sources is ~22
#: queries a night, well inside both APIs' published limits.
DEFAULT_LIMIT = 25


async def run(
    subject: SubjectApp,
    *,
    since_days: int = DEFAULT_WINDOW_DAYS,
    limit_per_source: int = DEFAULT_LIMIT,
    engineer: bool = False,
) -> dict:
    """One complete pass. Returns a summary for the run log."""
    started = datetime.now(timezone.utc)
    db = store.client()
    summary: dict = {"subject": subject.key, "started_at": started.isoformat()}

    # --- retrieve ---------------------------------------------------------
    known = store.known_paper_ids(db=db)
    result = await sweep(
        subject, since_days=since_days, limit_per_source=limit_per_source,
        known_ids=known,
    )
    store.save_agenda(result.agenda, db=db)
    store.save_papers(result.papers, db=db)
    store.save_rejections(result.rejections, db=db)
    summary |= {
        "algorithm_version": result.agenda.algorithm_version,
        "retrieved_new": len(result.papers),
        "already_seen": result.seen_count,
        "screened_out": len(result.rejections),
    }
    log.info("nightly: %d new papers", len(result.papers))

    # --- appraise ---------------------------------------------------------
    if result.papers:
        kept, triaged_out = await triage(result.papers, result.agenda)
        appraisals, rejected = await appraise(kept, result.agenda)
        store.save_appraisals(appraisals, db=db)
        store.save_rejections(triaged_out + rejected, db=db)
        summary |= {
            "appraised": len(appraisals),
            "tiers": dict(Counter(a.tier.value for a in appraisals)),
            "alignment": dict(Counter(a.alignment.value for a in appraisals)),
            "rejected": dict(
                Counter(r.reason_code for r in triaged_out + rejected)
            ),
        }
    else:
        summary |= {"appraised": 0}

    # --- synthesise -------------------------------------------------------
    # Convergence is judged over the whole accumulated corpus, not tonight's
    # batch: the third paper that completes a Finding may have arrived weeks
    # before the one that triggers this run.
    all_appraisals = [
        Appraisal.model_validate(doc.to_dict())
        for doc in db.collection(store.APPRAISALS).stream()
    ]
    papers = {
        p.doc_id: p
        for doc in db.collection(store.PAPERS).stream()
        if (p := Paper.model_validate(doc.to_dict()))
    }
    prior = [
        Finding.model_validate(doc.to_dict())
        for doc in db.collection(store.FINDINGS).stream()
    ]
    existing = {f.finding_id for f in prior}

    findings, gated = await synthesise(
        subject, result.agenda, all_appraisals, papers, prior_findings=prior
    )
    fresh = [f for f in findings if f.finding_id not in existing]
    for finding in findings:
        store.save_finding(finding, db=db)
    store.save_rejections(gated, db=db)
    summary |= {
        "findings_total": len(findings),
        "findings_new": len(fresh),
        "components_gated": len(gated),
    }

    # --- engineer ---------------------------------------------------------
    # Off by default. A draft pull request is cheap to close but it is still a
    # notification to a human, and opening one unattended every night for the
    # same finding would train them to ignore it.
    if engineer and fresh:
        from .agents.engineer import execute, plan

        appraisal_index = {a.paper_id: a for a in all_appraisals}
        opened = []
        for finding in fresh:
            engineering = await plan(subject, finding, appraisal_index, papers)
            if engineering is None:
                continue
            outcome = execute(
                subject, finding, engineering, appraisal_index, papers,
                repo=subject.github_repo, base=subject.base_branch, run_tests=True,
            )
            finding.status = FindingStatus.PR_DRAFTED
            finding.issue_url = outcome.get("issue", "")
            finding.pr_url = outcome.get("pull_request", "")
            store.save_finding(finding, db=db)
            opened.append(finding.pr_url)
        summary["pull_requests"] = opened

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    summary["seconds"] = round(
        (datetime.now(timezone.utc) - started).total_seconds(), 1
    )

    # The run log is what a reviewer reads to answer "did it actually run last
    # night, and what did it decide" without reconstructing it from traces.
    db.collection("provenance_runs").document(
        started.strftime("%Y-%m-%dT%H:%M:%SZ")
    ).set(summary)
    log.info("nightly: done in %.1fs — %s", summary["seconds"], summary)
    return summary


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "google_genai", "urllib3", "google.auth", "google.api_core"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    subject = SUBJECTS[os.getenv("PROVENANCE_SUBJECT", "synqology")]
    asyncio.run(
        run(
            subject,
            since_days=int(os.getenv("PROVENANCE_WINDOW_DAYS", DEFAULT_WINDOW_DAYS)),
            limit_per_source=int(os.getenv("PROVENANCE_LIMIT", DEFAULT_LIMIT)),
            engineer=os.getenv("PROVENANCE_ENGINEER", "").lower() in {"1", "true", "yes"},
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
