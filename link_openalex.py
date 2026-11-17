"""Link scraped faculty to OpenAlex authors and pull their recent works.

    python link_openalex.py                       # all departments in the DB
    python link_openalex.py --dept cs --limit 40  # first 40 CS faculty (research stream first)
    python link_openalex.py --max-cost 0.08       # stop before spending more than $0.08 of API budget

Responses are cached in data/openalex_cache, so re-running is free and resumes where a budget stop left off.
Uncertain matches go to review_matches.csv; resolve them by adding rows to match_overrides.csv:

    faculty_id,openalex_ids,note
    cs:jane-doe,A5012345678,checked her homepage
    cs:john-roe,NONE,no OpenAlex record
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from types import SimpleNamespace

from researchmatch import db
from researchmatch.config import load_settings
from researchmatch.linking import LinkDecision, ScoredCandidate, decide, name_variants, score_candidates
from researchmatch.openalex import SKIP_WORK_TYPES, BudgetExhausted, OpenAlexClient, reconstruct_abstract

APPOINTMENT_ORDER = ["research_stream", "teaching_stream", "emeritus", "cross_appointed", "status_only", "adjunct"]


def load_overrides(path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    out = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ids = (row.get("openalex_ids") or "").strip()
            if row.get("faculty_id") and ids:
                out[row["faculty_id"].strip()] = [] if ids.upper() == "NONE" else [
                    i.strip() for i in ids.split("|") if i.strip()]
    return out


def faculty_rows(conn, dept_ids):
    q = "SELECT * FROM faculty" + (f" WHERE department_id IN ({','.join('?' * len(dept_ids))})" if dept_ids else "")
    rows = []
    for r in conn.execute(q, dept_ids or []):
        rows.append(SimpleNamespace(**{k: r[k] for k in r.keys()},
                                    research_areas_l=json.loads(r["research_areas"]),
                                    research_interests_l=json.loads(r["research_interests"])))
    order = {t: i for i, t in enumerate(APPOINTMENT_ORDER)}
    return sorted(rows, key=lambda r: (r.department_id, order.get(r.appointment_type, 99), r.name))


def merged_topics(authors: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for a in authors:
        for t in a.get("topics") or []:
            e = agg.setdefault(t["display_name"], {"name": t["display_name"], "subfield": t["subfield"]["display_name"],
                                                   "field": t["field"]["display_name"], "count": 0})
            e["count"] += t.get("count", 1)
    return sorted(agg.values(), key=lambda e: -e["count"])


def _norm_title(t: str) -> str:
    return " ".join("".join(ch for ch in t.lower() if ch.isalnum() or ch == " ").split())


def clean_works(raw: list[dict]) -> list[dict]:
    """Drop non-research types; collapse preprint/published duplicates (keep one with abstract, then newest)."""
    by_title: dict[str, dict] = {}
    for w in raw:
        title = (w.get("display_name") or "").strip()
        if not title or (w.get("type") or "") in SKIP_WORK_TYPES:
            continue
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        landing = loc.get("landing_page_url") or ""
        rec = {
            "id": w["id"], "doi": w.get("doi"), "title": title,
            "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
            "year": w.get("publication_year"), "pub_date": w.get("publication_date"),
            "venue": src.get("display_name") or ("arXiv" if "arxiv.org" in landing else None),
            "type": w.get("type"), "url": w.get("doi") or landing or w["id"],
            "topics": [t["display_name"] for t in (w.get("topics") or [])],
        }
        key = _norm_title(title)
        prev = by_title.get(key)
        if prev is None or (rec["abstract"] and not prev["abstract"]) or (
                bool(rec["abstract"]) == bool(prev["abstract"]) and rec["venue"] not in (None, "arXiv")
                and prev["venue"] in (None, "arXiv")):
            by_title[key] = rec
    return list(by_title.values())


def candidate_summary(s: ScoredCandidate) -> dict:
    a = s.author
    return {
        "id": a["id"], "name": a.get("display_name"), "works_count": a.get("works_count"),
        "last_known": [i.get("display_name") for i in a.get("last_known_institutions") or []],
        "top_topics": [t["display_name"] for t in (a.get("topics") or [])[:4]],
        "confidence": s.confidence, "name_score": round(s.name, 3),
        "affil_score": round(s.affiliation, 3), "topic_score": round(s.topic, 3),
    }


def save_link(conn, fac, decision: LinkDecision, authors: list[dict], works: list[dict]):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    b = decision.best
    with conn:
        conn.execute(
            "INSERT INTO openalex_links (faculty_id, status, reason, openalex_ids, confidence, name_score, "
            "affil_score, topic_score, author_topics, candidates, linked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(faculty_id) DO UPDATE SET status=excluded.status, reason=excluded.reason, "
            "openalex_ids=excluded.openalex_ids, confidence=excluded.confidence, name_score=excluded.name_score, "
            "affil_score=excluded.affil_score, topic_score=excluded.topic_score, "
            "author_topics=excluded.author_topics, candidates=excluded.candidates, linked_at=excluded.linked_at",
            (fac.id, decision.status, decision.reason, json.dumps(decision.author_ids),
             b.confidence if b else None, b.name if b else None, b.affiliation if b else None,
             b.topic if b else None,
             json.dumps(merged_topics(authors) if decision.status == "accepted" else []),
             json.dumps([candidate_summary(c) for c in decision.candidates[:5]]), now))
        conn.execute("DELETE FROM faculty_works WHERE faculty_id = ?", (fac.id,))
        for w in works:
            conn.execute(
                "INSERT INTO works (id, doi, title, abstract, year, pub_date, venue, type, url, topics) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
                "abstract=excluded.abstract, venue=excluded.venue, topics=excluded.topics",
                (w["id"], w["doi"], w["title"], w["abstract"], w["year"], w["pub_date"], w["venue"], w["type"],
                 w["url"], json.dumps(w["topics"])))
            conn.execute("INSERT OR IGNORE INTO faculty_works (faculty_id, work_id) VALUES (?, ?)", (fac.id, w["id"]))


def link_one(fac, client, inst_id, settings, overrides, dept_cfg):
    since = date.today().year - settings.openalex.works_since_years
    fac_obj = SimpleNamespace(name=fac.name, research_areas=fac.research_areas_l,
                              research_interests=fac.research_interests_l)
    primary = dept_cfg.extra.get("openalex_fields", []) if dept_cfg else []
    related = dept_cfg.extra.get("openalex_related_fields", []) if dept_cfg else []

    if fac.id in overrides:
        ids = overrides[fac.id]
        if not ids:
            return LinkDecision("unmatched", "manual override: NONE"), [], []
        authors = client.authors_by_id(ids)
        scored = score_candidates(fac_obj, authors, inst_id, date.today().year, primary, related)
        by_id = {s.id.rsplit('/', 1)[-1]: s for s in scored}
        ordered = [by_id[i.rsplit('/', 1)[-1]] for i in ids if i.rsplit('/', 1)[-1] in by_id]
        d = LinkDecision("accepted", "manual override", best=ordered[0], merged=ordered[1:], candidates=ordered)
    else:
        variants = name_variants(fac.name)
        candidates = client.search_authors(variants[0], inst_id)
        for v in variants[1:]:
            if candidates:
                break
            candidates = client.search_authors(v, inst_id)
        if not candidates:                         # e.g. status-only/adjunct faculty based elsewhere
            candidates = client.search_authors(variants[0], None, per_page=5)
        scored = score_candidates(fac_obj, candidates, inst_id, date.today().year, primary, related)
        d = decide(scored)
        authors = [d.best.author] + [m.author for m in d.merged] if d.best else []

    works = clean_works(client.recent_works(d.author_ids, since)) if d.status == "accepted" else []
    return d, authors, works


def write_review_csv(conn, path):
    rows = conn.execute(
        "SELECT f.id, f.name, f.department_id, f.title, f.appointment_type, f.research_areas, f.website, "
        "l.reason, l.candidates FROM openalex_links l JOIN faculty f ON f.id = l.faculty_id "
        "WHERE l.status = 'review' ORDER BY f.department_id, f.name").fetchall()
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["faculty_id", "faculty_name", "department", "title", "appointment_type", "research_areas",
                    "website", "reason", "candidate_rank", "candidate_id", "candidate_name", "works_count",
                    "last_known_institutions", "top_topics", "confidence", "name_score", "affil_score",
                    "topic_score"])
        for r in rows:
            for i, c in enumerate(json.loads(r["candidates"]), 1):
                w.writerow([r["id"], r["name"], r["department_id"], r["title"], r["appointment_type"],
                            "; ".join(json.loads(r["research_areas"])), r["website"], r["reason"], i,
                            c["id"].rsplit("/", 1)[-1], c["name"], c["works_count"], "; ".join(c["last_known"]),
                            "; ".join(c["top_topics"]), c["confidence"], c["name_score"], c["affil_score"],
                            c["topic_score"]])
    return len(rows)


def print_report(conn, dept_ids, client):
    print("\n=========== OpenAlex linking report ===========")
    q_dept = f" AND f.department_id IN ({','.join('?' * len(dept_ids))})" if dept_ids else ""
    depts = [r[0] for r in conn.execute("SELECT DISTINCT department_id FROM faculty f WHERE 1=1" + q_dept,
                                        dept_ids or [])]
    for d in depts:
        total = conn.execute("SELECT COUNT(*) FROM faculty WHERE department_id=?", (d,)).fetchone()[0]
        st = Counter(dict(conn.execute(
            "SELECT l.status, COUNT(*) FROM openalex_links l JOIN faculty f ON f.id=l.faculty_id "
            "WHERE f.department_id=? GROUP BY l.status", (d,)).fetchall()))
        done = sum(st.values())
        nw, na = conn.execute(
            "SELECT COUNT(DISTINCT w.id), COUNT(DISTINCT CASE WHEN w.abstract IS NOT NULL THEN w.id END) "
            "FROM works w JOIN faculty_works fw ON fw.work_id=w.id JOIN faculty f ON f.id=fw.faculty_id "
            "WHERE f.department_id=?", (d,)).fetchone()
        rate = f"{100 * st['accepted'] / done:.0f}%" if done else "n/a"
        print(f"[{d}] processed {done}/{total} | accepted {st['accepted']} | review {st['review']} | "
              f"unmatched {st['unmatched']} | auto-match rate {rate}")
        print(f"      works (since {date.today().year - 6}): {nw}, with abstract: {na}"
              f" ({100 * na / nw:.0f}%)" if nw else "      works: 0")
        by_type = conn.execute(
            "SELECT f.appointment_type, COUNT(*), SUM(l.status='accepted') FROM openalex_links l "
            "JOIN faculty f ON f.id=l.faculty_id WHERE f.department_id=? GROUP BY 1 ORDER BY 2 DESC", (d,)).fetchall()
        for t, n, a in by_type:
            print(f"      {t:<18} accepted {a}/{n}")
    print(f"\nAPI: {client.calls} calls, {client.cache_hits} cache hits, ${client.spent_usd:.4f} spent this run")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dept", action="append")
    ap.add_argument("--limit", type=int, help="max faculty per department this run")
    ap.add_argument("--max-cost", type=float, help="stop before exceeding this many USD of OpenAlex budget")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    s = load_settings()
    conn = db.connect(s.database_path)
    client = OpenAlexClient(s.openalex.cache_dir, s.user_agent, api_key=s.openalex.api_key,
                            mailto=s.contact_email, min_interval_s=s.openalex.min_request_interval_s,
                            max_cost_usd=args.max_cost)
    if not s.openalex.api_key:
        print("note: no OPENALEX_API_KEY; using the shared keyless budget ($0.10/day per IP)")
    overrides = load_overrides(s.openalex.overrides_file)
    dept_cfgs = {d.id: d for d in s.departments}

    inst = client.institution_by_ror(s.openalex.institution_ror)
    inst_id = inst["id"]
    print(f"Institution: {inst['display_name']} ({inst_id}) via ROR {s.openalex.institution_ror}")

    rows = faculty_rows(conn, args.dept)
    per_dept: Counter = Counter()
    stopped = None
    for fac in rows:
        if args.limit and per_dept[fac.department_id] >= args.limit:
            continue
        per_dept[fac.department_id] += 1
        try:
            decision, authors, works = link_one(fac, client, inst_id, s, overrides, dept_cfgs.get(fac.department_id))
        except BudgetExhausted as e:
            stopped = str(e)
            break
        save_link(conn, fac, decision, authors, works)
        if args.verbose or decision.status != "accepted":
            b = decision.best
            print(f"  {decision.status:<9} {fac.name:<28} {decision.reason}"
                  + (f" -> {b.author.get('display_name')} [{b.id.rsplit('/', 1)[-1]}]" if b else ""))

    n_review = write_review_csv(conn, s.openalex.review_file)
    print_report(conn, args.dept, client)
    print(f"review file: {s.openalex.review_file} ({n_review} faculty awaiting review)")
    if stopped:
        print(f"\nSTOPPED EARLY: {stopped}. Re-run later (cached work is kept) or set OPENALEX_API_KEY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
