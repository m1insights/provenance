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

    status = sub.add_parser("status", help="counts by collection")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
