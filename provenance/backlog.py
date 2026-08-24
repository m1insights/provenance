"""Deterministic selection policy for the nightly appraisal queue."""

from __future__ import annotations

from .models import Paper


def select_for_appraisal(
    papers: list[Paper], *, new_ids: set[str], limit: int
) -> list[Paper]:
    """Select a bounded, balanced batch of new and backlog papers.

    New retrievals receive half the capacity (rounded down) and the backlog
    receives the other half. Capacity either group cannot use is lent to the
    other group, so a quiet retrieval day never leaves appraisal slots idle.
    """
    if limit <= 0:
        return []

    ordered = sorted(papers, key=lambda paper: (paper.retrieved_at, paper.doc_id))
    unique_papers: list[Paper] = []
    seen_ids: set[str] = set()
    for paper in ordered:
        if paper.doc_id not in seen_ids:
            unique_papers.append(paper)
            seen_ids.add(paper.doc_id)

    new_papers = [paper for paper in unique_papers if paper.doc_id in new_ids]
    backlog_papers = [paper for paper in unique_papers if paper.doc_id not in new_ids]

    new_slots = limit // 2
    backlog_slots = limit - new_slots
    selected_new = new_papers[:new_slots]
    selected_backlog = backlog_papers[:backlog_slots]

    if len(selected_new) < new_slots:
        selected_backlog.extend(
            backlog_papers[
                backlog_slots : backlog_slots + (new_slots - len(selected_new))
            ]
        )
    if len(selected_backlog) < backlog_slots:
        selected_new.extend(
            new_papers[
                new_slots : new_slots + (backlog_slots - len(selected_backlog))
            ]
        )

    # Keep each cohort's old-first order while alternating cohorts. Starting
    # with backlog guarantees that a three-paper model wave includes both
    # kinds whenever both are present, even if quota stops the run immediately.
    selected: list[Paper] = []
    for index in range(max(len(selected_backlog), len(selected_new))):
        if index < len(selected_backlog):
            selected.append(selected_backlog[index])
        if index < len(selected_new):
            selected.append(selected_new[index])
    return selected[:limit]
