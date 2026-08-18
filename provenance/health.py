"""Health checks on proposals the fleet has already opened.

Everything else in this system verifies once, before a pull request exists.
This is the only part that keeps checking afterwards, which matters because the
two worst bugs in this project were both of that shape: something that was true
when written and quietly stopped being true.

Four questions, asked nightly:

1. Does it still merge cleanly, or has the base branch moved under it?
2. Does the decision recorded in Firestore match what GitHub shows?
3. Is a companion change in another repository still outstanding?
4. Has it been sitting undecided long enough to have been forgotten?

When an answer is bad it is said on the pull request itself. A warning in a
database is a warning nobody reads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import SubjectApp
from .models import Finding, FindingStatus
from .tools import github

log = logging.getLogger(__name__)

#: A proposal open this long without a decision has been forgotten rather than
#: deliberated. Long enough not to nag, short enough to still be actionable.
STALE_AFTER_DAYS = 14


@dataclass
class Health:
    finding_id: str
    pr_url: str
    number: int
    #: Things that need a human to act.
    problems: list[str] = field(default_factory=list)
    #: Things worth knowing that are not yet wrong.
    notes: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.problems

    def as_comment(self) -> str:
        lines = ["**Provenance health check**", ""]
        lines += [f"- ⚠️ {p}" for p in self.problems]
        lines += [f"- {n}" for n in self.notes]
        lines += [
            "",
            "_Checked nightly. This appears only when something changed since "
            "the pull request was opened._",
        ]
        return "\n".join(lines)


def check(
    subject: SubjectApp, finding: Finding, *, now: datetime | None = None
) -> Health | None:
    """Inspect one proposal. Returns ``None`` when there is nothing to check."""
    number = github.pull_request_number(finding.pr_url)
    if number is None:
        return None

    now = now or datetime.now(timezone.utc)
    health = Health(finding.finding_id, finding.pr_url, number)

    try:
        pull = github.pull_request(subject.github_repo, number)
    except Exception as exc:
        log.warning("health: could not read %s: %s", finding.pr_url, exc)
        return None

    if pull.get("state") == "closed":
        return None  # a closed proposal needs no upkeep

    health.problems.extend(_merge_problems(pull))
    health.problems.extend(_decision_problems(finding, pull))
    health.problems.extend(_staleness_problems(finding, pull, now))
    health.notes.extend(_companion_notes(subject, finding))
    return health


def _merge_problems(pull: dict) -> list[str]:
    """Has the base branch moved under the proposal?

    GitHub computes mergeability asynchronously and reports ``null`` while it
    is thinking, which is not the same as a conflict. Treating ``null`` as a
    problem would raise a false alarm on every freshly opened pull request.
    """
    if pull.get("mergeable") is not False:
        return []
    base = pull.get("base", {}).get("ref", "the base branch")
    return [
        f"The diff no longer applies to `{base}`. The branch moved after this "
        f"was opened, so the change needs reworking rather than merging."
    ]


def _decision_problems(finding: Finding, pull: dict) -> list[str]:
    """Does GitHub agree with what the console recorded?

    This is the check that would have caught the approval that never reached
    GitHub, and the nightly run that reverted one.
    """
    is_draft = bool(pull.get("draft"))
    problems = []
    if finding.status is FindingStatus.APPROVED and is_draft:
        problems.append(
            "Recorded as approved in the console, but still a draft here — the "
            "approval never reached GitHub."
        )
    if finding.status is FindingStatus.REJECTED and not is_draft:
        problems.append(
            "Recorded as rejected in the console, but open for review here."
        )
    return problems


def _staleness_problems(finding: Finding, pull: dict, now: datetime) -> list[str]:
    created = pull.get("created_at")
    if not created or finding.status is not FindingStatus.OPEN:
        return []
    opened_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
    age = (now - opened_at).days
    if age < STALE_AFTER_DAYS:
        return []
    return [
        f"Open and undecided for {age} days. Either it is worth deciding or it "
        f"is worth closing; leaving it open teaches everyone to scroll past the "
        f"next one."
    ]


def _companion_notes(subject: SubjectApp, finding: Finding) -> list[str]:
    notes = []
    for companion in subject.cross_repo_companions:
        try:
            pulls = github.open_pull_requests(companion.github_repo)
        except Exception:
            # Absence of evidence is not evidence of absence. Do not raise a
            # note that cannot be substantiated.
            continue
        opened = any(
            finding.component_id in (p.get("head", {}).get("ref") or "")
            for p in pulls
        )
        if not opened:
            notes.append(
                f"`{companion.path}` in **{companion.github_repo}** has no matching "
                f"change open. Merging this alone leaves the two describing "
                f"different algorithms."
            )
    return notes


def sweep(subject: SubjectApp, findings: list[Finding], *, comment: bool = True) -> dict:
    """Check every open proposal, commenting where something has changed."""
    checked = commented = unhealthy = 0
    report: list[dict] = []

    for finding in findings:
        health = check(subject, finding)
        if health is None:
            continue
        checked += 1
        if health.healthy and not health.notes:
            continue
        if health.problems:
            unhealthy += 1
        report.append({
            "finding_id": health.finding_id,
            "pr": health.pr_url,
            "problems": health.problems,
            "notes": health.notes,
        })
        if comment and health.problems:
            try:
                github.comment(subject.github_repo, health.number, health.as_comment())
                commented += 1
            except Exception as exc:
                log.warning("health: could not comment on %s: %s", health.pr_url, exc)

    log.info(
        "health: %d checked, %d with problems, %d commented",
        checked, unhealthy, commented,
    )
    return {
        "checked": checked,
        "unhealthy": unhealthy,
        "commented": commented,
        "report": report,
    }
