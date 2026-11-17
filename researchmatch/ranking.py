"""Search: query -> ranked professors with the papers that drove each match.

score = profile_weight * sim(query, profile) + (1 - profile_weight) * mean(top-k paper sims)
Paper sims are shrunk slightly for older papers; emeriti get a configurable multiplier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from .profiles import Professor


@dataclass
class PaperHit:
    work_id: str
    title: str
    year: int | None
    venue: str | None
    url: str | None
    similarity: float


@dataclass
class Result:
    professor: Professor
    score: float
    profile_similarity: float
    paper_similarity: float | None
    top_papers: list[PaperHit] = field(default_factory=list)
    other_appointments: list[Professor] = field(default_factory=list)   # same person, other departments

    @property
    def departments(self) -> list[str]:
        return [self.professor.department_id] + [p.department_id for p in self.other_appointments]

    @property
    def email(self) -> str | None:
        return self.professor.email or next((p.email for p in self.other_appointments if p.email), None)


@dataclass
class SearchIndex:
    professors: list[Professor]
    profile_matrix: np.ndarray               # (n_prof, dim), rows L2-normalized; zero row if no profile
    paper_matrices: list[np.ndarray]          # per professor: (n_papers_i, dim), aligned with professor.papers
    ranking: dict

    def search(self, query_vec: np.ndarray, k: int = 10, departments: list[str] | None = None,
               include_emeriti: bool = True) -> list[Result]:
        r = self.ranking
        w = float(r.get("profile_weight", 0.5))
        top_n = int(r.get("top_papers", 3))
        penalty = float(r.get("paper_recency_penalty", 0.10))
        emer = float(r.get("emeritus_multiplier", 0.9))
        this_year = date.today().year

        q = query_vec.astype(np.float32).ravel()
        prof_sims = self.profile_matrix @ q
        results = []
        for i, prof in enumerate(self.professors):
            if not include_emeriti and prof.is_emeritus:
                continue
            if not np.any(self.profile_matrix[i]):
                continue                               # nothing to match on
            ps = float(prof_sims[i])
            hits: list[PaperHit] = []
            paper_part = None
            pm = self.paper_matrices[i]
            if pm is not None and len(pm):
                sims = pm @ q
                ages = np.array([max(0, this_year - (p.year or this_year)) for p in prof.papers], dtype=np.float32)
                adj = sims * (1 - penalty * np.clip(ages / 6.0, 0, 1))
                order = np.argsort(-adj)[:top_n]
                paper_part = float(adj[order].mean())
                hits = [PaperHit(prof.papers[j].work_id, prof.papers[j].title, prof.papers[j].year,
                                 prof.papers[j].venue, prof.papers[j].url, float(sims[j])) for j in order]
            score = w * ps + (1 - w) * (paper_part if paper_part is not None else ps)
            if prof.is_emeritus:
                score *= emer
            results.append(Result(prof, score, ps, paper_part, hits))
        results.sort(key=lambda x: x.score, reverse=True)

        # One result per person: keep the best-scoring appointment, attach the others.
        by_person: dict[str, Result] = {}
        for res in results:
            key = res.professor.person_key
            if key in by_person:
                by_person[key].other_appointments.append(res.professor)
            else:
                by_person[key] = res
        merged = list(by_person.values())
        if departments:
            merged = [r for r in merged if set(r.departments) & set(departments)]
        return merged[:k]
