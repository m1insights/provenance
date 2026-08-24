"""Guardrails are the difference between a request and a control. Prove them."""

from __future__ import annotations

from types import SimpleNamespace

from provenance.guardrails.callbacks import (
    FORBIDDEN_TOOLS,
    enforce_draft_only,
)


def _tool(name: str):
    return SimpleNamespace(name=name)


def _pr_args(**overrides) -> dict:
    return {
        "branch": "provenance/mvpa-credit-days",
        "base": "main",
        "draft": True,
        "title": "Relax MVPA credit-day target",
    } | overrides


class TestMergeIsImpossible:
    def test_every_forbidden_tool_is_blocked(self):
        for name in FORBIDDEN_TOOLS:
            result = enforce_draft_only(_tool(name), {}, None)
            assert result is not None, f"{name} was not blocked"
            assert result["status"] == "blocked"

    def test_block_explains_itself_to_the_model(self):
        """The model receives the dict as a tool result, so it must be legible."""
        result = enforce_draft_only(_tool("github_merge"), {}, None)
        assert "never merged by an agent" in result["reason"]


class TestDraftEnforcement:
    def test_valid_draft_pr_passes(self):
        assert enforce_draft_only(_tool("open_pull_request"), _pr_args(), None) is None

    def test_non_draft_is_blocked(self):
        result = enforce_draft_only(_tool("open_pull_request"), _pr_args(draft=False), None)
        assert result is not None and "must be opened as drafts" in result["reason"]

    def test_omitted_draft_flag_is_allowed(self):
        """Absent means the tool's own default applies, which is draft=True."""
        args = _pr_args()
        del args["draft"]
        assert enforce_draft_only(_tool("open_pull_request"), args, None) is None


class TestBranchConfinement:
    def test_main_is_refused(self):
        result = enforce_draft_only(_tool("open_pull_request"), _pr_args(branch="main"), None)
        assert result is not None and "outside the" in result["reason"]

    def test_human_feature_branch_is_refused(self):
        result = enforce_draft_only(
            _tool("open_pull_request"), _pr_args(branch="feature/garmin"), None
        )
        assert result is not None

    def test_path_traversal_in_branch_name_is_refused(self):
        result = enforce_draft_only(
            _tool("open_pull_request"), _pr_args(branch="provenance/../main"), None
        )
        assert result is not None and "not a safe branch name" in result["reason"]

    def test_cannot_target_another_provenance_branch_as_base(self):
        """Stacking proposals on each other hides what is actually changing."""
        result = enforce_draft_only(
            _tool("open_pull_request"), _pr_args(base="provenance/earlier"), None
        )
        assert result is not None and "target the trunk" in result["reason"]
