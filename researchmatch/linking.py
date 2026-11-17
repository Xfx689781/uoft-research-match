"""Entity linking: department-page faculty record -> OpenAlex author record(s).

confidence = 0.50 * name + 0.25 * affiliation + 0.25 * topic   (each component in [0, 1])

Decisions:
  accepted   confidence >= ACCEPT, name >= 0.9, and no near-tie with a distinct candidate
  review     anything plausible but uncertain (written to review_matches.csv; never auto-merged)
  unmatched  no candidate reaches REVIEW_FLOOR

OpenAlex often splits one person across several author ids. A same-name, same-institution
candidate that is tiny next to the best one is treated as a split profile and merged into it,
rather than counted as a rival.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

ACCEPT = 0.75
REVIEW_FLOOR = 0.45
TIE_MARGIN = 0.10

_STOP = {"and", "of", "the", "for", "in", "to", "a", "on", "with", "theory", "methods", "systems",
         "applications", "analysis", "learning", "computer", "science", "research", "data", "study"}


# --- names --------------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    name = re.sub(r"[‐-―−]", "-", name)   # unicode hyphens/dashes; ascii-encoding would drop them
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    if "," in name:                                   # "Anderson, Ashton" -> "Ashton Anderson"
        last, _, first = name.partition(",")
        name = f"{first} {last}"
    name = re.sub(r"[.\-'’]", " ", name.lower())
    return " ".join(re.sub(r"[^a-z ]+", " ", name).split())


def name_variants(name: str) -> list[str]:
    """'Maria (Masha) Shugrina' -> ['maria shugrina', 'masha shugrina']"""
    m = re.search(r"\(([^)]+)\)", name)
    base = re.sub(r"\s*\([^)]*\)\s*", " ", name)
    out = [normalize_name(base)]
    if m:
        rest = base.split()
        out.append(normalize_name(" ".join([m.group(1)] + rest[1:])))
    return [v for v in out if v]


def _pair_score(f: str, c: str) -> float:
    ft, ct = f.split(), c.split()
    if not ft or not ct:
        return 0.0
    if ft == ct:
        return 1.0
    # last names: allow compound/hyphenated surnames to match on any shared surname token
    f_last, c_last = ft[-1], ct[-1]
    last_ok = f_last == c_last or (len(ft) > 2 and ft[-2] == c_last) or (len(ct) > 2 and ct[-2] == f_last)
    if not last_ok:
        return 0.6 * SequenceMatcher(None, f, c).ratio()
    f_first, c_first = ft[0], ct[0]
    if f_first == c_first:
        first = 1.0
    elif len(c_first) == 1 and c_first == f_first[0]:
        first = 0.8                                    # initial
    elif f_first.startswith(c_first) or c_first.startswith(f_first):
        first = 0.85                                   # "dan" / "daniel"
    elif f_first[0] == c_first[0]:
        first = 0.4
    else:
        first = 0.1
    return 0.5 + 0.5 * first


def name_score(faculty_name: str, candidate: dict) -> float:
    cands = [candidate.get("display_name") or ""] + list(candidate.get("display_name_alternatives") or [])
    cnorm = [normalize_name(c) for c in cands if c]
    return max((_pair_score(f, c) for f in name_variants(faculty_name) for c in cnorm if c), default=0.0)


# --- affiliation --------------------------------------------------------------------------

def _short(oa_id: str) -> str:
    return oa_id.rsplit("/", 1)[-1]


def affiliation_score(candidate: dict, institution_id: str, current_year: int, window: int = 6) -> float:
    inst = _short(institution_id)
    if any(_short(i.get("id", "")) == inst for i in candidate.get("last_known_institutions") or []):
        return 1.0
    for a in candidate.get("affiliations") or []:
        if _short(a.get("institution", {}).get("id", "")) == inst:
            years = a.get("years") or []
            return 0.8 if years and max(years) >= current_year - window else 0.6
    return 0.0


# --- topics -------------------------------------------------------------------------------

def _terms(texts: list[str]) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for w in re.findall(r"[a-z]+", t.lower()):
            if len(w) > 2 and w not in _STOP:
                out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def topic_score(candidate: dict, primary_fields: list[str], related_fields: list[str],
                research_terms: list[str]) -> float:
    topics = candidate.get("topics") or []
    if not topics:
        return 0.0
    total = sum(t.get("count", 1) for t in topics) or 1
    prim, rel = set(primary_fields), set(related_fields)
    field_share = sum(
        t.get("count", 1) * (1.0 if t["field"]["display_name"] in prim else 0.6 if t["field"]["display_name"] in rel else 0.0)
        for t in topics
    ) / total
    if not research_terms:
        return field_share
    fac = _terms(research_terms)
    cand = _terms([t["display_name"] for t in topics] + [t["subfield"]["display_name"] for t in topics])
    overlap = len(fac & cand) / len(fac) if fac else 0.0
    return 0.6 * field_share + 0.4 * min(1.0, 2 * overlap)


# --- decision ----------------------------------------------------------------------------

@dataclass
class ScoredCandidate:
    author: dict
    name: float
    affiliation: float
    topic: float

    @property
    def confidence(self) -> float:
        return round(0.5 * self.name + 0.25 * self.affiliation + 0.25 * self.topic, 4)

    @property
    def id(self) -> str:
        return self.author["id"]


@dataclass
class LinkDecision:
    status: str                                   # accepted | review | unmatched
    reason: str
    best: ScoredCandidate | None = None
    merged: list[ScoredCandidate] = field(default_factory=list)   # split-profile ids folded into best
    candidates: list[ScoredCandidate] = field(default_factory=list)

    @property
    def author_ids(self) -> list[str]:
        return ([self.best.id] if self.best else []) + [m.id for m in self.merged]


def score_candidates(faculty, candidates: list[dict], institution_id: str, current_year: int,
                     primary_fields: list[str], related_fields: list[str]) -> list[ScoredCandidate]:
    terms = list(faculty.research_areas) + list(faculty.research_interests)
    scored = [ScoredCandidate(
        author=c,
        name=name_score(faculty.name, c),
        affiliation=affiliation_score(c, institution_id, current_year),
        topic=topic_score(c, primary_fields, related_fields, terms),
    ) for c in candidates]
    return sorted(scored, key=lambda s: (s.confidence, s.author.get("works_count", 0)), reverse=True)


def _is_split_fragment(main: ScoredCandidate, other: ScoredCandidate) -> bool:
    mw = main.author.get("works_count", 0)
    ow = other.author.get("works_count", 0)
    return other.name >= 0.9 and other.affiliation > 0 and ow <= max(5, 0.1 * mw)


def decide(scored: list[ScoredCandidate]) -> LinkDecision:
    if not scored:
        return LinkDecision("unmatched", "no OpenAlex candidates")
    top = scored[0]
    if top.confidence < REVIEW_FLOOR:
        return LinkDecision("unmatched", f"best confidence {top.confidence:.2f} < {REVIEW_FLOOR}",
                            best=None, candidates=scored)

    # A tiny fragment profile often edges out the person's main profile on topic score. Within the
    # tie band, the main profile is the one with the most works; fragments are folded into it.
    contenders = [s for s in scored if top.confidence - s.confidence < TIE_MARGIN
                  and s.affiliation >= top.affiliation and s.name >= 0.9]
    best = max(contenders, key=lambda s: s.author.get("works_count", 0))
    merged = [s for s in scored if s is not best and _is_split_fragment(best, s)]
    rivals = sorted((s for s in scored if s is not best and s not in merged and s.name >= 0.8),
                    key=lambda s: s.confidence, reverse=True)
    if rivals and best.confidence - rivals[0].confidence < TIE_MARGIN:
        return LinkDecision("review", f"ambiguous: {rivals[0].author.get('display_name')} "
                            f"({rivals[0].confidence:.2f}) close to best ({best.confidence:.2f})",
                            best=best, merged=merged, candidates=scored)
    if best.confidence >= ACCEPT and best.name >= 0.9:
        return LinkDecision("accepted", f"confidence {best.confidence:.2f}", best=best, merged=merged,
                            candidates=scored)
    return LinkDecision("review", f"low confidence {best.confidence:.2f} (name {best.name:.2f}, "
                        f"affil {best.affiliation:.2f}, topic {best.topic:.2f})",
                        best=best, merged=merged, candidates=scored)
