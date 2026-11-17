"""Normalize printed titles into ranks and decide who counts as faculty."""
from __future__ import annotations

import re

# Ordered: first match wins.
_RANK_PATTERNS: list[tuple[str, str]] = [
    (r"emerit", "emeritus"),
    (r"\badjunct\b", "adjunct"),
    (r"status[\s-]*only", "status_only"),
    (r"\bvisiting\b", "visiting"),
    (r"assistant professor.*teaching", "assistant_professor_teaching"),
    (r"associate professor.*teaching", "associate_professor_teaching"),
    (r"professor.*teaching", "professor_teaching"),
    (r"assistant professor", "assistant_professor"),
    (r"associate professor", "associate_professor"),
    (r"\bprofessor\b", "professor"),
    (r"\blecturer\b", "lecturer"),
]

# Titles that are never faculty, even if they contain "professor"-adjacent words.
_NON_FACULTY = re.compile(
    r"post[\s-]*doc|graduate student|ph\.?d\.? (student|candidate)|research associate|"
    r"administrat|coordinator|assistant to|manager|staff|officer",
    re.IGNORECASE,
)


def normalize_rank(title: str) -> str:
    t = re.sub(r"\s+", " ", title).strip().lower()
    for pattern, rank in _RANK_PATTERNS:
        if re.search(pattern, t):
            return rank
    return "unknown"


def is_faculty(title: str) -> bool:
    """True for professors of any rank/stream, emeriti, adjunct/status-only/visiting professors,
    and lecturers. False for students, postdocs, and staff."""
    if _NON_FACULTY.search(title):
        return False
    return normalize_rank(title) != "unknown"
