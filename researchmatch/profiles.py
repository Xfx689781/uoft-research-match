"""What text represents a professor and their papers, and how the profile vector is assembled."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from .embedding import normalize


@dataclass
class Paper:
    work_id: str
    title: str
    abstract: str | None
    year: int | None
    venue: str | None
    url: str | None
    topics: list[str] = field(default_factory=list)


@dataclass
class Professor:
    id: str
    name: str
    department_id: str
    department_name: str
    title: str
    rank: str
    appointment_type: str
    is_emeritus: bool
    email: str | None
    profile_url: str | None
    website: str | None
    source_url: str
    home_unit: str | None
    research_areas: list[str]
    research_interests: list[str]
    notes: list[str]
    accepting_students: bool | None
    topics: list[dict]                 # OpenAlex author topics [{name, subfield, field, count}]
    papers: list[Paper]
    link_status: str | None            # accepted | review | unmatched | None
    openalex_id: str | None = None     # primary OpenAlex author id when the link is accepted

    @property
    def person_key(self) -> str:
        """Same person listed by several departments shares one OpenAlex author id."""
        return self.openalex_id or self.id


def department_text(p: Professor) -> str | None:
    parts = []
    if p.research_areas:
        parts.append("Research areas: " + ", ".join(p.research_areas))
    if p.research_interests:
        parts.append("Research interests: " + ", ".join(p.research_interests))
    return ". ".join(parts) or None


def topics_text(p: Professor, k: int = 15) -> str | None:
    if not p.topics:
        return None
    names = [t["name"] for t in p.topics[:k]]
    subfields = list(dict.fromkeys(t["subfield"] for t in p.topics[:k]))
    return "Research topics: " + "; ".join(names) + ". Fields: " + ", ".join(subfields)


def paper_text(paper: Paper, p: Professor, abstract_chars: int = 1500) -> str:
    """Title + abstract. Many math/stats works have no abstract in OpenAlex: then fall back to
    title + the work's topics + the professor's department-page research areas."""
    if paper.abstract:
        return f"{paper.title}. {paper.abstract[:abstract_chars]}"
    extra = []
    if paper.topics:
        extra.append("Topics: " + ", ".join(paper.topics[:5]))
    if p.research_areas:
        extra.append("Area: " + ", ".join(p.research_areas[:5]))
    return ". ".join([paper.title] + extra)


def recency_weight(year: int | None, decay: float, this_year: int | None = None) -> float:
    this_year = this_year or date.today().year
    age = max(0, this_year - (year or this_year - 6))
    return decay ** age


def assemble_profile(dept_vec: np.ndarray | None, topics_vec: np.ndarray | None,
                     paper_vecs: np.ndarray | None, paper_years: list[int | None],
                     mix: dict, decay: float) -> np.ndarray | None:
    """Weighted mean of the available components; weights renormalize when a component is missing."""
    comps, weights = [], []
    if dept_vec is not None:
        comps.append(dept_vec); weights.append(mix.get("department_page", 0.25))
    if topics_vec is not None:
        comps.append(topics_vec); weights.append(mix.get("topics", 0.25))
    if paper_vecs is not None and len(paper_vecs):
        w = np.array([recency_weight(y, decay) for y in paper_years], dtype=np.float32)
        comps.append(normalize((paper_vecs * w[:, None]).sum(axis=0))); weights.append(mix.get("papers", 0.5))
    if not comps:
        return None
    total = sum(weights)
    return normalize(sum(c * (w / total) for c, w in zip(comps, weights)))


# --- loading from the DB -------------------------------------------------------------------

def load_professors(conn, dept_ids: list[str] | None = None) -> list[Professor]:
    q = ("SELECT f.*, d.name AS department_name, l.status AS link_status, l.author_topics, l.openalex_ids "
         "FROM faculty f JOIN departments d ON d.id = f.department_id "
         "LEFT JOIN openalex_links l ON l.faculty_id = f.id")
    args: list = []
    if dept_ids:
        q += f" WHERE f.department_id IN ({','.join('?' * len(dept_ids))})"
        args = list(dept_ids)
    profs = []
    for r in conn.execute(q + " ORDER BY f.id", args).fetchall():
        papers = [Paper(w["id"], w["title"], w["abstract"], w["year"], w["venue"], w["url"], json.loads(w["topics"]))
                  for w in conn.execute(
                      "SELECT w.* FROM works w JOIN faculty_works fw ON fw.work_id = w.id "
                      "WHERE fw.faculty_id = ? ORDER BY w.pub_date DESC", (r["id"],))]
        accepted = r["link_status"] == "accepted"
        profs.append(Professor(
            id=r["id"], name=r["name"], department_id=r["department_id"], department_name=r["department_name"],
            title=r["title"], rank=r["rank"], appointment_type=r["appointment_type"],
            is_emeritus=bool(r["is_emeritus"]), email=r["email"], profile_url=r["profile_url"],
            website=r["website"], source_url=r["source_url"], home_unit=r["home_unit"],
            research_areas=json.loads(r["research_areas"]), research_interests=json.loads(r["research_interests"]),
            notes=json.loads(r["notes"] or "[]"),
            accepting_students=None if r["accepting_students"] is None else bool(r["accepting_students"]),
            topics=json.loads(r["author_topics"] or "[]") if accepted else [],
            papers=papers if accepted else [],
            link_status=r["link_status"],
            openalex_id=(json.loads(r["openalex_ids"] or "[]") or [None])[0] if accepted else None,
        ))
    return profs
