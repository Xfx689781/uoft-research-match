"""Scrape faculty directories listed in departments.yaml into SQLite.

    python scrape_directories.py                 # all departments, use cached HTML when present
    python scrape_directories.py --dept cs       # one department
    python scrape_directories.py --refresh       # re-download even if cached
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from researchmatch import db
from researchmatch.config import load_settings
from researchmatch.http import BlockedError, FetchError, PoliteFetcher
from researchmatch.parsers import get_parser

MAX_PAGES_PER_DEPT = 500


def scrape_department(dept, fetcher, refresh: bool):
    parser = get_parser(dept.parser)
    queue = list(parser.start_urls(dept))
    visited: set[str] = set()
    records, skipped = [], []
    fetched = cached = 0
    while queue and len(visited) < MAX_PAGES_PER_DEPT:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        html, _, from_cache = fetcher.get(url, dept.id, refresh=refresh)
        cached += from_cache
        fetched += not from_cache
        res = parser.parse(html, url, dept)
        records.extend(res.records)
        skipped.extend(res.skipped)
        queue.extend(u for u in res.next_urls if u not in visited)
    return records, skipped, fetched, cached


def print_summary(dept, records, skipped, fetched, cached):
    with_email = sum(r.email is not None for r in records)
    with_areas = sum(bool(r.research_areas) for r in records)
    print(f"\n=== {dept.name} [{dept.id}] ===")
    print(f"pages: {fetched} downloaded, {cached} from cache")
    print(f"faculty kept: {len(records)} | with email: {with_email} | with research areas: {with_areas}")
    by_type = Counter(r.appointment_type for r in records)
    email_by_type = Counter(r.appointment_type for r in records if r.email)
    for t, n in by_type.most_common():
        print(f"  {t:<18} {n:>4}  (emails: {email_by_type[t]})")
    print(f"emeriti flagged: {sum(r.is_emeritus for r in records)}")
    print(f"rank distribution: {dict(Counter(r.rank for r in records).most_common())}")
    if skipped:
        print(f"skipped ({len(skipped)}):")
        for s in skipped[:15]:
            print(f"  - {s}")
    print("sample rows:")
    rng = random.Random(0)
    for r in rng.sample(records, min(5, len(records))):
        print(f"  * {r.name} | {r.title} | {r.appointment_type}"
              f"{' | home: ' + r.home_unit if r.home_unit else ''}")
        print(f"      email={r.email} website={r.website}")
        print(f"      areas={r.research_areas} interests={r.research_interests[:4]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dept", action="append", help="department id(s); default all")
    ap.add_argument("--refresh", action="store_true", help="ignore cache and re-download")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

    settings = load_settings()
    fetcher = PoliteFetcher(settings.user_agent, settings.cache_dir, settings.min_request_interval_s)
    conn = db.connect(settings.database_path)
    depts = [settings.department(d) for d in args.dept] if args.dept else settings.departments

    failures = 0
    for dept in depts:
        try:
            records, skipped, fetched, cached = scrape_department(dept, fetcher, args.refresh)
        except NotImplementedError as e:
            note = f" (site access: {dept.access})" if dept.access != "ok" else ""
            print(f"\n=== {dept.name} [{dept.id}] === SKIPPED: {e}{note}")
            failures += 1
            continue
        except BlockedError as e:
            print(f"\n=== {dept.name} [{dept.id}] === BLOCKED: {e}")
            print("    Save the pages manually from a browser into the cache dir; see README.")
            failures += 1
            continue
        except FetchError as e:
            print(f"\n=== {dept.name} [{dept.id}] === FAILED: {e}")
            failures += 1
            continue
        if not records:
            print(f"\n=== {dept.name} [{dept.id}] === parsed 0 faculty; not overwriting DB")
            failures += 1
            continue
        db.replace_department_faculty(conn, dept, records)
        print_summary(dept, records, skipped, fetched, cached)

    print(f"\nDatabase: {settings.database_path}")
    return 1 if failures == len(depts) else 0


if __name__ == "__main__":
    sys.exit(main())
