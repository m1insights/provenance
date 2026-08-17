"""Engineer -- turn a Finding into a draft pull request a human can judge.

The Synthesist works from a cached snapshot of the algorithm and names symbols
loosely; it proposed changing ``mvpaCreditDaysTarget``, which does not exist.
The Engineer therefore starts by *searching the live repository* for where the
value actually lives, and refuses to edit a symbol it cannot find.

What it produces is deliberately not a merge. It is an issue stating the
evidence, and a draft pull request whose body carries the proposed diff, the
result of running the repository's own scoring tests against that diff, and the
strongest argument against making the change at all.
"""

from __future__ import annotations

import json
import logging
import re

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import AliasChoices, BaseModel, Field

from ..config import REASONING_MODEL, SubjectApp
from ..guardrails.callbacks import enforce_draft_only
from ..llm import model as llm_model
from ..models import Appraisal, Finding, Paper
from ..tools import backtest, github
from ..tools.repo import RepoReader

log = logging.getLogger(__name__)


class ProposedEdit(BaseModel):
    """One exact-match replacement in a real file.

    Field aliases are deliberate. This agent carries tools, so ADK forbids
    ``output_schema`` and the shape is requested in the prompt instead --
    which means the model picks plausible synonyms. It reliably produces
    correct edits under the key ``file``; rejecting eleven good edits over a
    key name would be pedantry, not rigour. The content is still validated.
    """

    model_config = {"populate_by_name": True}

    path: str = Field(
        validation_alias=AliasChoices("path", "file", "file_path"),
        description="Repository-relative path, exactly as the tools report it",
    )
    old: str = Field(
        validation_alias=AliasChoices("old", "old_string", "before"),
        description="Text to replace, copied EXACTLY from the file including "
        "indentation. Include enough surrounding lines to be unique.",
    )
    new: str = Field(
        validation_alias=AliasChoices("new", "new_string", "after"),
        description="Replacement text, same indentation style",
    )
    why: str = Field(
        default="",
        validation_alias=AliasChoices("why", "reason", "rationale"),
        description="One sentence: what this edit accomplishes",
    )


class EditPlan(BaseModel):
    """First call: where the value lives and exactly how to change it."""

    resolved_symbol: str = Field(
        description="The symbol that actually holds the value, as found in the repository"
    )
    symbol_location: str = Field(description="path:line where it is declared")
    version_bump: str = Field(default="", description="e.g. VI v2.11.0 -> VI v2.12.0")
    coupling_notes: str = Field(
        default="",
        description="Other values or consumers affected, found by reading usage sites",
    )
    edits: list[ProposedEdit] = Field(default_factory=list)


class NarrativePlan(BaseModel):
    """Second call: the prose a reviewer reads, written against final edits."""

    issue_title: str
    issue_body: str = Field(description="Markdown. Evidence, current behaviour, proposal.")
    pr_title: str
    pr_body: str = Field(description="Markdown. What changed and why.")
    commit_message: str = Field(description="Conventional-commit subject, then a body")
    dissent: str = Field(description="The strongest argument against making this change")


class EngineeringPlan(EditPlan, NarrativePlan):
    """The two halves, joined.

    Split because asking for eleven exact-match edits *and* two markdown
    documents in one response overruns the output limit and returns JSON that
    is merely truncated -- which is indistinguishable from a malformed plan.
    Splitting also means edits are validated before any tokens are spent on
    prose describing them.
    """


INSTRUCTION = """\
You are proposing a change to a production health application used by real \
people. Your output is a DRAFT pull request for a human to judge, never a merge.

## Work in this order

1. **Find where the value actually lives.** Call `find_symbol` on the symbol the \
finding names. It is frequently wrong -- the finding is written from a summary, \
not from the code. If it does not exist, use `search_source` to find the real \
constant. Never propose an edit to a symbol the tools did not return.

2. **Read the surrounding code** with `read_source_file`. Constants here carry \
comments explaining why they hold their current value, often citing the \
literature they came from. You are arguing against a stated rationale, so \
address it directly in the pull request body. A proposal that ignores the \
existing reasoning will be rejected by the reviewer.

3. **Check the coupling.** A constant that has a paired value for a special \
population, or is read by more than one consumer, cannot be changed in \
isolation. `find_symbol` lists every usage site; read them.

4. **Call `companion_files`.** This repository requires that an algorithm change \
updates the specification and the chat explainer alongside the code, and bumps \
the version. A pull request that changes only the constant leaves three sources \
disagreeing, and will be rejected.

## Writing the edits

`old` must be copied EXACTLY from what `read_source_file` returned -- the same \
indentation, the same comment text -- but WITHOUT the line-number prefix the \
tool adds. It must appear exactly once in the file; include surrounding lines \
until it does. An edit whose `old` is not found, or is found twice, is refused.

Update the doc comment when you change a value it describes. A stale comment is \
worse than no comment.

## Writing the body

State the evidence honestly. Give tier counts, not adjectives. Quote the \
existing rationale you are arguing against. `dissent` must contain the \
strongest genuine argument against your own proposal -- population mismatch, \
surrogate endpoints, the possibility the current value is already right. If you \
cannot argue against it, you do not understand it well enough to propose it.

Do not claim any effect on user scores. You have not measured that.
"""


def _tools(reader: RepoReader) -> list[FunctionTool]:
    """Bind the read-only repository tools for this subject.

    Note what is absent: nothing here writes. Applying edits, committing and
    pushing are done by code after the plan is validated, so the model cannot
    reach the repository directly.
    """

    def find_symbol(symbol: str) -> str:
        """Locate where a symbol is declared and every place it is used.

        Args:
            symbol: Identifier to look for, e.g. 'mvpaDayFactorDenominator'.
        """
        return reader.find_symbol(symbol)

    def read_source_file(path: str, start_line: int = 1, line_count: int = 120) -> str:
        """Read part of a file from the subject repository.

        Args:
            path: Repository-relative path.
            start_line: 1-indexed first line.
            line_count: How many lines to return.
        """
        return reader.read_source_file(path, start_line, line_count)

    def search_source(pattern: str) -> str:
        """Search the repository with a regular expression.

        Args:
            pattern: Python regular expression.
        """
        return reader.search_source(pattern)

    def companion_files() -> str:
        """List files that must be updated alongside any algorithm change."""
        return reader.companion_files()

    return [FunctionTool(f) for f in (find_symbol, read_source_file, search_source, companion_files)]


def _evidence_block(finding: Finding, appraisals: dict[str, Appraisal], papers: dict[str, Paper]) -> str:
    rows = []
    for paper_id in finding.supporting_paper_ids[:12]:
        appraisal = appraisals.get(paper_id)
        paper = papers.get(paper_id)
        if appraisal is None or paper is None:
            continue
        quote = appraisal.claims[0].quote if appraisal.claims else ""
        rows.append(
            f"- **[Tier {appraisal.tier.value}]** {paper.title}\n"
            f"  {paper.citation()} — {appraisal.design}"
            f"{f', n={appraisal.sample_size:,}' if appraisal.sample_size else ''}\n"
            f"  > {quote}\n"
            f"  {paper.url}"
        )
    return "\n".join(rows)


async def plan(
    subject: SubjectApp,
    finding: Finding,
    appraisals: dict[str, Appraisal],
    papers: dict[str, Paper],
) -> EngineeringPlan | None:
    """Ask the Engineer for a concrete, located, exact-match set of edits."""
    from .appraiser import _run

    reader = RepoReader(subject)
    proposed = "\n".join(
        f"- {c.symbol}: {c.current_value} -> {c.proposed_value}\n  {c.rationale}"
        for c in finding.proposed_changes
    )
    evidence = _evidence_block(finding, appraisals, papers)
    header = (
        f"# FINDING: {finding.component_id} (confidence {finding.confidence:.2f})\n\n"
        f"{finding.statement}\n\n"
        f"## CURRENT BEHAVIOUR (cached snapshot -- verify against the live source)\n"
        f"{finding.current_behavior}\n\n"
        f"## PROPOSED (symbol names here may be wrong; resolve them yourself)\n{proposed}\n"
    )

    # --- first call: investigate the repository and produce exact edits ---
    editor = LlmAgent(
        name="engineer_edits",
        model=llm_model(REASONING_MODEL),
        instruction=INSTRUCTION,
        tools=_tools(reader),
        before_tool_callback=enforce_draft_only,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, max_output_tokens=32768
        ),
    )
    edit_raw = await _run(
        editor,
        f"{header}\n"
        f"Investigate with the tools, then return ONLY a JSON object with these keys:\n"
        f"{json.dumps(EditPlan.model_json_schema()['properties'], indent=1)[:1200]}\n\n"
        f"Do NOT write any prose bodies yet. Edits only.",
    )
    if edit_raw is None:
        log.warning("engineer: no edit plan for %s", finding.finding_id)
        return None
    try:
        edit_plan = EditPlan.model_validate(edit_raw)
    except Exception as exc:
        log.warning("engineer: invalid edit plan for %s: %s", finding.finding_id, exc)
        return None
    if not edit_plan.edits:
        log.warning("engineer: edit plan for %s proposes nothing", finding.finding_id)
        return None

    # --- second call: prose, written against the edits that actually exist ---
    diff_summary = "\n\n".join(
        f"### {e.path}\n- {e.why}\n```diff\n- {e.old[:280]}\n+ {e.new[:280]}\n```"
        for e in edit_plan.edits
    )
    writer = LlmAgent(
        name="engineer_narrative",
        model=llm_model(REASONING_MODEL),
        instruction=INSTRUCTION,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.3, max_output_tokens=16384
        ),
    )
    narrative_raw = await _run(
        writer,
        f"{header}\n"
        f"## EVIDENCE ({sum(finding.tier_counts.values())} papers, tiers {finding.tier_counts})\n"
        f"{evidence}\n\n"
        f"## RESOLVED SYMBOL\n{edit_plan.resolved_symbol} at {edit_plan.symbol_location}\n"
        f"{edit_plan.coupling_notes}\n\n"
        f"## EDITS ALREADY DECIDED ({len(edit_plan.edits)} files)\n{diff_summary}\n\n"
        f"Write the issue and pull request text for exactly these edits. "
        f"Return ONLY a JSON object with these keys:\n"
        f"{json.dumps(NarrativePlan.model_json_schema()['properties'], indent=1)[:900]}",
    )
    if narrative_raw is None:
        log.warning("engineer: no narrative for %s", finding.finding_id)
        return None
    try:
        narrative = NarrativePlan.model_validate(narrative_raw)
    except Exception as exc:
        log.warning("engineer: invalid narrative for %s: %s", finding.finding_id, exc)
        return None

    return EngineeringPlan(**(edit_plan.model_dump() | narrative.model_dump()))


def _branch_name(finding: Finding) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", finding.component_id.lower()).strip("-")
    return f"provenance/{slug}-{finding.finding_id.rsplit('__', 1)[-1][:8]}"


def execute(
    subject: SubjectApp,
    finding: Finding,
    engineering: EngineeringPlan,
    *,
    repo: str,
    base: str,
    run_tests: bool = True,
) -> dict[str, str]:
    """Apply the plan on an isolated branch, backtest it, and open the proposals.

    Nothing here touches the subject repository's working tree, and there is no
    path from this function to a merge.
    """
    edits = [github.Edit(path=e.path, old=e.old, new=e.new) for e in engineering.edits]
    if not edits:
        raise ValueError("plan contains no edits")

    outcome = backtest.TestOutcome(ran=False, note="not requested")
    if run_tests:
        with github.isolated_branch(subject, _branch_name(finding) + "-test", f"origin/{base}") as tree:
            for edit in edits:
                failure = edit.apply_to(tree)
                if failure:
                    raise RuntimeError(f"edit does not apply: {failure}")
            outcome = backtest.run_scoring_tests(tree)

    body = (
        f"{engineering.pr_body}\n\n"
        f"## Backtest\n\n{outcome.as_markdown()}\n\n"
        f"## Argument against this change\n\n{engineering.dissent}\n\n"
        f"---\n"
        f"Opened by **Provenance** from {len(finding.supporting_paper_ids)} appraised papers "
        f"(tiers {finding.tier_counts}), confidence {finding.confidence:.2f}. "
        f"Every quoted claim was verified against its source text. "
        f"This is a draft: no agent can merge it."
    )

    issue_url = github.open_issue(
        repo=repo,
        title=engineering.issue_title,
        body=engineering.issue_body,
    )
    pr_url = github.open_pull_request(
        subject,
        repo=repo,
        branch=_branch_name(finding),
        base=base,
        title=engineering.pr_title,
        body=body,
        edits=edits,
        commit_message=engineering.commit_message,
        draft=True,
    )
    return {"issue": issue_url, "pull_request": pr_url, "backtest": outcome.as_markdown()}
