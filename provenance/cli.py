"""Command line entry points.

    python -m provenance agenda          show the agenda derived from the algorithm
    python -m provenance sweep           run a literature sweep and persist it
    python -m provenance status          what is currently in the store
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import textwrap

from .agenda import build_agenda
from .agents.scout import sweep
from .config import SUBJECTS, SubjectApp


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
    )
    for noisy in ("httpx", "google_genai", "urllib3", "google.auth", "google.api_core"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _subject(name: str) -> SubjectApp:
    try:
        return SUBJECTS[name]
    except KeyError:
        raise SystemExit(f"unknown subject {name!r}; known: {', '.join(SUBJECTS)}")


def cmd_agenda(args: argparse.Namespace) -> int:
    agenda = build_agenda(_subject(args.subject), refresh=args.refresh)
    print(f"\n{agenda.algorithm_version}   digest {agenda.source_digest}   "
          f"{len(agenda.items)} components\n")
    for item in agenda.items:
        window = f"{item.window_days}d" if item.window_days else "-"
        print(f"  {item.component_id:<18} {item.weight:>5g}pt {window:>5}  {item.display_name}")
        if args.detail:
            print(textwrap.indent(textwrap.fill(item.current_rule, 84), " " * 6))
            for concept in item.search_concepts:
                print(f"        · {concept}")
            print()
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    from .store import firestore as store

    subject = _subject(args.subject)
    db = None if args.no_store else store.client()
    known = store.known_paper_ids(db=db) if db else set()

    result = asyncio.run(
        sweep(
            subject,
            since_days=args.since_days,
            limit_per_source=args.limit,
            known_ids=known,
            components=args.components,
        )
    )

    if db is not None:
        store.save_agenda(result.agenda, db=db)
        store.save_papers(result.papers, db=db)
        store.save_rejections(result.rejections, db=db)

    print(f"\n{len(result.papers)} new · {result.seen_count} seen · "
          f"{len(result.rejections)} screened out"
          f"{' · NOT PERSISTED' if db is None else ''}\n")
    for component, count in sorted(result.per_component.items(), key=lambda kv: -kv[1]):
        print(f"  {component:<18} {count:>4}")
    return 0


def cmd_appraise(args: argparse.Namespace) -> int:
    import collections

    from .agents.appraiser import appraise, triage
    from .models import Paper
    from .store import firestore as store

    db = store.client()
    agenda = build_agenda(_subject(args.subject))

    already = {doc.id for doc in db.collection(store.APPRAISALS).select([]).stream()}
    seen_rejects = {
        doc.id.split("__")[0]
        for doc in db.collection(store.REJECTIONS).select([]).stream()
    }
    done = already | seen_rejects
    # --redo runs ONLY the named papers back through the pipeline; the fresh
    # appraisal overwrites the stored one (save_appraisals keys on paper_id).
    redo = set(args.redo or [])

    query = db.collection(store.PAPERS)
    papers = [
        paper
        for doc in query.stream()
        if (paper := Paper.model_validate(doc.to_dict()))
        and (paper.doc_id in redo if redo else paper.doc_id not in done)
    ]
    if args.limit_papers:
        papers = papers[: args.limit_papers]

    print(f"{len(papers)} unappraised papers")
    if not papers:
        return 0

    kept, triaged_out = asyncio.run(triage(papers, agenda))
    appraisals, rejected = asyncio.run(appraise(kept, agenda))

    store.save_appraisals(appraisals, db=db)
    store.save_rejections(triaged_out + rejected, db=db)

    print(f"\n  tiers      {dict(collections.Counter(a.tier.value for a in appraisals))}")
    print(f"  alignment  {dict(collections.Counter(a.alignment.value for a in appraisals))}")
    print(f"  rejected   {dict(collections.Counter(r.reason_code for r in triaged_out + rejected))}")
    return 0


def cmd_synthesise(args: argparse.Namespace) -> int:
    import collections

    from .agents.synthesist import synthesise
    from .models import Appraisal, Finding, Paper
    from .store import firestore as store

    subject = _subject(args.subject)
    db = store.client()
    agenda = build_agenda(subject)

    appraisals = [
        Appraisal.model_validate(doc.to_dict())
        for doc in db.collection(store.APPRAISALS).stream()
    ]
    papers = {
        paper.doc_id: paper
        for doc in db.collection(store.PAPERS).stream()
        if (paper := Paper.model_validate(doc.to_dict()))
    }
    print(f"{len(appraisals)} appraisals across {len(papers)} papers")
    print(f"  alignment {dict(collections.Counter(a.alignment.value for a in appraisals))}")

    prior = [
        Finding.model_validate(doc.to_dict())
        for doc in db.collection(store.FINDINGS).stream()
    ]
    findings, gated = asyncio.run(
        synthesise(subject, agenda, appraisals, papers, prior_findings=prior)
    )
    for finding in findings:
        store.save_finding(finding, db=db)
    store.save_rejections(gated, db=db)

    print(f"\n{len(findings)} finding(s) opened, {len(gated)} component(s) gated\n")
    for finding in findings:
        print(f"  [{finding.confidence:.2f}] {finding.component_id}: {finding.statement[:88]}")
        for change in finding.proposed_changes:
            print(f"      {change.symbol}: {change.current_value} -> {change.proposed_value}")
    if args.show_gated:
        print()
        for rejection in gated:
            print(f"  GATED {rejection.title:<18} [{rejection.reason_code}] {rejection.reason[:70]}")
    return 0


def cmd_engineer(args: argparse.Namespace) -> int:
    from .agents.engineer import execute, plan
    from .models import Appraisal, Finding, FindingStatus, Paper
    from .store import firestore as store

    subject = _subject(args.subject)
    db = store.client()

    findings = [
        finding
        for doc in db.collection(store.FINDINGS).stream()
        if (finding := Finding.model_validate(doc.to_dict())).subject_key == subject.key
        and (args.finding_id is None or finding.finding_id == args.finding_id)
        and (args.redo or finding.status == FindingStatus.OPEN)
    ]
    if not findings:
        print("no open findings to engineer")
        return 0

    appraisals = {
        appraisal.paper_id: appraisal
        for doc in db.collection(store.APPRAISALS).stream()
        if (appraisal := Appraisal.model_validate(doc.to_dict()))
    }
    papers = {
        paper.doc_id: paper
        for doc in db.collection(store.PAPERS).stream()
        if (paper := Paper.model_validate(doc.to_dict()))
    }

    for finding in findings:
        print(f"\n=== {finding.finding_id} ===")
        engineering = asyncio.run(plan(subject, finding, appraisals, papers))
        if engineering is None:
            print("  no plan produced")
            continue

        print(f"  resolved  {engineering.resolved_symbol} @ {engineering.symbol_location}")
        print(f"  edits     {len(engineering.edits)} across "
              f"{len({e.path for e in engineering.edits})} files")

        result = execute(
            subject,
            finding,
            engineering,
            appraisals,
            papers,
            repo=subject.github_repo,
            base=subject.base_branch,
            run_tests=not args.skip_tests,
        )
        for label, value in result.items():
            print(f"  {label:<13} {value.splitlines()[0][:96]}")

        if not settings_dry_run():
            finding.status = FindingStatus.PR_DRAFTED
            finding.issue_url = result.get("issue", "")
            finding.pr_url = result.get("pull_request", "")
            store.save_finding(finding, db=db)
    return 0


def settings_dry_run() -> bool:
    from .config import settings

    return settings().dry_run


def cmd_evidence(args: argparse.Namespace) -> int:
    """Show what a finding is actually based on, down to the quoted sentence."""
    from .models import Appraisal, Finding, Paper
    from .store import firestore as store

    db = store.client()
    findings = [
        finding
        for doc in db.collection(store.FINDINGS).stream()
        if (finding := Finding.model_validate(doc.to_dict()))
        and (args.finding_id is None or finding.finding_id == args.finding_id)
        and (args.component is None or finding.component_id == args.component)
    ]
    if not findings:
        print("no findings match")
        return 0

    appraisals = {
        appraisal.paper_id: appraisal
        for doc in db.collection(store.APPRAISALS).stream()
        if (appraisal := Appraisal.model_validate(doc.to_dict()))
    }
    papers = {
        paper.doc_id: paper
        for doc in db.collection(store.PAPERS).stream()
        if (paper := Paper.model_validate(doc.to_dict()))
    }

    for finding in findings:
        print(f"\n{'=' * 92}")
        print(f"{finding.component_id}  ·  confidence {finding.confidence:.2f}  ·  "
              f"tiers {finding.tier_counts}  ·  {finding.status.value}")
        print(f"{'=' * 92}")
        print(textwrap.fill(finding.statement, 92))
        if finding.pr_url:
            print(f"\nPR    {finding.pr_url}")
        if finding.issue_url:
            print(f"Issue {finding.issue_url}")

        for change in finding.proposed_changes:
            print(f"\nPROPOSED  {change.symbol}: {change.current_value} -> {change.proposed_value}")

        rows = [
            (appraisals[pid], papers[pid])
            for pid in finding.supporting_paper_ids
            if pid in appraisals and pid in papers
        ]
        rows.sort(key=lambda r: (r[0].tier.value, -(r[0].sample_size or 0)))

        print(f"\n{len(rows)} SUPPORTING STUDIES\n")
        for appraisal, paper in rows:
            size = f"n={appraisal.sample_size:,}" if appraisal.sample_size else ""
            print(f"[{appraisal.tier.value}] {paper.title}")
            print(f"    {paper.citation()}  ·  {appraisal.design}"
                  f"{'  ·  ' + size if size else ''}"
                  f"{'  ·  ' + appraisal.follow_up if appraisal.follow_up else ''}")
            print(f"    {paper.url}")
            if args.quotes:
                for claim in appraisal.claims:
                    print(textwrap.indent(textwrap.fill(f'"{claim.quote}"', 84), "      "))
            print()
    return 0


def cmd_storyteller(args: argparse.Namespace) -> int:
    """Turn a finding into a rendered creative, gates and all."""
    import json
    import subprocess
    from pathlib import Path

    from .agents.storyteller import tell
    from .models import Appraisal, Finding, Paper
    from .store import firestore as store

    db = store.client()
    findings = [
        finding
        for doc in db.collection(store.FINDINGS).stream()
        if (finding := Finding.model_validate(doc.to_dict()))
        and (args.component is None or finding.component_id == args.component)
    ]
    if not findings:
        print("no findings match")
        return 0

    appraisals = {
        a.paper_id: a
        for doc in db.collection(store.APPRAISALS).stream()
        if (a := Appraisal.model_validate(doc.to_dict()))
    }
    papers = {
        p.doc_id: p
        for doc in db.collection(store.PAPERS).stream()
        if (p := Paper.model_validate(doc.to_dict()))
    }

    for finding in findings:
        print(f"\n=== {finding.component_id} ===")
        result = asyncio.run(tell(finding, appraisals, papers))
        if result is None:
            print("  no creative survived the gates")
            continue
        payload, plan = result

        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        spec = out / f"{finding.component_id}.json"
        spec.write_text(json.dumps(payload, indent=1))
        print(f"  spec  {spec}")
        for index, slide in enumerate(plan.slides, start=1):
            print(f"  {index}. {slide.headline}")

        if args.render:
            renderer = Path(__file__).resolve().parent.parent / "renderer"
            subprocess.run(
                ["node", "render.mjs", "carousel", str(spec.resolve()), str(out.resolve())],
                cwd=renderer, check=False,
            )
            print(f"  rendered → {out}")
    return 0


def cmd_content(args: argparse.Namespace) -> int:
    """The publishable pool: papers worth a post, ranked, with a motion each."""
    from . import content as pool
    from .models import Appraisal, Paper
    from .store import firestore as store

    db = store.client()
    appraisals = [
        Appraisal.model_validate(doc.to_dict())
        for doc in db.collection(store.APPRAISALS).stream()
    ]
    papers = {
        p.doc_id: p
        for doc in db.collection(store.PAPERS).stream()
        if (p := Paper.model_validate(doc.to_dict()))
    }

    if args.mark:
        pool.mark_posted(args.mark, db=db, note=args.note or "")
        print(f"marked posted: {args.mark}")
        return 0

    posted = pool.posted_ids(db=db)
    picks = pool.candidates(
        appraisals, papers,
        posted=posted, component=args.component,
        include_weak=args.include_weak, sweepable=args.sweepable,
        limit=args.limit,
    )
    if not picks:
        print("nothing sweepable in the pool" if args.sweepable
              else "nothing publishable in the pool")
        return 0

    print(f"{len(picks)} publishable · {len(posted)} already posted\n")
    for index, c in enumerate(picks, start=1):
        a = c.appraisal
        print(f"{index:>2}. [{a.tier.value}] {c.title[:76]}")
        journal = c.paper.journal if c.paper else ""
        bits = " · ".join(b for b in (journal, a.design, a.follow_up) if b)
        print(f"    {bits}")
        print(f"    motion {c.motion}  ·  score {c.score:.0f}  ·  {', '.join(c.reasons)}")
        if c.sweep_signals:
            print(f"    sweep signals: {', '.join(c.sweep_signals[:4])}")
        for claim in c.numeric_claims[:2]:
            ci = (f" [{claim.ci_low:g} to {claim.ci_high:g}]"
                  if claim.ci_low is not None and claim.ci_high is not None else "")
            print(f"      {claim.value:g}{claim.unit}{ci} — {claim.statement[:74]}")
        print(f"    id {c.paper_id}")
        print()
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    from . import health as pr_health
    from .models import Finding
    from .store import firestore as store

    subject = _subject(args.subject)
    db = store.client()
    findings = [
        Finding.model_validate(doc.to_dict())
        for doc in db.collection(store.FINDINGS).stream()
    ]
    result = pr_health.sweep(subject, findings, comment=args.comment)
    print(f"\n{result['checked']} checked · {result['unhealthy']} with problems\n")
    for entry in result["report"]:
        print(f"  {entry['pr']}")
        for problem in entry["problems"]:
            print(f"    PROBLEM  {problem}")
        for note in entry["notes"]:
            print(f"    note     {note}")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    """Send the decision email for one audited pull request.

    Called by /provenance AFTER the audit, which is the whole point: the
    reviewer should never be asked to approve code that has not been reviewed
    by anything but the model that wrote it.
    """
    from . import notify
    from .models import Appraisal, Finding, Paper
    from .store import firestore as store

    db = store.client()
    findings = [
        finding
        for doc in db.collection(store.FINDINGS).stream()
        if (finding := Finding.model_validate(doc.to_dict()))
        and (
            (args.pr and f"/pull/{args.pr}" in (finding.pr_url or ""))
            or (args.finding_id and finding.finding_id == args.finding_id)
        )
    ]
    if not findings:
        print(f"no finding matches pr={args.pr} finding_id={args.finding_id}")
        return 1

    appraisals = {
        a.paper_id: a
        for doc in db.collection(store.APPRAISALS).stream()
        if (a := Appraisal.model_validate(doc.to_dict()))
    }
    papers = {
        p.doc_id: p
        for doc in db.collection(store.PAPERS).stream()
        if (p := Paper.model_validate(doc.to_dict()))
    }

    config = notify.mail_config()
    if not config.configured:
        print("email not configured (RESEND_API_KEY / NOTIFY_FROM / NOTIFY_TO)")
        return 1

    for finding in findings:
        subject, html = notify.decision_email(
            finding, appraisals, papers, config,
            verdict=args.verdict, audit_summary=args.summary,
        )
        sent = notify.send(subject, html, config)
        print(f"{'sent' if sent else 'FAILED'}  {finding.component_id}  "
              f"verdict={args.verdict or '(none)'}  {sent or ''}")
    return 0


def cmd_summarise(args: argparse.Namespace) -> int:
    """Write the plain-English cover sentence onto appraisals that lack one.

    Only papers appraised before the field existed need this. It touches
    nothing else on the record, so it is safe to re-run.
    """
    import asyncio

    from .agents.appraiser import summarise
    from .models import Appraisal, Paper
    from .store import firestore as store

    db = store.client()
    missing = [
        a
        for doc in db.collection(store.APPRAISALS).stream()
        if (a := Appraisal.model_validate(doc.to_dict())) and not a.plain_summary.strip()
    ]
    if not missing:
        print("every appraisal already has a plain-English summary")
        return 0

    missing.sort(key=lambda a: a.appraised_at, reverse=True)
    if args.limit:
        missing = missing[: args.limit]
    papers = {
        p.doc_id: p
        for doc in db.collection(store.PAPERS).stream()
        if (p := Paper.model_validate(doc.to_dict()))
    }
    print(f"summarising {len(missing)} appraisal(s)")

    updated = asyncio.run(summarise([(papers.get(a.paper_id), a) for a in missing]))
    store.save_appraisals(updated, db=db)
    for appraisal in updated:
        print(f"  {appraisal.paper_id}\n    {appraisal.plain_summary}")
    print(f"wrote {len(updated)} of {len(missing)}")
    return 0


def cmd_briefing(args: argparse.Namespace) -> int:
    """Rebuild the morning briefing for a run that already happened.

    The nightly job composes this once and posts it. When the question is "what
    did that email look like" -- reviewing a change to it, or showing someone
    the output without waiting for 06:00 -- rebuilding it from the stored run
    beats re-running the pipeline, and it is the same function that sends it,
    so a preview cannot flatter the real thing.
    """
    from . import notify
    from .models import Appraisal, Finding, FindingStatus, Paper, Rejection
    from .store import firestore as store

    db = store.client()
    runs = sorted(
        (doc.to_dict() or {} for doc in db.collection("provenance_runs").stream()),
        key=lambda r: r.get("started_at", ""),
    )
    runs = [r for r in runs if r.get("subject") in (args.subject, None)]
    if not runs:
        print("no runs recorded yet — run `provenance` nightly first")
        return 1
    run = runs[-1 - min(args.ago, len(runs) - 1)]

    started = run.get("started_at", "")
    print(f"briefing for the run started {started}")

    def _after(value) -> bool:
        """Records written by this run, not the whole corpus."""
        if not started or not value:
            return False
        return str(value) >= started

    appraisals = [
        a
        for doc in db.collection(store.APPRAISALS).stream()
        if (a := Appraisal.model_validate(doc.to_dict()))
        and _after(a.appraised_at.isoformat())
    ]
    rejections = [
        r
        for doc in db.collection(store.REJECTIONS).stream()
        if (r := Rejection.model_validate(doc.to_dict()))
        and _after(r.rejected_at.isoformat())
    ]
    papers = {
        p.doc_id: p
        for doc in db.collection(store.PAPERS).stream()
        if (p := Paper.model_validate(doc.to_dict()))
    }
    findings = [
        f
        for doc in db.collection(store.FINDINGS).stream()
        if (f := Finding.model_validate(doc.to_dict()))
        and f.status in (FindingStatus.OPEN, FindingStatus.PR_DRAFTED)
    ]
    agenda = store.latest_agenda(args.subject, db=db)
    components = (
        {item.component_id: item.display_name for item in agenda.items} if agenda else {}
    )

    subject_line, html = notify.briefing_email(
        run,
        [(papers.get(a.paper_id), a) for a in appraisals],
        rejections,
        findings,
        notify.mail_config(),
        components=components,
    )
    print(f"  {len(appraisals)} kept · {len(rejections)} thrown out · "
          f"{len(findings)} still open")
    print(f"  subject: {subject_line}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(html)
        print(f"  wrote {args.out}")

    if args.send:
        sent = notify.send(subject_line, html)
        print(f"  {'sent' if sent else 'NOT SENT (email not configured)'}  {sent or ''}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .store import firestore as store

    db = store.client()
    for label, collection in (
        ("papers", store.PAPERS),
        ("appraisals", store.APPRAISALS),
        ("rejections", store.REJECTIONS),
        ("findings", store.FINDINGS),
    ):
        count = sum(1 for _ in db.collection(collection).select([]).stream())
        print(f"  {label:<12} {count:>6}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provenance")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--subject", default="synqology")
    sub = parser.add_subparsers(dest="command", required=True)

    agenda = sub.add_parser("agenda", help="show the agenda derived from the algorithm")
    agenda.add_argument("--refresh", action="store_true", help="ignore the cache")
    agenda.add_argument("--detail", action="store_true", help="show rules and search terms")
    agenda.set_defaults(func=cmd_agenda)

    sweep_cmd = sub.add_parser("sweep", help="run a literature sweep")
    sweep_cmd.add_argument("--since-days", type=int, default=540)
    sweep_cmd.add_argument("--limit", type=int, default=25, help="records per source per component")
    sweep_cmd.add_argument("--components", nargs="*", default=None)
    sweep_cmd.add_argument("--no-store", action="store_true", help="do not write to Firestore")
    sweep_cmd.set_defaults(func=cmd_sweep)

    appraise_cmd = sub.add_parser("appraise", help="triage and appraise unappraised papers")
    appraise_cmd.add_argument("--limit-papers", type=int, default=None)
    appraise_cmd.add_argument(
        "--redo", action="append", default=None, metavar="PAPER_ID",
        help="re-appraise this already-appraised paper (repeatable); the fresh "
             "appraisal overwrites the stored one after passing grounding",
    )
    appraise_cmd.set_defaults(func=cmd_appraise)

    synth = sub.add_parser("synthesise", help="open findings where evidence converges")
    synth.add_argument("--show-gated", action="store_true", help="show why components were gated")
    synth.set_defaults(func=cmd_synthesise)

    eng = sub.add_parser("engineer", help="turn findings into issues and draft PRs")
    eng.add_argument("--finding-id", default=None)
    eng.add_argument("--redo", action="store_true", help="re-engineer already-drafted findings")
    eng.add_argument("--skip-tests", action="store_true", help="skip the xcodebuild backtest")
    eng.set_defaults(func=cmd_engineer)

    ev = sub.add_parser("evidence", help="show the studies a finding rests on")
    ev.add_argument("--finding-id", default=None)
    ev.add_argument("--component", default=None, help="e.g. mvpa")
    ev.add_argument("--quotes", action="store_true", help="include the verified quote per claim")
    ev.set_defaults(func=cmd_evidence)

    story = sub.add_parser("storyteller", help="turn a finding into a creative")
    story.add_argument("--component", default=None, help="e.g. mvpa")
    story.add_argument("--out", default="renderer/out-real")
    story.add_argument("--render", action="store_true", help="also run the renderer")
    story.set_defaults(func=cmd_storyteller)

    con = sub.add_parser("content", help="the publishable pool, ranked for social")
    con.add_argument("--component", default=None, help="e.g. mvpa")
    con.add_argument("--limit", type=int, default=12)
    con.add_argument("--include-weak", action="store_true",
                     help="include tier C/D — never post these as settled")
    con.add_argument("--sweepable", action="store_true",
                     help="only papers with dose-response signals — the hunt "
                          "for the next 10k-steps reel")
    con.add_argument("--mark", default=None, metavar="PAPER_ID",
                     help="record a paper as posted so it stops being offered")
    con.add_argument("--note", default=None)
    con.set_defaults(func=cmd_content)

    hc = sub.add_parser("health", help="check proposals already opened")
    hc.add_argument("--comment", action="store_true", help="comment on unhealthy PRs")
    hc.set_defaults(func=cmd_health)

    notify_cmd = sub.add_parser("notify", help="send the decision email for an audited PR")
    notify_cmd.add_argument("--pr", type=int, default=None, help="pull request number")
    notify_cmd.add_argument("--finding-id", default=None)
    notify_cmd.add_argument("--repo", default=None, help="accepted for symmetry; unused")
    notify_cmd.add_argument("--verdict", default="", choices=["", "clean", "concerns", "defect"])
    notify_cmd.add_argument("--summary", default="", help="one line from the audit")
    notify_cmd.set_defaults(func=cmd_notify)

    summ = sub.add_parser("summarise",
                          help="backfill plain-English summaries on older appraisals")
    summ.add_argument("--limit", type=int, default=None, help="newest N only")
    summ.set_defaults(func=cmd_summarise)

    brief = sub.add_parser("briefing", help="rebuild the morning briefing for a past run")
    brief.add_argument("--out", default=None, metavar="FILE",
                       help="write the email to an HTML file")
    brief.add_argument("--ago", type=int, default=0,
                       help="0 is the most recent run, 1 the one before it")
    brief.add_argument("--send", action="store_true", help="also email it")
    brief.set_defaults(func=cmd_briefing)

    status = sub.add_parser("status", help="counts by collection")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
