"""Guardrails that run as code, before a tool executes.

The distinction this module exists to make: an instruction in a prompt is a
request, and a `before_tool_callback` is a control. A model that has been asked
not to merge can still merge. A model with no merge tool, whose pull-request
tool refuses anything that is not a draft on a reserved branch, cannot.

Returning a dict from `before_tool_callback` short-circuits the call -- the
tool never runs and the model receives the dict as the tool's result, so it
learns what it did wrong and can correct course.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

#: Branch namespace this system is allowed to write. Anything else is refused,
#: which keeps an agent away from main and away from human feature branches.
BRANCH_PREFIX = "provenance/"

#: Tools that must never exist in an agent's toolset. Checked defensively at
#: call time as well, so adding one by mistake fails loudly rather than
#: silently gaining the capability.
FORBIDDEN_TOOLS = {
    "github_merge",
    "github_merge_pull_request",
    "merge_pull_request",
    "git_push_force",
    "github_delete_branch",
    "github_close_issue",
}

_BRANCH_SAFE = re.compile(r"^provenance/[a-z0-9][a-z0-9._\-/]{0,80}$")


def _block(reason: str, **extra: Any) -> dict:
    log.warning("guardrail: %s", reason)
    return {"status": "blocked", "reason": reason, **extra}


def enforce_draft_only(tool, args: dict, tool_context) -> dict | None:
    """Refuse any write that is not a draft pull request on a reserved branch.

    Returns ``None`` to allow the call, or a dict to block it.
    """
    name = getattr(tool, "name", "") or getattr(tool, "__name__", "")

    if name in FORBIDDEN_TOOLS:
        return _block(
            f"{name!r} is not available to this system. Changes to the subject "
            "application are proposed for human review and are never merged by "
            "an agent.",
            tool=name,
        )

    if name in {"open_pull_request", "github_open_pr"}:
        if args.get("draft") is False:
            return _block(
                "Pull requests must be opened as drafts. A human converts the "
                "draft to ready for review after reading the evidence.",
                tool=name,
            )

        branch = str(args.get("branch", ""))
        if not branch.startswith(BRANCH_PREFIX):
            return _block(
                f"Branch {branch!r} is outside the {BRANCH_PREFIX!r} namespace. "
                "This system may only write branches it owns.",
                tool=name,
            )
        if not _BRANCH_SAFE.match(branch):
            return _block(
                f"Branch {branch!r} is not a safe branch name.",
                tool=name,
            )

        base = str(args.get("base", "main"))
        if base.startswith(BRANCH_PREFIX):
            return _block(
                "A proposal must target the trunk, not another provenance branch.",
                tool=name,
            )

    return None


def require_grounded_numbers(claims_by_id: dict[str, float | None]):
    """Build a callback that refuses copy containing unverified numbers.

    Used by the Storyteller. Any digit appearing in generated copy must trace
    to a claim value that survived grounding; otherwise the model has invented
    a figure that would be rendered onto a slide as fact.
    """
    allowed = {abs(v) for v in claims_by_id.values() if v is not None}
    number = re.compile(r"\d+(?:[.,]\d+)?")

    def callback(tool, args: dict, tool_context) -> dict | None:
        name = getattr(tool, "name", "") or getattr(tool, "__name__", "")
        if name not in {"render_creative", "emit_creative_spec"}:
            return None

        text = " ".join(
            str(value) for key, value in args.items() if isinstance(value, str)
        )
        found = {float(m.group(0).replace(",", "")) for m in number.finditer(text)}
        ungrounded = {n for n in found if n not in allowed}
        if ungrounded:
            return _block(
                f"Copy contains numbers with no verified source: "
                f"{sorted(ungrounded)}. Every figure on a creative must come "
                f"from an appraised claim. Reference the claim instead of "
                f"writing the number.",
                tool=name,
            )
        return None

    return callback
