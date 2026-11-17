"""Ranking and profile assembly, using a deterministic bag-of-words embedder (no model download)."""
import hashlib
import re
import sqlite3

import numpy as np
import pytest

from researchmatch import db
from researchmatch.config import Department
from researchmatch.embedding import normalize
from researchmatch.index_store import build, load_index
from researchmatch.models import FacultyRecord
from researchmatch.profiles import assemble_profile, paper_text, recency_weight

DIM = 256
RANKING = {"profile_weight": 0.5, "top_papers": 2, "profile_mix": {"department_page": 0.25, "topics": 0.25,
           "papers": 0.5}, "recency_decay": 0.8, "paper_recency_penalty": 0.1, "emeritus_multiplier": 0.5}


class BowEmbedder:
    name = "bow-test"

    def encode(self, texts, is_query=False):
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z]+", t.lower()):
                if len(w) > 3:
                    out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1
        return normalize(out)


def add_prof(conn, dept, name, areas, papers, emeritus=False, status="accepted"):
    rec = FacultyRecord(name=name, title="Professor Emeritus" if emeritus else "Professor",
                        rank="emeritus" if emeritus else "professor", appointment_type="research_stream",
                        department_id=dept.id, department_name=dept.name, source_url="https://x",
                        is_emeritus=emeritus, research_areas=areas)
    conn.execute("INSERT INTO faculty (id, department_id, name, title, rank, appointment_type, is_emeritus, "
                 "research_areas, source_url, scraped_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (rec.id, dept.id, name, rec.title, rec.rank, rec.appointment_type, int(emeritus),
                  __import__("json").dumps(areas), "https://x", "2026-01-01"))
    conn.execute("INSERT INTO openalex_links (faculty_id, status, linked_at) VALUES (?,?,?)",
                 (rec.id, status, "2026-01-01"))
    for i, (title, abstract, year) in enumerate(papers):
        wid = f"W{rec.id}{i}"
        conn.execute("INSERT INTO works (id, title, abstract, year, pub_date) VALUES (?,?,?,?,?)",
                     (wid, title, abstract, year, f"{year}-01-01"))
        conn.execute("INSERT INTO faculty_works VALUES (?,?)", (rec.id, wid))
    conn.commit()
    return rec.id


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    for d in [("cs", "Computer Science"), ("stats", "Statistical Sciences"), ("math", "Mathematics")]:
        c.execute("INSERT INTO departments (id, name, directory_url) VALUES (?,?,?)", (d[0], d[1], "https://x"))
    cs, st, ma = (Department(id=i, name=n, directory_url="", parser="") for i, n in
                  [("cs", "Computer Science"), ("stats", "Statistical Sciences"), ("math", "Mathematics")])
    add_prof(c, cs, "Robo Learner", ["reinforcement learning", "robotics"], [
        ("Reinforcement learning for robotic manipulation", "policy gradient robots grasping", 2025),
        ("Sim-to-real transfer for legged robots", "reinforcement learning locomotion", 2023),
        ("Database indexing", "btree storage", 2021)])
    add_prof(c, st, "Bayes Stat", ["Bayesian inference"], [
        ("Variational Bayesian inference at scale", "probabilistic models posterior", 2025),
        ("Causal inference with healthcare data", "observational studies treatment effects", 2024)])
    add_prof(c, ma, "Topo Logist", ["algebraic topology"], [
        ("Homotopy groups of spheres", None, 2024)])
    add_prof(c, ma, "Old Topologist", ["algebraic topology"], [
        ("Homotopy groups of spheres revisited", None, 2024)], emeritus=True)
    add_prof(c, cs, "No Papers", ["robotics", "reinforcement learning"], [], status="unmatched")
    build(c, BowEmbedder(), RANKING, log=lambda *_: None)
    return c


def search(conn, q, **kw):
    e = BowEmbedder()
    return load_index(conn, e.name, RANKING).search(e.encode([q], is_query=True)[0], **kw)


def test_best_match_first_and_top_papers(conn):
    res = search(conn, "reinforcement learning robots", k=3)
    assert res[0].professor.name in ("Robo Learner", "No Papers")
    robo = next(r for r in res if r.professor.name == "Robo Learner")
    assert len(robo.top_papers) == 2
    assert all("Database" not in h.title for h in robo.top_papers)


def test_cross_listed_person_appears_once(tmp_path):
    c = db.connect(tmp_path / "x.db")
    for d in ("cs", "stats"):
        c.execute("INSERT INTO departments (id, name, directory_url) VALUES (?,?,?)", (d, d, "https://x"))
    paper = [("Bayesian deep learning", "uncertainty posterior", 2025)]
    a = add_prof(c, Department(id="cs", name="cs", directory_url="", parser=""), "Tim Rudner", ["AI"], paper)
    b = add_prof(c, Department(id="stats", name="stats", directory_url="", parser=""), "Tim G. J. Rudner",
                 ["Machine Learning"], paper)
    for fid in (a, b):
        c.execute("UPDATE openalex_links SET openalex_ids=? WHERE faculty_id=?", ('["https://openalex.org/A9"]', fid))
    c.commit()
    build(c, BowEmbedder(), RANKING, log=lambda *_: None)
    res = search(c, "Bayesian deep learning")
    assert len(res) == 1 and sorted(res[0].departments) == ["cs", "stats"]
    assert search(c, "Bayesian deep learning", departments=["stats"])[0].professor.name in ("Tim Rudner", "Tim G. J. Rudner")


def test_department_filter(conn):
    res = search(conn, "inference", departments=["stats"])
    assert {r.professor.department_id for r in res} == {"stats"}


def test_professor_without_papers_still_searchable(conn):
    res = search(conn, "robotics reinforcement learning", k=5)
    np_ = next(r for r in res if r.professor.name == "No Papers")
    assert np_.paper_similarity is None and np_.top_papers == []


def test_emeritus_multiplier_and_exclusion(conn):
    res = search(conn, "algebraic topology homotopy spheres", k=5)
    names = [r.professor.name for r in res]
    assert names.index("Topo Logist") < names.index("Old Topologist")
    assert "Old Topologist" not in [r.professor.name for r in search(conn, "algebraic topology", include_emeriti=False)]


def test_unmatched_professor_papers_not_used(conn):
    # papers of a professor whose OpenAlex link is not accepted are never shown
    for r in search(conn, "robotics", k=10):
        if r.professor.link_status != "accepted":
            assert r.top_papers == []


def test_incremental_build_skips_unchanged(conn):
    stats = build(conn, BowEmbedder(), RANKING, log=lambda *_: None)
    assert stats["embedded"] == 0 and stats["profiles"] == 5


def test_paper_text_falls_back_without_abstract():
    from researchmatch.profiles import Paper, Professor
    prof = Professor(id="m:x", name="X", department_id="math", department_name="Math", title="", rank="",
                     appointment_type="", is_emeritus=False, email=None, profile_url=None, website=None,
                     source_url="", home_unit=None, research_areas=["number theory"], research_interests=[],
                     notes=[], accepting_students=None, topics=[], papers=[], link_status="accepted")
    t = paper_text(Paper("W1", "On primes", None, 2024, None, None, ["Analytic Number Theory"]), prof)
    assert "Analytic Number Theory" in t and "number theory" in t


def test_recency_weighting():
    assert recency_weight(2026, 0.8, 2026) == 1.0
    assert recency_weight(2024, 0.8, 2026) == pytest.approx(0.64)
    new, old = np.eye(2, dtype=np.float32)
    v = assemble_profile(None, None, np.stack([new, old]), [2026, 2020], {"papers": 1.0}, 0.8)
    assert v[0] > v[1]


def test_profile_renormalizes_missing_components():
    d = np.array([1, 0], dtype=np.float32)
    assert np.allclose(assemble_profile(d, None, None, [], {"department_page": 0.25}, 0.8), d)
    assert assemble_profile(None, None, None, [], {}, 0.8) is None
