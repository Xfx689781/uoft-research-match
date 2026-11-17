"""Parser for Faculty of Arts & Science Drupal 7 people directories (Mathematics, Statistical Sciences).

Those sites block automated clients with a bot check, so pages are saved from a browser into
data/manual_html/<dept>/ and parsed from there. Best page to save (all faculty on one page):
    <site>/people/directories/all-faculty?sort_by=ppl_last_name_value&items_per_page=All

Each person is a `div.views-row` containing:
    h3 > a                         name, link to official profile page
    .field-name-ppl-title          title as printed, e.g. "Assistant Professor, Teaching Stream (Limited Term)"
    .pane-...-format-email a       email, sometimes obfuscated as "name[at]utoronto.ca"
    .field-name-fy-field-study li  "Fields of study" tags
The header "N Profiles Found" is used to detect incomplete saves.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..config import Department
from ..models import FacultyRecord
from ..ranks import is_faculty, normalize_rank
from . import ParseResult

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_SAVED_FROM_RE = re.compile(r"saved from url=\(\d+\)(\S+)")
_FOUND_RE = re.compile(r"(\d+)\s+Profiles?\s+Found", re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def saved_from_url(html: str) -> str | None:
    """Browser 'Save page as' writes the original URL in a comment at the top."""
    m = _SAVED_FROM_RE.search(html[:2000])
    return m.group(1) if m else None


def _email(row) -> str | None:
    """The address as printed. '[at]' is the site's anti-spam spelling of '@' in the printed text;
    undoing it is reading the published address, not constructing one. Anything else is rejected."""
    for a in row.select('a[href^="mailto:"]'):
        for raw in (a["href"][len("mailto:"):], a.get_text()):
            addr = re.sub(r"\s*\[at\]\s*", "@", raw.strip(), flags=re.IGNORECASE).split("?")[0]
            if _EMAIL_RE.match(addr):
                return addr.lower()
    return None


def appointment_type_from_title(title: str) -> str:
    rank = normalize_rank(title)
    if rank == "emeritus":
        return "emeritus"
    if rank in ("status_only", "adjunct", "visiting", "lecturer"):
        return rank
    if "teaching" in rank:
        return "teaching_stream"
    if re.search(r"cross[\s-]*appointed", title, re.IGNORECASE):
        return "cross_appointed"
    return "research_stream"


class ArtsciDrupalParser:
    def start_urls(self, dept: Department) -> list[str]:
        return [dept.directory_url]

    def parse(self, html: str, url: str, dept: Department) -> ParseResult:
        soup = BeautifulSoup(html, "html5lib")
        result = ParseResult()
        rows = soup.select("div.view-people div.views-row") or soup.select("div.views-row")
        if not rows:
            result.skipped.append(f"no directory entries on this page (title: {_clean(soup.title.get_text()) if soup.title else '?'})")
            return result

        header = soup.select_one("div.view-people .view-header")
        m = _FOUND_RE.search(header.get_text() if header else "")
        result.expected_total = int(m.group(1)) if m else None

        for row in rows:
            link = row.select_one("h3 a")
            title_el = row.select_one(".field-name-ppl-title .field-item") or row.select_one(".field-name-ppl-title")
            if not link or not title_el:
                result.skipped.append(f"unparseable entry {_clean(row.get_text(' '))[:80]!r}")
                continue
            name, title = _clean(link.get_text()), _clean(title_el.get_text())
            if not is_faculty(title):
                result.skipped.append(f"not faculty: {name} ({title})")
                continue
            rank = normalize_rank(title)
            appt = appointment_type_from_title(title)
            href = link.get("href", "").strip()
            result.records.append(FacultyRecord(
                name=name,
                title=title,
                rank=rank,
                appointment_type=appt,
                is_emeritus=appt == "emeritus",
                department_id=dept.id,
                department_name=dept.name,
                source_url=url,
                email=_email(row),
                profile_url=href if href.startswith("http") else None,
                website=None,                    # only on individual profile pages
                research_areas=[_clean(li.get_text()) for li in row.select(".field-name-fy-field-study li")
                                if _clean(li.get_text())],
            ))
        return result
