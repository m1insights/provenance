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
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

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
        # -B rather than -b: a previous run that failed after creating the
        # branch but before pushing leaves it behind, and every subsequent
        # attempt would then die on "a branch named ... already exists". This
        # namespace belongs to the system, so resetting it is safe.
        _git(tree, "checkout", "-B", branch)
        yield tree
    finally:
        _git(repo, "worktree", "remove", "--force", str(tree), check=False)
        _git(repo, "worktree", "prune", check=False)
        # Leave no local branch behind either; the pushed remote branch is the
        # durable artefact, and a stale local one only confuses the next run.
        _git(repo, "branch", "-D", branch, check=False)
        shutil.rmtree(workdir, ignore_errors=True)


#: gRPC prints fork-safety chatter to stderr once a Firestore client exists in
#: the parent process. It is harmless and it is not the error message.
_GRPC_NOISE = re.compile(r"^[IWE]\d{4} .*(ev_poll_posix|fork|grpc)", re.IGNORECASE)


def _clean_stderr(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if line.strip() and not _GRPC_NOISE.match(line)
    ).strip()


def _token() -> str:
    """A GitHub token, from the environment or from the CLI's keyring."""
    token = settings().github_token
    if token:
        return token
    executable = shutil.which("gh")
    if executable is not None:
        result = subprocess.run(
            [executable, "auth", "token"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise RuntimeError("no GitHub token; set GITHUB_TOKEN or run `gh auth login`")


def _api(method: str, path: str, payload: dict | None = None) -> dict:
    """Call the GitHub REST API.

    Deliberately REST rather than the `gh` CLI. `gh issue create` and
    `gh pr create` go through GraphQL, and during a GitHub partial outage
    GraphQL returned 503 while REST stayed healthy -- with `gh` reporting the
    failure as the badly misleading "no git remotes found". Fewer moving parts
    and a truthful error message are both worth having here.
    """
    response = httpx.request(
        method,
        f"https://api.github.com{path}",
        json=payload,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "provenance/0.1",
        },
        timeout=60.0,
    )
    if response.status_code >= 400:
        detail = response.json().get("message", response.text[:300]) if response.content else ""
        errors = response.json().get("errors", []) if response.content else []
        raise RuntimeError(
            f"GitHub {method} {path} -> {response.status_code}: {detail} {errors}".strip()
        )
    return response.json()


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

    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    created = _api("POST", f"/repos/{repo}/issues", payload)
    return created["html_url"]


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

        created = _api(
            "POST",
            f"/repos/{repo}/pulls",
            {
                "title": title,
                "body": body,
                "head": branch,
                "base": base.split("/")[-1],
                "draft": True,
            },
        )
        return created["html_url"]


def update_pull_request(repo: str, number: int, *, body: str, title: str | None = None) -> str:
    """Rewrite an existing draft pull request's body.

    Regenerating the body is preferable to opening a replacement: the review
    conversation, and any comments already left on it, stay attached.
    """
    if settings().dry_run:
        log.info("dry run: would update %s#%d", repo, number)
        return f"DRY-RUN update {repo}#{number}"
    payload: dict = {"body": body}
    if title:
        payload["title"] = title
    return _api("PATCH", f"/repos/{repo}/pulls/{number}", payload)["html_url"]


def update_issue(repo: str, number: int, *, body: str, title: str | None = None) -> str:
    """Rewrite an existing issue's body."""
    if settings().dry_run:
        log.info("dry run: would update %s#%d", repo, number)
        return f"DRY-RUN update {repo}#{number}"
    payload: dict = {"body": body}
    if title:
        payload["title"] = title
    return _api("PATCH", f"/repos/{repo}/issues/{number}", payload)["html_url"]
