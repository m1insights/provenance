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

    query = db.collection(store.PAPERS)
    papers = [
        paper
        for doc in query.stream()
        if (paper := Paper.model_validate(doc.to_dict())).doc_id not in done
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
    from .models import Appraisal, Paper
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

    findings, gated = asyncio.run(synthesise(subject, agenda, appraisals, papers))
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

    status = sub.add_parser("status", help="counts by collection")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
