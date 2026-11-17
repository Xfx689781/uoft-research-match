"""Entity linking: name/affiliation/topic scoring and accept/review/unmatched decisions.
Candidate shapes mirror real OpenAlex author records seen during the first CS run."""
from types import SimpleNamespace

import pytest

from link_openalex import clean_works
from researchmatch.linking import (affiliation_score, decide, name_score, name_variants, normalize_name,
                                   score_candidates, topic_score)
from researchmatch.openalex import reconstruct_abstract

UOFT = "https://openalex.org/I185261750"
OTHER = "https://openalex.org/I999"
CS = ["Computer Science"]
REL = ["Mathematics", "Engineering"]


def author(aid, name, works, last_known=(UOFT,), topics=(("Computer Vision", "Computer Science", 10),),
           alts=(), past=()):
    return {
        "id": f"https://openalex.org/{aid}", "display_name": name, "display_name_alternatives": list(alts),
        "works_count": works,
        "last_known_institutions": [{"id": i, "display_name": i} for i in last_known],
        "affiliations": [{"institution": {"id": i}, "years": [2025]} for i in last_known]
                        + [{"institution": {"id": i}, "years": list(y)} for i, y in past],
        "topics": [{"display_name": t, "field": {"display_name": f}, "subfield": {"display_name": t}, "count": c}
                   for t, f, c in topics],
    }


def fac(name, areas=(), interests=()):
    return SimpleNamespace(name=name, research_areas=list(areas), research_interests=list(interests))


def run(faculty, cands):
    return decide(score_candidates(faculty, cands, UOFT, 2026, CS, REL))


# --- names -----------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Alán Aspuru-Guzik", "alan aspuru guzik"),
    ("Anderson, Ashton", "ashton anderson"),
    ("Chris J. Maddison", "chris j maddison"),
])
def test_normalize_name(a, b):
    assert normalize_name(a) == b


def test_nickname_variant():
    assert name_variants("Maria (Masha) Shugrina") == ["maria shugrina", "masha shugrina"]


@pytest.mark.parametrize("faculty,candidate,lo,hi", [
    ("David Fleet", "David J. Fleet", 1.0, 1.0),           # middle initial ignored
    ("Babak Taati", "B Taati", 0.9, 0.9),                  # first initial
    ("Chris Maddison", "Christopher Maddison", 0.9, 0.95),  # prefix nickname
    ("Alán Aspuru-Guzik", "Alán Aspuru‐Guzik", 1.0, 1.0),  # unicode hyphen
    ("Angela Brown", "Angela Demke Brown", 1.0, 1.0),
    ("Bo Wang", "Bo Li", 0.0, 0.6),                        # different surname
    ("Anna Goldenberg", "Boris Goldenberg", 0.5, 0.6),     # different first name
])
def test_name_score(faculty, candidate, lo, hi):
    assert lo <= name_score(faculty, author("A1", candidate, 1)) <= hi


def test_name_score_uses_alternatives():
    assert name_score("Babak Taati", author("A1", "B Taati", 8, alts=["Babak Taati"])) == 1.0


# --- affiliation / topics -------------------------------------------------------------

def test_affiliation_levels():
    assert affiliation_score(author("A", "x", 1), UOFT, 2026) == 1.0
    assert affiliation_score(author("A", "x", 1, last_known=(OTHER,), past=[(UOFT, [2023])]), UOFT, 2026) == 0.8
    assert affiliation_score(author("A", "x", 1, last_known=(OTHER,), past=[(UOFT, [2008])]), UOFT, 2026) == 0.6
    assert affiliation_score(author("A", "x", 1, last_known=(OTHER,)), UOFT, 2026) == 0.0


def test_topic_score_prefers_department_field_and_research_terms():
    cs = author("A", "x", 1, topics=[("Reinforcement Learning in Robotics", "Computer Science", 10)])
    med = author("B", "x", 1, topics=[("Chronic Kidney Disease", "Medicine", 10)])
    terms = ["robotics", "reinforcement learning"]
    assert topic_score(cs, CS, REL, terms) > 0.9
    assert topic_score(med, CS, REL, terms) == 0.0
    assert topic_score(cs, CS, REL, []) == 1.0


# --- decisions (real-world patterns) ------------------------------------------------------

def test_clear_match_with_split_fragment_merged():   # Ashton Anderson: 110-work main + 1-work stray
    d = run(fac("Ashton Anderson"), [author("A5048789742", "Ashton Anderson", 110),
                                     author("A5129659352", "Ashton Anderson", 1)])
    assert d.status == "accepted"
    assert d.author_ids == ["https://openalex.org/A5048789742", "https://openalex.org/A5129659352"]


def test_fragment_outscoring_main_profile():         # David Fleet: 4-work fragment ranked above 237-work main
    frag = author("A5123657655", "David J. Fleet", 4, topics=[("Computer Vision", "Computer Science", 4)])
    main = author("A5035123135", "David J. Fleet", 237,
                  topics=[("Computer Vision", "Computer Science", 80), ("Optics", "Physics and Astronomy", 20)])
    d = run(fac("David Fleet", ["computer vision"]), [frag, main])
    assert d.status == "accepted"
    assert d.best.id.endswith("A5035123135")
    assert [m.id for m in d.merged] == ["https://openalex.org/A5123657655"]


def test_common_name_is_ambiguous():                 # Bo Wang: two substantial UofT records
    a = author("A5074665648", "Bo Wang", 266, topics=[("Cancer Immunotherapy", "Medicine", 10)])
    b = author("A5100408160", "Bo Wang", 291, topics=[("Single-cell transcriptomics", "Biochemistry", 10)])
    d = run(fac("Bo Wang", ["computational medicine"]), [a, b])
    assert d.status == "review" and "ambiguous" in d.reason


def test_weak_institution_far_record_not_chosen_as_main():
    a = author("A1", "Bo Wang", 266, topics=[("Machine Learning", "Computer Science", 10)])
    far = author("A2", "Bo Wang", 546, last_known=(OTHER,), past=[(UOFT, [2024])],
                 topics=[("Machine Learning", "Computer Science", 10)])
    d = run(fac("Bo Wang"), [a, far])
    assert d.best.id.endswith("A1")


def test_no_uoft_affiliation_goes_to_review_not_accept():   # e.g. status-only faculty searched without filter
    d = run(fac("Marcus Brubaker", ["AI"]), [author("A1", "Marcus A. Brubaker", 90, last_known=(OTHER,))])
    assert d.status == "review"


def test_wrong_person_unmatched():
    d = run(fac("Anna Goldenberg"), [author("A1", "Boris Petrov", 50, last_known=(OTHER,),
                                            topics=[("Soil Science", "Agricultural and Biological Sciences", 5)])])
    assert d.status == "unmatched" and d.best is None


def test_no_candidates():
    assert decide([]).status == "unmatched"


# --- works -------------------------------------------------------------------------------

def test_reconstruct_abstract():
    assert reconstruct_abstract({"Bayesian": [0], "inference": [1, 3], "is": [2]}) == "Bayesian inference is inference"
    assert reconstruct_abstract(None) is None


def _work(wid, title, typ="article", abstract=None, venue=None, landing=None):
    return {"id": wid, "display_name": title, "type": typ, "publication_year": 2024, "publication_date": "2024-01-01",
            "doi": None, "abstract_inverted_index": abstract, "topics": [],
            "primary_location": {"source": {"display_name": venue} if venue else None, "landing_page_url": landing}}


def test_clean_works_dedupes_preprint_and_drops_errata():
    works = clean_works([
        _work("W1", "Neural ODEs", typ="preprint", landing="https://arxiv.org/abs/1"),
        _work("W2", "Neural ODEs.", venue="NeurIPS", abstract={"We": [0]}),
        _work("W3", "Erratum: Neural ODEs", typ="erratum"),
    ])
    assert [w["id"] for w in works] == ["W2"]
    assert works[0]["abstract"] == "We"


def test_clean_works_arxiv_venue_fallback():
    (w,) = clean_works([_work("W1", "A preprint", typ="preprint", landing="https://arxiv.org/abs/2401.1")])
    assert w["venue"] == "arXiv"
