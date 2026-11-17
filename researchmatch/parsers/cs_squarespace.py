"""Parser for https://web.cs.toronto.edu/people/faculty-directory

The page is one static HTML document: <h2> section headings, each followed by a
<table class="blueTable">. Three row layouts occur:

  A  3 cells: [name<br>title] [email/phone/room] [research]     (research stream, emeriti)
  T  5 cells: [name] [title] [email] [phone] [room]             (teaching stream; no research text)
  C  3 cells: [name] [title<br>home unit] [research]            (cross-appointed, status-only, adjunct)

Layout is detected from the row itself, not from the section name, so a moved section still parses.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..config import Department
from ..models import FacultyRecord
from ..ranks import is_faculty, normalize_rank
from . import ParseResult

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_LABEL_RE = re.compile(r"Research\s+(Areas|Interests)\s*:", re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _lines(cell: Tag) -> list[str]:
    """Cell text split on <br>/block boundaries, empty lines dropped."""
    return [s for s in (_clean(x) for x in cell.get_text("\n").split("\n")) if s]


def _split_list(text: str) -> list[str]:
    parts = re.split(r"[,;]\s*", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _email(row: Tag) -> str | None:
    """Only an address the page actually links with mailto:. Never constructed."""
    for a in row.select('a[href^="mailto:"]'):
        # strip *repeated* prefixes too: the page has a typo'd "mailto:mailto:..." link
        addr = re.sub(r"^(mailto:)+", "", a["href"].strip(), flags=re.IGNORECASE).split("?")[0].strip()
        if _EMAIL_RE.match(addr):
            return addr.lower()
    return None


def _website(cell: Tag) -> str | None:
    a = cell.find("a", href=True)
    if a:
        href = a["href"].strip()
        if href.startswith(("http://", "https://")):
            return href
    return None


def _name(cell: Tag) -> str:
    a = cell.find("a")
    return _clean(a.get_text()) if a and _clean(a.get_text()) else _lines(cell)[0]


def _research(cell: Tag) -> tuple[list[str], list[str], list[str]]:
    # Italic notes like "Professor X is not accepting any new graduate students." are kept
    # separately (shown to students), not mixed into the research areas.
    notes = []
    for p in cell.find_all("p"):
        if p.find(["i", "em"]):
            if _clean(p.get_text(" ")):
                notes.append(_clean(p.get_text(" ")))
            p.decompose()
    text = _clean(cell.get_text(" "))
    areas: list[str] = []
    interests: list[str] = []
    matches = list(_LABEL_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = _split_list(text[m.end():end])
        (areas if m.group(1).lower() == "areas" else interests).extend(chunk)
    return areas, interests, notes


class CSSquarespaceParser:
    def start_urls(self, dept: Department) -> list[str]:
        return [dept.directory_url]

    def parse(self, html: str, url: str, dept: Department) -> ParseResult:
        # html5lib repairs markup the way browsers do (e.g. a row missing its opening <tr>);
        # lxml silently drops such rows.
        soup = BeautifulSoup(html, "html5lib")
        result = ParseResult()
        seen: set[str] = set()

        for h2 in soup.find_all("h2"):
            section = _clean(h2.get_text())
            table = h2.find_next("table")
            if table is None or table.find_previous("h2") is not h2:
                continue
            if section not in dept.include_sections:
                result.skipped.append(f"section not included: {section!r}")
                continue
            appointment_type = dept.include_sections[section]

            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if not cells:
                    continue
                rec = self._parse_row(cells, row, appointment_type, url, dept)
                if rec is None:
                    result.skipped.append(f"{section}: unparseable row {_clean(row.get_text(' '))[:80]!r}")
                    continue
                if not is_faculty(rec.title):
                    result.skipped.append(f"{section}: not faculty: {rec.name} ({rec.title})")
                    continue
                if rec.id in seen:
                    result.skipped.append(f"{section}: duplicate of earlier entry: {rec.name}")
                    continue
                seen.add(rec.id)
                result.records.append(rec)
        return result

    def _parse_row(self, cells, row, appointment_type, url, dept) -> FacultyRecord | None:
        home_unit = None
        areas: list[str] = []
        interests: list[str] = []
        notes: list[str] = []

        if len(cells) == 5:                                    # layout T
            name, title = _name(cells[0]), _clean(cells[1].get_text(" "))
            title = re.sub(r"\s+,", ",", title)
        elif len(cells) == 3:
            first = _lines(cells[0])
            if len(first) >= 2:                                # layout A
                name, title = _name(cells[0]), first[1]
            else:                                              # layout C
                second = _lines(cells[1])
                if not first or not second:
                    return None
                name, title = _name(cells[0]), second[0]
                home_unit = " ".join(second[1:]) or None
            areas, interests, notes = _research(cells[2])
        else:
            return None

        if not name or not title:
            return None
        rank = normalize_rank(title)
        return FacultyRecord(
            name=name,
            title=title,
            rank=rank,
            appointment_type=appointment_type,
            is_emeritus=appointment_type == "emeritus" or rank == "emeritus",
            home_unit=home_unit,
            department_id=dept.id,
            department_name=dept.name,
            source_url=url,
            email=_email(row),
            profile_url=None,        # the CS site has no per-person profile pages
            website=_website(cells[0]),
            research_areas=areas,
            research_interests=interests,
            notes=notes,
        )
