"""Minimal OpenAlex client: disk cache, request spacing, cost tracking, budget stop."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

BASE = "https://api.openalex.org"

AUTHOR_FIELDS = "id,display_name,display_name_alternatives,works_count,cited_by_count,last_known_institutions,affiliations,topics"
WORK_FIELDS = "id,doi,display_name,publication_year,publication_date,type,abstract_inverted_index,primary_location,topics"
SKIP_WORK_TYPES = {"paratext", "erratum", "retraction", "peer-review", "editorial", "letter", "other"}


class BudgetExhausted(RuntimeError):
    pass


class OpenAlexClient:
    def __init__(self, cache_dir: Path, user_agent: str, api_key: str | None = None,
                 mailto: str | None = None, min_interval_s: float = 0.15, max_cost_usd: float | None = None):
        self.cache_dir = cache_dir
        self.api_key, self.mailto = api_key, mailto
        self.min_interval_s = min_interval_s
        self.max_cost_usd = max_cost_usd
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.spent_usd = 0.0
        self.calls = self.cache_hits = 0
        self._last = 0.0

    def get(self, path: str, params: dict) -> dict:
        query = urlencode(sorted(params.items()))
        key = f"{path}?{query}"                       # api_key / mailto deliberately not part of the key
        cache = self.cache_dir / f"{hashlib.sha1(key.encode()).hexdigest()}.json"
        if cache.exists():
            self.cache_hits += 1
            return json.loads(cache.read_text(encoding="utf-8"))

        if self.max_cost_usd is not None and self.spent_usd >= self.max_cost_usd:
            raise BudgetExhausted(f"--max-cost ${self.max_cost_usd:.3f} reached")

        send = dict(params)
        if self.api_key:
            send["api_key"] = self.api_key
        if self.mailto:
            send["mailto"] = self.mailto

        wait = self.min_interval_s - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(3):
            self._last = time.monotonic()
            r = self.session.get(f"{BASE}{path}", params=send, timeout=60)
            if r.status_code == 429:
                if "budget" in r.text.lower():           # daily budget gone: retrying won't help
                    raise BudgetExhausted(f"OpenAlex 429: {r.text[:200]}")
                time.sleep(2 ** attempt)                 # per-second rate limit: back off
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            break
        if r.status_code == 429:
            raise BudgetExhausted(f"OpenAlex 429: {r.text[:200]}")
        r.raise_for_status()
        data = r.json()
        self.calls += 1
        self.spent_usd += float(data.get("meta", {}).get("cost_usd") or 0)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data

    # -- endpoints -------------------------------------------------------------------
    def institution_by_ror(self, ror: str) -> dict:
        return self.get(f"/institutions/ror:{ror}", {})

    def search_authors(self, name: str, institution_id: str | None, per_page: int = 10) -> list[dict]:
        params = {"search": name, "per_page": per_page, "select": AUTHOR_FIELDS}
        if institution_id:
            params["filter"] = f"affiliations.institution.id:{institution_id}"
        return self.get("/authors", params)["results"]

    def authors_by_id(self, ids: list[str]) -> list[dict]:
        short = "|".join(i.rsplit("/", 1)[-1] for i in ids)
        return self.get("/authors", {"filter": f"openalex:{short}", "select": AUTHOR_FIELDS})["results"]

    def recent_works(self, author_ids: list[str], since_year: int) -> list[dict]:
        """Most recent 100 works (first page only: deeper paging needs an API key and isn't needed here)."""
        short = "|".join(i.rsplit("/", 1)[-1] for i in author_ids)
        data = self.get("/works", {
            "filter": f"author.id:{short},publication_year:>{since_year - 1}",
            "sort": "publication_date:desc",
            "per_page": 100,
            "select": WORK_FIELDS,
        })
        return data["results"]


def reconstruct_abstract(inverted: dict | None) -> str | None:
    if not inverted:
        return None
    positions = [(pos, word) for word, poss in inverted.items() for pos in poss]
    if not positions:
        return None
    return " ".join(w for _, w in sorted(positions))
