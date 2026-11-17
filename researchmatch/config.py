"""Loads departments.yaml and .env settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Department:
    id: str
    name: str
    directory_url: str
    parser: str
    campus: str = "St. George"
    page_type: str = ""
    access: str = "ok"
    include_sections: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenAlexSettings:
    institution_ror: str
    works_since_years: int
    min_request_interval_s: float
    cache_dir: Path
    overrides_file: Path
    review_file: Path
    api_key: str | None


@dataclass
class Settings:
    user_agent: str
    min_request_interval_s: float
    cache_dir: Path
    database_path: Path
    contact_email: str | None
    departments: list[Department]
    openalex: OpenAlexSettings

    def department(self, dept_id: str) -> Department:
        for d in self.departments:
            if d.id == dept_id:
                return d
        raise KeyError(f"Unknown department id {dept_id!r}")


_KNOWN = {"id", "name", "directory_url", "parser", "campus", "page_type", "access", "include_sections"}


def load_settings(path: Path | None = None) -> Settings:
    path = path or PROJECT_ROOT / "departments.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    depts = []
    for d in raw["departments"]:
        known = {k: v for k, v in d.items() if k in _KNOWN}
        extra = {k: v for k, v in d.items() if k not in _KNOWN}
        depts.append(Department(**known, extra=extra))

    contact = os.getenv("CONTACT_EMAIL") or None
    ua = defaults.get("user_agent", "UofTResearchMatch/0.1")
    if contact:
        ua = f"{ua} (contact: {contact})"

    interval = float(defaults.get("min_request_interval_s", 1.0))
    if interval < 1.0:
        raise ValueError("min_request_interval_s must be >= 1.0")

    oa = raw.get("openalex", {})
    openalex = OpenAlexSettings(
        institution_ror=oa.get("institution_ror", "03dbr7087"),
        works_since_years=int(oa.get("works_since_years", 6)),
        min_request_interval_s=float(oa.get("min_request_interval_s", 0.15)),
        cache_dir=PROJECT_ROOT / oa.get("cache_dir", "data/openalex_cache"),
        overrides_file=PROJECT_ROOT / oa.get("overrides_file", "match_overrides.csv"),
        review_file=PROJECT_ROOT / oa.get("review_file", "review_matches.csv"),
        api_key=os.getenv("OPENALEX_API_KEY") or None,
    )

    return Settings(
        openalex=openalex,
        user_agent=ua,
        min_request_interval_s=interval,
        cache_dir=PROJECT_ROOT / defaults.get("cache_dir", "data/raw_html"),
        database_path=PROJECT_ROOT / os.getenv("DATABASE_PATH", "data/research_match.db"),
        contact_email=contact,
        departments=depts,
    )
