"""Read-only navigation of the subject repository.

The Engineer must resolve a Finding's abstract proposal ("relax the credit-day
target from 3 to 2") into a concrete edit at a real location. The Synthesist
works from the agenda's cached snapshot and routinely names a symbol that does
not exist -- it proposed ``mvpaCreditDaysTarget`` where the code actually holds
the value in ``ShiftWorkAdjuster.mvpaDayFactorDenominator``.

So the Engineer never trusts the snapshot. It reads the live files through
these tools, and every path is confined to the subject repository.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from ..config import SubjectApp

log = logging.getLogger(__name__)

#: Extensions worth searching. Keeps grep off binaries and build output.
_SEARCHABLE = {".swift", ".md", ".py", ".json", ".yml", ".yaml"}

_SKIP_DIRS = {".git", "build", "DerivedData", "Pods", ".build", "node_modules", ".venv"}

#: Guards against a single tool call returning a whole file into the context.
_MAX_LINES = 400
_MAX_MATCHES = 40


class RepoReader:
    """Path-confined reader over one subject application's checkout."""

    def __init__(self, subject: SubjectApp) -> None:
        self.subject = subject
        self.root = subject.repo_path.resolve()

    # -- internals ---------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        """Resolve a repo-relative path, refusing anything outside the root."""
        candidate = (self.root / path).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError(f"path escapes the subject repository: {path}")
        return candidate

    def _candidates(self) -> list[Path]:
        found: list[Path] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix not in _SEARCHABLE:
                continue
            if _SKIP_DIRS.intersection(path.parts):
                continue
            found.append(path)
        return found

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    # -- tools -------------------------------------------------------------

    def read_source_file(self, path: str, start_line: int = 1, line_count: int = 120) -> str:
        """Read part of a file from the subject repository.

        Args:
            path: Repository-relative path, e.g. ``synq/tapntrack/Services/X.swift``.
            start_line: 1-indexed line to start from.
            line_count: How many lines to return (capped).

        Returns:
            The requested lines, each prefixed with its line number.
        """
        try:
            target = self._resolve(path)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not target.is_file():
            return f"ERROR: no such file in the subject repository: {path}"

        lines = target.read_text(errors="replace").splitlines()
        start = max(1, start_line)
        end = min(len(lines), start + min(line_count, _MAX_LINES) - 1)
        body = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1))
        return f"{path} (lines {start}-{end} of {len(lines)})\n{body}"

    def find_symbol(self, symbol: str) -> str:
        """Locate where a symbol is declared and used.

        Use this before proposing any edit: the Finding may name a symbol that
        does not exist, and the real constant may live in a different type.

        Args:
            symbol: Identifier to look for, e.g. ``mvpaDayFactorDenominator``.

        Returns:
            Declaration sites first, then usages, as ``path:line  code``.
        """
        if not symbol.strip():
            return "ERROR: empty symbol"

        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        declaration = re.compile(
            rf"\b(let|var|func|class|struct|enum|def)\s+{re.escape(symbol)}\b"
        )

        declarations: list[str] = []
        usages: list[str] = []
        for path in self._candidates():
            try:
                lines = path.read_text(errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if not pattern.search(line):
                    continue
                entry = f"{self.rel(path)}:{number}  {line.strip()[:150]}"
                (declarations if declaration.search(line) else usages).append(entry)

        if not declarations and not usages:
            return (
                f"'{symbol}' does not appear anywhere in the subject repository. "
                "Do not propose an edit to it; search for the concept instead."
            )

        out = []
        if declarations:
            out.append("DECLARED:\n" + "\n".join(declarations[:_MAX_MATCHES]))
        if usages:
            shown = usages[:_MAX_MATCHES]
            out.append(f"USED ({len(usages)} sites):\n" + "\n".join(shown))
        return "\n\n".join(out)

    def search_source(self, pattern: str) -> str:
        """Search the subject repository for a regular expression.

        Args:
            pattern: Python regular expression.

        Returns:
            Matching lines as ``path:line  code``.
        """
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return f"ERROR: bad regular expression: {exc}"

        matches: list[str] = []
        for path in self._candidates():
            try:
                lines = path.read_text(errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if compiled.search(line):
                    matches.append(f"{self.rel(path)}:{number}  {line.strip()[:150]}")
                    if len(matches) >= _MAX_MATCHES:
                        return "\n".join(matches) + f"\n... truncated at {_MAX_MATCHES}"
        return "\n".join(matches) if matches else f"no matches for {pattern!r}"

    def companion_files(self) -> str:
        """List files that must be updated alongside any algorithm change.

        The subject repository states this as a contributor rule: an algorithm
        change must bump the version AND update the specification, or the
        sources drift apart.

        Some obligations live in a different repository. Those are listed
        separately and must NOT be edited -- a pull request cannot span two
        repositories, and an edit to a path outside this one is silently
        dropped. Mention them in the pull request body instead.

        Returns:
            Editable in-repo paths, then out-of-repo obligations.
        """
        editable = [
            self.rel(path.resolve())
            for path in self.subject.companion_files
            if path.is_file()
        ]
        lines = ["EDITABLE (in this repository):"]
        lines += [f"  {path}" for path in editable] or ["  (none)"]

        if self.subject.cross_repo_companions:
            lines.append("")
            lines.append("DO NOT EDIT (different repository -- mention in the PR body):")
            for companion in self.subject.cross_repo_companions:
                lines.append(f"  {companion.github_repo}:{companion.path}")
                lines.append(f"    {companion.why}")
        return "\n".join(lines)

    def current_diff(self) -> str:
        """Show uncommitted changes in the subject repository working tree."""
        result = subprocess.run(
            ["git", "-C", str(self.root), "diff", "--stat"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return result.stdout.strip() or "working tree clean"
