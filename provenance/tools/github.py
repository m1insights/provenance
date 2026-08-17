"""Propose changes to the subject repository. Never merge them.

Two safety properties, both structural rather than advisory:

**The working tree is never touched.** Edits are applied inside a throwaway
``git worktree`` created from a remote ref. The subject repository here carries
33 uncommitted files across an active branch; an agent writing into that
checkout would be indistinguishable from a bad merge.

**There is no merge path.** This module exposes issue creation and draft pull
requests. It has no merge function, and `guardrails.callbacks.enforce_draft_only`
refuses anything that is not a draft on a ``provenance/*`` branch.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..config import SubjectApp, settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Edit:
    """One exact-match replacement.

    Exact old/new rather than a line range: line numbers drift between the
    snapshot an agent read and the ref the edit lands on, and a drifted line
    range corrupts a file silently. A string that no longer matches simply
    fails.
    """

    path: str
    old: str
    new: str

    def apply_to(self, root: Path) -> str | None:
        """Apply in place. Returns a failure reason, or ``None`` on success."""
        target = (root / self.path).resolve()
        if not target.is_relative_to(root.resolve()):
            return f"path escapes the repository: {self.path}"
        if not target.is_file():
            return f"no such file: {self.path}"

        content = target.read_text()
        occurrences = content.count(self.old)
        if occurrences == 0:
            return f"text to replace not found in {self.path}: {self.old[:90]!r}"
        if occurrences > 1:
            return (
                f"text appears {occurrences} times in {self.path}; "
                "an ambiguous edit is refused. Include surrounding context."
            )
        target.write_text(content.replace(self.old, self.new, 1))
        return None


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


@contextmanager
def isolated_branch(subject: SubjectApp, branch: str, base: str):
    """A disposable worktree at ``base``, on a new ``branch``.

    Yields the worktree path. Removed on exit whether or not the body raised,
    so a failed proposal leaves no state behind.
    """
    repo = subject.repo_path
    _git(repo, "fetch", "origin", base.split("/")[-1])

    workdir = Path(tempfile.mkdtemp(prefix="provenance-"))
    tree = workdir / "tree"
    try:
        _git(repo, "worktree", "add", "--detach", str(tree), base)
        _git(tree, "checkout", "-b", branch)
        yield tree
    finally:
        _git(repo, "worktree", "remove", "--force", str(tree), check=False)
        _git(repo, "worktree", "prune", check=False)
        shutil.rmtree(workdir, ignore_errors=True)


def _gh(*args: str, cwd: Path | None = None) -> str:
    executable = shutil.which("gh")
    if executable is None:
        raise RuntimeError("the GitHub CLI (gh) is not installed")
    result = subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(cwd) if cwd else None,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def open_issue(repo: str, title: str, body: str, labels: list[str] | None = None) -> str:
    """Open an issue on the subject repository.

    Args:
        repo: ``owner/name``.
        title: Issue title.
        body: Markdown body, including the evidence table.
        labels: Optional labels.

    Returns:
        The issue URL, or a dry-run marker.
    """
    if settings().dry_run:
        log.info("dry run: would open issue %r on %s", title, repo)
        return f"DRY-RUN issue on {repo}: {title}"

    args = ["issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels or []:
        args += ["--label", label]
    return _gh(*args)


def open_pull_request(
    subject: SubjectApp,
    *,
    repo: str,
    branch: str,
    base: str,
    title: str,
    body: str,
    edits: list[Edit],
    commit_message: str,
    draft: bool = True,
) -> str:
    """Apply edits on an isolated branch and open a DRAFT pull request.

    Args:
        subject: The application being changed.
        repo: ``owner/name``.
        branch: Must live under ``provenance/``.
        base: Branch to target, e.g. ``launch``.
        title: Pull request title.
        body: Markdown body: evidence, backtest, dissent.
        edits: Exact-match replacements to apply.
        commit_message: Commit subject and body.
        draft: Must be True. Enforced by the guardrail callback as well.

    Returns:
        The pull request URL, or a dry-run summary including the diff.
    """
    if not draft:
        raise ValueError("open_pull_request refuses non-draft pull requests")
    if not branch.startswith("provenance/"):
        raise ValueError(f"branch {branch!r} is outside the provenance/ namespace")
    if not edits:
        raise ValueError("a pull request with no edits proposes nothing")

    remote_base = base if base.startswith("origin/") else f"origin/{base}"

    with isolated_branch(subject, branch, remote_base) as tree:
        for edit in edits:
            failure = edit.apply_to(tree)
            if failure:
                raise RuntimeError(f"edit failed, nothing was pushed: {failure}")

        diff = _git(tree, "diff").stdout
        if not diff.strip():
            raise RuntimeError("edits produced no change; nothing to propose")

        if settings().dry_run:
            log.info("dry run: %d edit(s) apply cleanly on %s", len(edits), remote_base)
            return f"DRY-RUN pull request on {repo}\nbranch: {branch}\n\n{diff}"

        _git(tree, "add", "-A")
        _git(tree, "-c", "user.name=provenance", "-c", "user.email=provenance@m1labs.io",
             "commit", "-m", commit_message)
        _git(tree, "push", "-u", "origin", branch)

        return _gh(
            "pr", "create",
            "--repo", repo,
            "--head", branch,
            "--base", base.split("/")[-1],
            "--title", title,
            "--body", body,
            "--draft",
            cwd=tree,
        )
