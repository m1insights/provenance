from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from provenance import agenda, config
from provenance.config import SubjectApp


def _subject(tmp_path: Path) -> SubjectApp:
    specification = tmp_path / "LONGEVITY_FEATURE_STACK.md"
    primary = tmp_path / "VitalityIndexCalculator.swift"
    supporting = tmp_path / "ShiftWorkAdjuster.swift"
    specification.write_text("specification-v1")
    primary.write_text('static let current = "VI v9.9.9"\nprimary-v1')
    supporting.write_text("shift-v1")
    return SubjectApp(
        key="test",
        name="Test",
        repo_path=tmp_path,
        github_repo="example/test",
        base_branch="launch",
        algorithm_doc=specification,
        algorithm_source=primary,
        agenda_supporting_sources=(supporting,),
    )


def test_agenda_sources_are_complete_and_ordered(tmp_path: Path):
    subject = _subject(tmp_path)
    assert [path.name for path in subject.agenda_sources] == [
        "LONGEVITY_FEATURE_STACK.md",
        "VitalityIndexCalculator.swift",
        "ShiftWorkAdjuster.swift",
    ]
    assert subject.exists()


@pytest.mark.parametrize("source_index", [0, 1, 2])
def test_source_digest_changes_for_every_governing_source(
    tmp_path: Path, source_index: int
):
    subject = _subject(tmp_path)
    before = agenda.source_digest(subject)
    path = subject.agenda_sources[source_index]
    path.write_text(path.read_text() + "\nchanged")
    assert agenda.source_digest(subject) != before


def test_prompt_contains_every_fingerprinted_source(tmp_path: Path):
    subject = _subject(tmp_path)
    contents = agenda._prompt_contents(subject)
    assert len(contents) == 3
    for path, rendered in zip(subject.agenda_sources, contents, strict=True):
        assert path.name in rendered
        assert path.read_text() in rendered


def test_synq_root_uses_ci_environment_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SYNQOLOGY_REPO_PATH", str(tmp_path))
    assert config._synq_root() == tmp_path


def test_ci_override_roots_every_synqology_agenda_source(tmp_path: Path):
    environment = os.environ | {"SYNQOLOGY_REPO_PATH": str(tmp_path)}
    code = """
from provenance.config import SYNQOLOGY
print(SYNQOLOGY.repo_path)
for path in SYNQOLOGY.agenda_sources:
    print(path.relative_to(SYNQOLOGY.repo_path))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.stdout.splitlines() == [
        str(tmp_path),
        "LONGEVITY_FEATURE_STACK.md",
        "tapntrack/Services/VitalityIndexCalculator.swift",
        "tapntrack/Services/ShiftWorkAdjuster.swift",
    ]
