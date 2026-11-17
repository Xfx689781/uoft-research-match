"""SQLite storage for the MVP.

Kept Postgres-portable: TEXT primary keys, ISO-8601 timestamps as TEXT, list fields as JSON text
(-> JSONB in Postgres), no SQLite-only types. Embeddings (Step 3) will live in their own table so
they can move to a pgvector column.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import FacultyRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    campus          TEXT,
    directory_url   TEXT NOT NULL,
    last_scraped_at TEXT
);

CREATE TABLE IF NOT EXISTS faculty (
    id                 TEXT PRIMARY KEY,           -- "<dept>:<name-slug>"
    department_id      TEXT NOT NULL REFERENCES departments(id),
    name               TEXT NOT NULL,
    title              TEXT NOT NULL,
    rank               TEXT NOT NULL,
    appointment_type   TEXT NOT NULL,
    is_emeritus        INTEGER NOT NULL DEFAULT 0,  -- BOOLEAN in Postgres
    home_unit          TEXT,
    email              TEXT,
    profile_url        TEXT,
    website            TEXT,
    research_areas     TEXT NOT NULL DEFAULT '[]', -- JSON array
    research_interests TEXT NOT NULL DEFAULT '[]', -- JSON array
    source_url         TEXT NOT NULL,
    scraped_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_faculty_dept ON faculty(department_id);

-- Step 2: OpenAlex linking. One row per faculty member that the linker has looked at.
CREATE TABLE IF NOT EXISTS openalex_links (
    faculty_id      TEXT PRIMARY KEY REFERENCES faculty(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,                -- accepted | review | unmatched
    reason          TEXT,
    openalex_ids    TEXT NOT NULL DEFAULT '[]',   -- JSON: best id first, then merged split-profile ids
    confidence      REAL,
    name_score      REAL,
    affil_score     REAL,
    topic_score     REAL,
    author_topics   TEXT NOT NULL DEFAULT '[]',   -- JSON [{name, subfield, field, count}]
    candidates      TEXT NOT NULL DEFAULT '[]',   -- JSON, for review_matches.csv
    linked_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS works (
    id          TEXT PRIMARY KEY,                 -- OpenAlex work id
    doi         TEXT,
    title       TEXT NOT NULL,
    abstract    TEXT,
    year        INTEGER,
    pub_date    TEXT,
    venue       TEXT,
    type        TEXT,
    url         TEXT,                             -- DOI link or landing page
    topics      TEXT NOT NULL DEFAULT '[]'        -- JSON list of topic names
);

CREATE TABLE IF NOT EXISTS faculty_works (
    faculty_id  TEXT NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
    work_id     TEXT NOT NULL REFERENCES works(id),
    PRIMARY KEY (faculty_id, work_id)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def replace_department_faculty(conn: sqlite3.Connection, dept, records: list[FacultyRecord]) -> None:
    """Atomically replace one department's faculty with a fresh scrape."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.execute(
            "INSERT INTO departments (id, name, campus, directory_url, last_scraped_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "campus=excluded.campus, directory_url=excluded.directory_url, "
            "last_scraped_at=excluded.last_scraped_at",
            (dept.id, dept.name, dept.campus, dept.directory_url, now),
        )
        # Upsert, then drop people no longer listed. (A blanket DELETE would cascade away their
        # OpenAlex links on every re-scrape.)
        keep = [r.id for r in records]
        conn.execute(
            f"DELETE FROM faculty WHERE department_id = ? AND id NOT IN ({','.join('?' * len(keep))})",
            (dept.id, *keep),
        )
        conn.executemany(
            "INSERT INTO faculty (id, department_id, name, title, rank, appointment_type, is_emeritus, "
            "home_unit, email, profile_url, website, research_areas, research_interests, source_url, "
            "scraped_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "department_id=excluded.department_id, name=excluded.name, title=excluded.title, "
            "rank=excluded.rank, appointment_type=excluded.appointment_type, "
            "is_emeritus=excluded.is_emeritus, home_unit=excluded.home_unit, email=excluded.email, "
            "profile_url=excluded.profile_url, website=excluded.website, "
            "research_areas=excluded.research_areas, research_interests=excluded.research_interests, "
            "source_url=excluded.source_url, scraped_at=excluded.scraped_at",
            [(
                r.id, r.department_id, r.name, r.title, r.rank, r.appointment_type, int(r.is_emeritus),
                r.home_unit, r.email, r.profile_url, r.website, json.dumps(r.research_areas),
                json.dumps(r.research_interests), r.source_url, now,
            ) for r in records],
        )
