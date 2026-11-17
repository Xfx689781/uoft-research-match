"""Arts & Science Drupal parser (Math, Stats), against a Stats directory page saved from a browser."""
import pytest

from conftest import FIXTURES
from researchmatch.config import Department
from researchmatch.parsers.artsci_drupal import (ArtsciDrupalParser, appointment_type_from_title,
                                                  saved_from_url)

URL = "https://www.statistics.utoronto.ca/people/directories/all-faculty"


@pytest.fixture(scope="module")
def html():
    return (FIXTURES / "stats_faculty_page1_2026-11-16.html").read_text(encoding="utf-8")


@pytest.fixture
def stats():
    return Department(id="stats", name="Department of Statistical Sciences", directory_url=URL,
                      parser="artsci_drupal")


@pytest.fixture
def parsed(html, stats):
    return ArtsciDrupalParser().parse(html, URL, stats)


def by_name(res, name):
    (r,) = [r for r in res.records if r.name == name]
    return r


def test_saved_from_url(html):
    assert saved_from_url(html) == URL


def test_counts_and_expected_total(parsed):
    assert len(parsed.records) == 10
    assert parsed.expected_total == 81


def test_full_row(parsed):
    r = by_name(parsed, "Ricardo Baptista")
    assert r.title == "Assistant Professor" and r.rank == "assistant_professor"
    assert r.appointment_type == "research_stream"
    assert r.email == "r.baptista@utoronto.ca"
    assert r.profile_url == "https://www.statistics.utoronto.ca/people/directories/all-faculty/ricardo-baptista"
    assert r.research_areas == ["Probability", "Statistical Computing"]


def test_obfuscated_at_email(parsed):
    # printed on the page as "monica.alexander[at]utoronto.ca"
    assert by_name(parsed, "Monica Alexander").email == "monica.alexander@utoronto.ca"


def test_emeritus_without_fields(parsed):
    r = by_name(parsed, "David Andrews")
    assert r.is_emeritus and r.appointment_type == "emeritus"
    assert r.email == "david@utstat.toronto.edu"
    assert r.research_areas == []


def test_limited_term_teaching_stream(parsed):
    r = by_name(parsed, "Ismaila Ba")
    assert r.rank == "assistant_professor_teaching" and r.appointment_type == "teaching_stream"


def test_emails_are_from_page(parsed, html):
    page = html.lower().replace("[at]", "@")
    assert all(r.email in page for r in parsed.records if r.email)


def test_non_directory_page_yields_nothing(stats):
    res = ArtsciDrupalParser().parse("<html><head><title>People</title></head><body><p>Hi</p></body></html>",
                                     URL, stats)
    assert res.records == [] and "no directory entries" in res.skipped[0]


SYNTH = """<div class="view-people"><div class="view-header"><p>3 Profiles Found</p></div>
<div class="views-row"><h3><a href="https://x/p/a">Ann Prof</a></h3>
  <div class="field-name-ppl-title"><div class="field-item">Professor</div></div>
  <a href="mailto:not-an-address">not-an-address</a></div>
<div class="views-row"><h3><a href="https://x/p/b">Bob Fellow</a></h3>
  <div class="field-name-ppl-title"><div class="field-item">Postdoctoral Fellow</div></div></div>
<div class="views-row"><h3><a href="https://x/p/c">Cy Sessional</a></h3>
  <div class="field-name-ppl-title"><div class="field-item">Sessional Instructor</div></div></div></div>"""


def test_filters_non_faculty_and_bad_email(stats):
    res = ArtsciDrupalParser().parse(SYNTH, URL, stats)
    assert [r.name for r in res.records] == ["Ann Prof"]
    assert res.records[0].email is None
    assert sum("not faculty" in s for s in res.skipped) == 2


@pytest.mark.parametrize("title,appt", [
    ("Professor", "research_stream"),
    ("Associate Professor, Teaching Stream", "teaching_stream"),
    ("University Professor Emeritus", "emeritus"),
    ("Assistant Professor, Status-Only", "status_only"),
    ("Adjunct Professor", "adjunct"),
])
def test_appointment_type_from_title(title, appt):
    assert appointment_type_from_title(title) == appt


# --- full "View All" saves (2026-11-16) ----------------------------------------------------

@pytest.mark.parametrize("fixture,dept_id,expected", [
    ("math_faculty_all_2026-11-16.html", "math", 139),
    ("stats_faculty_all_2026-11-16.html", "stats", 81),
])
def test_full_directory_saves(fixture, dept_id, expected):
    html = (FIXTURES / fixture).read_text(encoding="utf-8")
    dept = Department(id=dept_id, name=dept_id, directory_url=URL, parser="artsci_drupal")
    res = ArtsciDrupalParser().parse(html, saved_from_url(html), dept)
    assert res.expected_total == expected
    assert len(res.records) == expected                 # everyone listed is faculty; nobody dropped
    assert len({r.id for r in res.records}) == expected
    assert all(r.profile_url and r.profile_url.startswith("https://") for r in res.records)


def test_math_title_with_honorifics():
    html = (FIXTURES / "math_faculty_all_2026-11-16.html").read_text(encoding="utf-8")
    dept = Department(id="math", name="Mathematics", directory_url=URL, parser="artsci_drupal")
    r = next(r for r in ArtsciDrupalParser().parse(html, URL, dept).records if r.name == "James Arthur")
    assert r.title == "University Professor Emeritus, FRS, FRSC" and r.is_emeritus
