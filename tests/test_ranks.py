import pytest

from researchmatch.ranks import is_faculty, normalize_rank


@pytest.mark.parametrize("title,rank", [
    ("Professor", "professor"),
    ("Associate Professor", "associate_professor"),
    ("Assistant Professor", "assistant_professor"),
    ("Assistant Professor, Teaching Stream", "assistant_professor_teaching"),
    ("Associate Professor,  Teaching Stream", "associate_professor_teaching"),
    ("Professor, Teaching Stream", "professor_teaching"),
    ("Professor Emeritus", "emeritus"),
    ("Associate Professor, Teaching Stream Emeritus", "emeritus"),
    ("University Professor Emerita", "emeritus"),
    ("Assistant Professor, Status-Only", "status_only"),
    ("Assistant Professor, Status Only", "status_only"),
    ("Adjunct", "adjunct"),
    ("Visiting Professor", "visiting"),
    ("Lecturer", "lecturer"),
    ("Graduate Administrator", "unknown"),
])
def test_normalize_rank(title, rank):
    assert normalize_rank(title) == rank


@pytest.mark.parametrize("title", [
    "Postdoctoral Fellow", "Post-doc", "PhD Student", "Graduate Student",
    "Research Associate", "Graduate Administrator", "Undergraduate Coordinator",
    "Assistant to the Chair", "Business Officer",
])
def test_non_faculty_excluded(title):
    assert not is_faculty(title)


@pytest.mark.parametrize("title", ["Professor", "Professor Emeritus", "Adjunct Professor", "Lecturer"])
def test_faculty_included(title):
    assert is_faculty(title)
