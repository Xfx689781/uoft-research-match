"""CS directory parser, against a frozen copy of the real page (2026-11-16) plus small synthetic cases."""
from collections import Counter

import pytest

from conftest import FIXTURES
from researchmatch.parsers.cs_squarespace import CSSquarespaceParser

URL = "https://web.cs.toronto.edu/people/faculty-directory"


@pytest.fixture(scope="module")
def fixture_html():
    return (FIXTURES / "cs_faculty_directory_2026-11-16.html").read_text(encoding="utf-8")


@pytest.fixture
def parsed(fixture_html, cs_dept):
    return CSSquarespaceParser().parse(fixture_html, URL, cs_dept)


def by_name(result, name):
    matches = [r for r in result.records if r.name == name]
    assert len(matches) == 1, f"{name}: {len(matches)} matches"
    return matches[0]


# --- real fixture ------------------------------------------------------------------

def test_section_counts(parsed):
    assert Counter(r.appointment_type for r in parsed.records) == {
        "research_stream": 89, "teaching_stream": 22, "emeritus": 19,
        "cross_appointed": 58, "status_only": 15, "adjunct": 11,
    }


def test_ids_unique(parsed):
    ids = [r.id for r in parsed.records]
    assert len(ids) == len(set(ids))


def test_research_stream_row(parsed):
    r = by_name(parsed, "Ishtiaque Ahmed")
    assert r.title == "Associate Professor"
    assert r.rank == "associate_professor"
    assert r.email == "ishtiaque@cs.toronto.edu"
    assert r.website == "https://www.ishtiaque.net/"
    assert r.research_areas == ["human-computer interaction", "ICTD"]
    assert "critical computing" in r.research_interests
    assert not r.is_emeritus
    assert r.id == "cs:ishtiaque-ahmed"


def test_teaching_stream_row(parsed):
    r = by_name(parsed, "Bahar Aameri")
    assert r.title == "Assistant Professor, Teaching Stream"
    assert r.rank == "assistant_professor_teaching"
    assert r.email == "bahar@cs.toronto.edu"


def test_row_missing_opening_tr_is_recovered(parsed):
    # The live page omits <tr> before Diane Horton's row.
    r = by_name(parsed, "Diane Horton")
    assert r.rank == "professor_teaching"
    assert r.email == "dianeh@cs.toronto.edu"


def test_doubled_mailto_prefix(parsed):
    # The live page links "mailto:mailto:steven.coyne@..."; the address itself is printed.
    assert by_name(parsed, "Steven Coyne").email == "steven.coyne@mail.utoronto.ca"


def test_emeritus_flag_and_note_stripped(parsed):
    r = by_name(parsed, "Ronald Baecker")
    assert r.is_emeritus and r.rank == "emeritus"
    assert r.research_areas == ["human-computer interaction", "health & assistive technologies"]
    assert not any("accepting" in a for a in r.research_areas)
    assert r.notes == ["Professor Baecker is not accepting any new graduate students."]
    assert r.accepting_students is False
    assert by_name(parsed, "Ishtiaque Ahmed").accepting_students is None   # page is silent -> unknown


def test_emeritus_outside_emeriti_section(parsed):
    r = by_name(parsed, "Eric Yu")
    assert r.appointment_type == "cross_appointed" and r.is_emeritus


def test_cross_appointed_home_unit(parsed):
    r = by_name(parsed, "Blair Armstrong")
    assert r.title == "Assistant Professor"
    assert r.home_unit == "Psychology"
    assert r.email is None


def test_status_only_strong_label(parsed):
    # this row uses <strong> instead of <b> for the label
    assert by_name(parsed, "Oana Balmau").research_areas == ["networks", "operating systems"]


def test_unicode_name(parsed):
    by_name(parsed, "François Pitt")


def test_every_email_is_printed_on_page(parsed, fixture_html):
    emails = [r.email for r in parsed.records if r.email]
    assert len(emails) == 124
    lowered = fixture_html.lower()
    for e in emails:
        assert e in lowered


# --- synthetic -----------------------------------------------------------------------

SYNTH = """
<html><body>
<h2>Research Stream Faculty</h2>
<table><tr><th>h</th></tr>
<tr><td><a href="https://x.example/">Ada Lovelace</a><br>Professor</td>
    <td>Room: BA 1</td><td><b>Research Areas:</b> algorithms; complexity</td></tr>
<tr><td>Pat Postdoc<br>Postdoctoral Fellow</td><td></td><td></td></tr>
<tr><td><a href="mailto:not an email">Bad Email</a><br>Professor</td><td></td><td></td></tr>
</table>
<h2>Graduate Students</h2>
<table><tr><td>Sam Student<br>PhD Student</td><td></td><td></td></tr></table>
</body></html>
"""


def test_synthetic_filters(cs_dept):
    res = CSSquarespaceParser().parse(SYNTH, URL, cs_dept)
    names = {r.name for r in res.records}
    assert names == {"Ada Lovelace", "Bad Email"}
    ada = next(r for r in res.records if r.name == "Ada Lovelace")
    assert ada.email is None                       # no mailto -> no email, nothing guessed
    assert ada.research_areas == ["algorithms", "complexity"]
    assert next(r for r in res.records if r.name == "Bad Email").email is None
    assert any("Pat Postdoc" in s for s in res.skipped)
    assert any("Graduate Students" in s for s in res.skipped)
