"""Search professors by research interests.

    python search.py "probabilistic machine learning and Bayesian inference"
    python search.py "causal inference in healthcare data" --dept stats --dept cs -k 10
    python search.py "algebraic topology" --no-emeriti
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import argparse  # noqa: E402
import sys  # noqa: E402

from researchmatch import db  # noqa: E402
from researchmatch.config import load_settings  # noqa: E402
from researchmatch.embedding import from_settings  # noqa: E402
from researchmatch.index_store import load_index  # noqa: E402


def print_results(query, results):
    print(f'\n### "{query}"')
    if not results:
        print("  (no results)")
    for rank, r in enumerate(results, 1):
        p = r.professor
        flags = []
        if p.is_emeritus:
            flags.append("emeritus")
        if p.accepting_students is False:
            flags.append("not accepting new grad students")
        if p.link_status != "accepted":
            flags.append("no publication data")
        depts = p.department_name + "".join(f" + {o.department_name}" for o in r.other_appointments)
        print(f"{rank}. {p.name} — {p.title}, {depts}  score={r.score:.3f} "
              f"(profile {r.profile_similarity:.3f}"
              + (f", papers {r.paper_similarity:.3f})" if r.paper_similarity is not None else ")")
              + (f"  [{'; '.join(flags)}]" if flags else ""))
        if p.research_areas:
            print(f"   areas: {', '.join(p.research_areas[:6])}")
        for h in r.top_papers:
            print(f"   - ({h.year}) {h.title[:110]}  [{h.similarity:.3f}]")
        print(f"   email: {r.email or '—'} | {p.profile_url or p.website or p.source_url}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="+")
    ap.add_argument("--dept", action="append", help="restrict to department id(s): cs, math, stats")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--no-emeriti", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    s = load_settings()
    conn = db.connect(s.database_path)
    embedder = from_settings(s)
    index = load_index(conn, embedder.name, s.ranking)
    for q in args.query:
        qv = embedder.encode([q], is_query=True)[0]
        print_results(q, index.search(qv, k=args.k, departments=args.dept, include_emeriti=not args.no_emeriti))
    return 0


if __name__ == "__main__":
    sys.exit(main())
