"""Companion -- carry an approved change into the other repository.

A pull request cannot span repositories, and synqology's scoring rules live in
two: the Swift implementation in ``synq``, and the explainer injected into the
synqIQ chat prompt in ``synq_insights``. Merging one without the other leaves
the assistant confidently describing an algorithm the app no longer runs, which
is a worse failure than not changing anything -- the app is right and the thing
explaining it is wrong.

This runs only after a human approves. The proposal in the main repository has
already been judged on its evidence; this is not a second judgement, it is the
rest of the same change.
"""

from __future__ import annotations

import json
import logging
import re

from google.adk.agents import LlmAgent
from google.genai import types

from ..config import REASONING_MODEL, CrossRepoCompanion, SubjectApp
from ..llm import model as llm_model
from ..models import Finding
from ..tools import github
from .engineer import EditPlan, ProposedEdit

log = logging.getLogger(__name__)


INSTRUCTION = """\
A change to a production scoring algorithm has been approved and is being \
merged in one repository. Your job is the same change in a second repository, \
which describes that algorithm to users through a chat assistant.

You are NOT re-deciding whether the change is right. That decision is made. You \
are making the description match the implementation.

Rules:

- Change only what the approved edit makes untrue. Wording that is still \
accurate stays exactly as it is; a diff that rewrites correct prose is a diff \
nobody can review.
- Keep the file's existing voice. It is read by an assistant and shown to \
users, so it is prose, not a changelog.
- If a number appears, it must match the approved value exactly.
- `old` must be copied EXACTLY from the file content shown, without the line \
numbers. It must appear exactly once; include surrounding lines until it does.

Return ONLY a JSON object with `resolved_symbol`, `symbol_location`, \
`version_bump`, `coupling_notes` and `edits`.
"""


def _branch(finding: Finding) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", finding.component_id.lower()).strip("-")
    return f"provenance/{slug}-explainer-{finding.finding_id.rsplit('__', 1)[-1][:8]}"


async def propose(
    subject: SubjectApp,
    companion: CrossRepoCompanion,
    finding: Finding,
    *,
    approved_changes: str,
    base_branch: str = "main",
) -> dict | None:
    """Open a draft pull request bringing the companion file into line."""
    from .appraiser import _run

    path = subject.repo_path.parent / companion.github_repo.split("/")[-1] / companion.path
    if not path.is_file():
        log.warning("companion: no local checkout at %s", path)
        return None

    content = path.read_text()
    numbered = "\n".join(
        f"{n:>5}  {line}" for n, line in enumerate(content.splitlines(), start=1)
    )

    agent = LlmAgent(
        name="companion",
        model=llm_model(REASONING_MODEL),
        instruction=INSTRUCTION,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, max_output_tokens=16384
        ),
    )

    prompt = (
        f"# APPROVED CHANGE (already merging in {subject.github_repo})\n\n"
        f"{finding.statement}\n\n"
        f"## Edits approved\n{approved_changes}\n\n"
        f"## Why it matters here\n{companion.why}\n\n"
        f"# FILE TO UPDATE: {companion.path}\n"
        f"```\n{numbered}\n```\n\n"
        f"Return the JSON object described in your instructions.\n"
        f"{json.dumps(EditPlan.model_json_schema()['properties'], indent=1)[:900]}"
    )

    raw = await _run(agent, prompt)
    if raw is None:
        log.warning("companion: no plan produced")
        return None
    try:
        plan = EditPlan.model_validate(raw)
    except Exception as exc:
        log.warning("companion: invalid plan: %s", exc)
        return None
    if not plan.edits:
        log.info("companion: nothing in %s needs changing", companion.path)
        return {"skipped": "no change needed"}

    # The companion repository is a different SubjectApp as far as the git and
    # GitHub tooling is concerned: different checkout, different remote, its
    # own trunk.
    target = SubjectApp(
        key=f"{subject.key}-companion",
        name=companion.github_repo,
        repo_path=subject.repo_path.parent / companion.github_repo.split("/")[-1],
        github_repo=companion.github_repo,
        base_branch=base_branch,
        algorithm_doc=path,
        algorithm_source=path,
    )

    edits = [
        github.Edit(path=_relative(e, companion.path), old=e.old, new=e.new)
        for e in plan.edits
    ]

    body = (
        f"Companion to **{finding.pr_url or subject.github_repo}**, which was "
        f"approved by a reviewer.\n\n"
        f"{companion.why}\n\n"
        f"## What changed\n\n"
        + "\n".join(f"- {e.why or 'kept in line with the approved change'}" for e in plan.edits)
        + f"\n\n{plan.coupling_notes}\n\n---\n"
        f"Opened by **Provenance** because a pull request cannot span "
        f"repositories. This is a draft: no agent can merge it."
    )

    url = github.open_pull_request(
        target,
        repo=companion.github_repo,
        branch=_branch(finding),
        base=base_branch,
        title=f"docs(vi): keep the explainer in line with {finding.component_id} change",
        body=body,
        edits=edits,
        commit_message=(
            f"docs(vi): keep explainer in line with approved {finding.component_id} change\n\n"
            f"Companion to {finding.pr_url}."
        ),
        draft=True,
    )
    log.info("companion: opened %s", url)
    return {"pull_request": url, "edits": len(edits)}


def _relative(edit: ProposedEdit, expected: str) -> str:
    """Models sometimes echo a fuller path than the repository uses."""
    given = (edit.path or "").strip()
    if not given or given.endswith(expected) or expected.endswith(given):
        return expected
    return given
