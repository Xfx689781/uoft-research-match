import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from researchmatch.config import Department  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

CS_SECTIONS = {
    "Research Stream Faculty": "research_stream",
    "Teaching Stream Faculty": "teaching_stream",
    "Professors Emeriti": "emeritus",
    "Cross-Appointed Faculty": "cross_appointed",
    "Status-Only Faculty": "status_only",
    "Adjunct Faculty": "adjunct",
}


@pytest.fixture
def cs_dept():
    return Department(
        id="cs",
        name="Department of Computer Science",
        directory_url="https://web.cs.toronto.edu/people/faculty-directory",
        parser="cs_squarespace",
        include_sections=dict(CS_SECTIONS),
    )
