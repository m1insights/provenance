from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version


REQUIREMENTS_PATH = Path(__file__).parents[1] / "requirements.txt"


def test_google_api_core_requirement_admits_only_verified_firestore_routing_version():
    requirements = [
        Requirement(line)
        for line in REQUIREMENTS_PATH.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    api_core = next(
        (requirement for requirement in requirements if requirement.name == "google-api-core"),
        Requirement("google-api-core"),
    )

    assert Version("2.34.0") in api_core.specifier
    assert Version("2.33.0") not in api_core.specifier
    assert Version("2.34.1") not in api_core.specifier
    assert Version("2.35.0") not in api_core.specifier
