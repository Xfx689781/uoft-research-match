"""'Why this match' sentences.

With ANTHROPIC_API_KEY set: one Claude request per search explains every result at once, grounded only in
the professor's listed areas and the papers that drove the match. Results are cached in SQLite by
(query, professor, model). Without a key, or if the call fails, a template sentence is used instead.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from .ranking import Result

log = logging.getLogger(__name__)

MODEL = os.getenv("EXPLAIN_MODEL", "claude-opus-5-5")

SYSTEM = """You write one short explanation per professor for a University of Toronto student who is \
looking for a research supervisor. The student's interests and, for each professor, their listed research \
areas, research topics, and the recent papers that best matched the student's interests are given.

For each professor, write 1-2 plain sentences (at most 45 words) saying concretely how their recent work \
connects to what the student described, naming a specific paper or topic. Use only the information \
provided: do not claim anything about the professor (availability, lab size, funding, reputation, \
methods) that isn't in it. If the connection is weak or only partial, say so plainly."""

SCHEMA = {
    "type": "object",
    "properties": {
        "explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "why": {"type": "string"}},
                "required": ["id", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["explanations"],
    "additionalProperties": False,
}

CACHE_DDL = """CREATE TABLE IF NOT EXISTS explanations (
    cache_key  TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL
)"""


def template_why(r: Result) -> str:
    p = r.professor
    focus = p.research_areas[:3] or [t["name"] for t in p.topics[:3]]
    parts = []
    if focus:
        parts.append(f"Works on {', '.join(focus)}.")
    if r.top_papers:
        h = r.top_papers[0]
        parts.append(f"Most relevant recent paper: “{h.title}”" + (f" ({h.year})." if h.year else "."))
    return " ".join(parts) or "Matched on the research description from the department page."


def _key(query: str, r: Result, model: str) -> str:
    q = " ".join(query.lower().split())
    return hashlib.sha1(f"{model}|{q}|{r.professor.person_key}".encode()).hexdigest()


def _prompt_item(r: Result) -> dict:
    p = r.professor
    return {
        "id": p.person_key,
        "name": p.name,
        "departments": [p.department_name] + [o.department_name for o in r.other_appointments],
        "research_areas": (p.research_areas + p.research_interests)[:12],
        "topics": [t["name"] for t in p.topics[:8]],
        "matching_papers": [{"title": h.title, "year": h.year} for h in r.top_papers],
    }


class Explainer:
    def __init__(self, conn, api_key: str | None = None, model: str = MODEL):
        self.conn = conn
        self.model = model
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY")
        self._client = None
        conn.execute(CACHE_DDL)
        conn.commit()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _client_or_none(self):
        if not self.enabled:
            return None
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key, max_retries=2, timeout=60.0)
        return self._client

    def explain_cached_only(self, query: str, results: list[Result]) -> dict[str, tuple[str, str]]:
        """Cache lookups only - never calls the API (used by the fast search endpoint)."""
        out = {}
        for r in results:
            row = self.conn.execute("SELECT text FROM explanations WHERE cache_key=?",
                                    (_key(query, r, self.model),)).fetchone()
            if row:
                out[r.professor.person_key] = (row[0], "cache")
        return out

    def explain(self, query: str, results: list[Result]) -> dict[str, tuple[str, str]]:
        """Returns {person_key: (text, source)} where source is 'llm', 'cache' or 'template'."""
        out: dict[str, tuple[str, str]] = {}
        todo = []
        for r in results:
            row = self.conn.execute("SELECT text FROM explanations WHERE cache_key=?",
                                    (_key(query, r, self.model),)).fetchone()
            if row:
                out[r.professor.person_key] = (row[0], "cache")
            else:
                todo.append(r)

        if todo and (client := self._client_or_none()):
            try:
                generated = self._call(client, query, todo)
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                with self.conn:
                    for r in todo:
                        text = generated.get(r.professor.person_key)
                        if text:
                            out[r.professor.person_key] = (text, "llm")
                            self.conn.execute(
                                "INSERT OR REPLACE INTO explanations VALUES (?,?,?,?)",
                                (_key(query, r, self.model), text, self.model, now))
            except Exception as e:                      # never let explanations break search
                log.warning("explanation call failed, using templates: %s", e)

        for r in results:
            out.setdefault(r.professor.person_key, (template_why(r), "template"))
        return out

    def _call(self, client, query: str, results: list[Result]) -> dict[str, str]:
        payload = {"student_interests": query, "professors": [_prompt_item(r) for r in results]}
        resp = client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                       # re-run on another model if this one declines
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        if resp.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"explanation stopped: {resp.stop_reason}")
        text = next(b.text for b in resp.content if b.type == "text")
        return {e["id"]: e["why"].strip() for e in json.loads(text)["explanations"] if e.get("why")}
