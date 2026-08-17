"""Run the subject application's own tests against a proposed change.

A pull request that says "this should be safe" is an opinion. One that says
"``mvpa_dayFactorDenom3_threeSessionsGetFullCredit`` now fails" is a fact, and
it is the fact a reviewer actually needs.

The subject repository pins several scoring behaviours in tests precisely so
that changing a constant is loud rather than quiet. Running those tests on the
patched tree is therefore the most honest backtest available without touching
real user data.

Verdicts come from the result bundle, never from the exit code. ``xcodebuild``
piped through anything reports the *pipe's* status, and it has been observed
to exit 0 with failing tests.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SCHEME = "tapntrack"
PROJECT = "tapntrack.xcodeproj"
DESTINATION = "platform=iOS Simulator,name=iPhone 17 Pro"

#: Suites that pin scoring behaviour. Running the whole app suite costs many
#: minutes and tells a reviewer nothing extra about a constant change.
SCORING_SUITES = (
    "tapntrackTests/VitalityIndexCalculatorTests",
    "tapntrackTests/VitalityScoreCalculatorTests",
    "tapntrackTests/VitalityPillarAggregationTests",
    "tapntrackTests/ConditionBaselineAdjusterTests",
)


@dataclass
class TestOutcome:
    ran: bool
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def total(self) -> int:
        return self.passed + self.failed

    def as_markdown(self) -> str:
        if not self.ran:
            return f"> Backtest did not run: {self.note}"
        if self.failed == 0:
            return (
                f"**{self.passed}/{self.total} scoring tests pass** against the "
                "proposed change. No pinned behaviour regressed."
            )
        listed = "\n".join(f"- `{name}`" for name in self.failures[:12])
        return (
            f"**{self.failed} of {self.total} scoring tests fail** against the "
            f"proposed change:\n\n{listed}\n\n"
            "Each failure is a behaviour the repository deliberately pinned. "
            "Review whether the pin or the constant should move."
        )


def _parse_result_bundle(bundle: Path) -> tuple[int, int, list[str]]:
    """Read verdicts out of the xcresult bundle."""
    result = subprocess.run(
        [
            "xcrun", "xcresulttool", "get", "test-results", "tests",
            "--path", str(bundle), "--format", "json",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        return 0, 0, []

    passed = failed = 0
    failures: list[str] = []

    def walk(node: dict) -> None:
        nonlocal passed, failed
        for child in node.get("children", []) or []:
            walk(child)
        status = node.get("result")
        if node.get("nodeType") == "Test Case" and status:
            if status == "Passed":
                passed += 1
            elif status in {"Failed", "Expected Failure"}:
                failed += 1
                failures.append(node.get("name", "unknown"))

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 0, 0, []
    for root in payload.get("testNodes", []) or []:
        walk(root)
    return passed, failed, failures


def run_scoring_tests(tree: Path, *, timeout: int = 1800) -> TestOutcome:
    """Run the scoring suites inside an already-patched worktree.

    Args:
        tree: A worktree with the proposed edits applied.
        timeout: Seconds before the run is abandoned.
    """
    project = tree / PROJECT
    if not project.exists():
        return TestOutcome(ran=False, note=f"no {PROJECT} at {tree}")
    if shutil.which("xcodebuild") is None:
        return TestOutcome(ran=False, note="xcodebuild is not available")

    bundle_dir = Path(tempfile.mkdtemp(prefix="provenance-xcresult-"))
    bundle = bundle_dir / "result.xcresult"

    command = [
        "xcodebuild", "test",
        "-project", str(project),
        "-scheme", SCHEME,
        "-destination", DESTINATION,
        "-resultBundlePath", str(bundle),
        "-quiet",
    ]
    for suite in SCORING_SUITES:
        command += ["-only-testing", suite]

    log.info("backtest: running %d scoring suites", len(SCORING_SUITES))
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        shutil.rmtree(bundle_dir, ignore_errors=True)
        return TestOutcome(ran=False, note=f"exceeded {timeout}s")

    try:
        if not bundle.exists():
            return TestOutcome(ran=False, note="xcodebuild produced no result bundle")
        passed, failed, failures = _parse_result_bundle(bundle)
        if passed + failed == 0:
            return TestOutcome(ran=False, note="result bundle contained no test cases")
        log.info("backtest: %d passed, %d failed", passed, failed)
        return TestOutcome(ran=True, passed=passed, failed=failed, failures=failures)
    finally:
        shutil.rmtree(bundle_dir, ignore_errors=True)
