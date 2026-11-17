"""FastAPI backend.

    POST /api/search          ranked professors, fast (template "why" sentences)
    POST /api/explain         Claude-written "why this match" sentences for the same search (slower, cached)
    GET  /api/professors/{id} full profile: appointments, topics, all recent papers with abstracts
    GET  /api/meta            departments, counts, data-last-updated dates
"""
from __future__ import annotations

import hmac
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .explain import Explainer, template_why
from .index_store import load_index
from .ranking import Result

MAX_QUERY_CHARS = 4000


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=MAX_QUERY_CHARS)
    departments: list[str] | None = None
    include_emeriti: bool = True
    k: int = Field(default=10, ge=1, le=30)


class RateLimiter:
    """Sliding-window limit per client: at most `limit` requests in `window` seconds."""

    def __init__(self, limit: int, window: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self.hits) > 10_000:                 # forget idle clients so memory stays bounded
                for k in [k for k, v in self.hits.items() if not v]:
                    del self.hits[k]
            return True


_LOCAL = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost", "testclient"}


def client_ip(request: Request) -> str:
    """The visitor's IP. Requests arrive via the Next.js proxy (and possibly a Cloudflare tunnel) on this
    machine, so forwarding headers are trusted only when the direct peer is local. In X-Forwarded-For the
    rightmost non-local entry is the one our own proxy added; entries to its left can be spoofed."""
    peer = request.client.host if request.client else ""
    if peer not in _LOCAL:
        return peer
    if cf := request.headers.get("cf-connecting-ip"):
        return cf.strip()
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return next((h for h in reversed(hops) if h not in _LOCAL), peer)


def match_label(score: float, top: float) -> str:
    """Raw cosine scores shift with query length and style (a paragraph scores lower than a keyword),
    so the label is relative to the best result of the same search."""
    gap = top - score
    return "strong" if gap <= 0.02 else "good" if gap <= 0.05 else "partial"


def _result_json(r: Result, why: tuple[str, str], top: float) -> dict:
    p = r.professor
    appts = [p] + r.other_appointments
    return {
        "id": p.id,
        "person_key": p.person_key,
        "name": p.name,
        "title": p.title,
        "appointments": [{"department_id": a.department_id, "department": a.department_name, "title": a.title,
                          "faculty_id": a.id, "profile_url": a.profile_url} for a in appts],
        "score": round(r.score, 4),
        "match": match_label(r.score, top),
        "why": why[0],
        "why_source": why[1],
        "top_papers": [{"title": h.title, "year": h.year, "venue": h.venue, "url": h.url,
                        "similarity": round(h.similarity, 4)} for h in r.top_papers],
        "research_areas": (p.research_areas + p.research_interests)[:8],
        "email": r.email,
        "profile_url": next((a.profile_url for a in appts if a.profile_url), None),
        "website": next((a.website for a in appts if a.website), None),
        "source_url": p.source_url,
        "is_emeritus": p.is_emeritus,
        "accepting_students": p.accepting_students,
        "notes": p.notes,
        "has_publications": p.link_status == "accepted",
    }


def create_app(db_path: Path, embedder, ranking: dict, explainer_factory=None,
               allowed_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="UofT Research Match API")
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins or ["http://localhost:3000"],
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    lock = threading.Lock()                       # sqlite connection shared across request threads
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    index = load_index(conn, embedder.name, ranking)
    explainer = (explainer_factory or Explainer)(conn)
    by_id = {p.id: p for p in index.professors}
    search_limit = RateLimiter(int(os.getenv("SEARCH_PER_MINUTE", "30")))
    explain_limit = RateLimiter(int(os.getenv("EXPLAIN_PER_MINUTE", "6")))
    # Deployed: the API is only meant to be called by the website's server, which proves it with this shared
    # secret and passes the visitor's IP in x-visitor-ip (the API itself only ever sees the website's IP).
    proxy_secret = os.getenv("PROXY_SECRET", "")

    def visitor(request: Request) -> str:
        if proxy_secret:
            if not hmac.compare_digest(request.headers.get("x-proxy-secret", ""), proxy_secret):
                raise HTTPException(403, "this API is only available through the website")
            return request.headers.get("x-visitor-ip") or "unknown"
        return client_ip(request)

    def check(limiter: RateLimiter, request: Request):
        if not limiter.allow(visitor(request)):
            raise HTTPException(429, "too many requests; please wait a minute")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    def run_search(req: SearchRequest) -> list[Result]:
        qv = embedder.encode([req.query.strip()], is_query=True)[0]
        return index.search(qv, k=req.k, departments=req.departments, include_emeriti=req.include_emeriti)

    @app.get("/api/meta")
    def meta(request: Request):
        visitor(request)
        with lock:
            depts = [dict(r) for r in conn.execute(
                "SELECT d.id, d.name, d.directory_url, d.last_scraped_at, COUNT(f.id) AS faculty "
                "FROM departments d LEFT JOIN faculty f ON f.department_id = d.id GROUP BY d.id ORDER BY d.name")]
            info = dict(conn.execute("SELECT key, value FROM build_info").fetchall())
            linked = conn.execute("SELECT MAX(linked_at) FROM openalex_links").fetchone()[0]
        dates = [d["last_scraped_at"] for d in depts if d["last_scraped_at"]] + [linked, info.get("embeddings_built_at")]
        return {
            "departments": depts,
            "data_last_updated": max(d for d in dates if d) if any(dates) else None,
            "embedding_model": info.get("embedding_model"),
            "explanations": "claude" if explainer.enabled else "template",
            "searchable_professors": int(sum(1 for row in index.profile_matrix if row.any())),
        }

    @app.post("/api/search")
    def search(req: SearchRequest, request: Request):
        check(search_limit, request)
        with lock:
            results = run_search(req)
            cached = {}
            if explainer.enabled:          # serve already-generated explanations instantly
                cached = {k: v for k, v in explainer.explain_cached_only(req.query, results).items()}
        top = results[0].score if results else 0.0
        return {"query": req.query, "results": [
            _result_json(r, cached.get(r.professor.person_key) or (template_why(r), "template"), top)
            for r in results]}

    @app.post("/api/explain")
    def explain(req: SearchRequest, request: Request):
        check(explain_limit, request)
        with lock:
            results = run_search(req)
        why = explainer.explain(req.query, results)     # network call outside the lock
        return {"query": req.query, "explanations": {k: {"why": t, "source": s} for k, (t, s) in why.items()}}

    @app.get("/api/professors/{faculty_id}")
    def professor(faculty_id: str, request: Request):
        visitor(request)
        p = by_id.get(faculty_id)
        if p is None:
            raise HTTPException(404, "professor not found")
        appts = [a for a in index.professors if a.person_key == p.person_key]
        with lock:
            papers = conn.execute(
                "SELECT w.id, w.title, w.abstract, w.year, w.pub_date, w.venue, w.type, w.url, w.doi, w.topics "
                "FROM works w JOIN faculty_works fw ON fw.work_id = w.id WHERE fw.faculty_id IN "
                f"({','.join('?' * len(appts))}) GROUP BY w.id ORDER BY w.pub_date DESC",
                [a.id for a in appts]).fetchall() if p.link_status == "accepted" else []
        return {
            "id": p.id,
            "name": p.name,
            "title": p.title,
            "appointments": [{"department_id": a.department_id, "department": a.department_name, "title": a.title,
                              "faculty_id": a.id, "profile_url": a.profile_url, "appointment_type": a.appointment_type,
                              "home_unit": a.home_unit} for a in appts],
            "email": next((a.email for a in appts if a.email), None),
            "website": next((a.website for a in appts if a.website), None),
            "profile_url": next((a.profile_url for a in appts if a.profile_url), None),
            "source_url": p.source_url,
            "research_areas": list(dict.fromkeys(x for a in appts for x in a.research_areas + a.research_interests)),
            "topics": p.topics[:20],
            "is_emeritus": p.is_emeritus,
            "accepting_students": p.accepting_students,
            "notes": list(dict.fromkeys(n for a in appts for n in a.notes)),
            "openalex_id": p.openalex_id,
            "papers": [{**dict(w), "topics": json.loads(w["topics"])} for w in papers],
        }

    return app
