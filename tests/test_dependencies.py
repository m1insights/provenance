from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version


REQUIREMENTS_PATH = Path(__file__).parents[1] / "requirements.txt"


def test_google_api_core_requirement_excludes_broken_firestore_routing_release():
    requirements = [
        Requirement(line)
        for line in REQUIREMENTS_PATH.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    api_core = next(
        (requirement for requirement in requirements if requirement.name == "google-api-core"),
        Requirement("google-api-core"),
    )

    assert Version("2.35.0") not in api_core.specifier
