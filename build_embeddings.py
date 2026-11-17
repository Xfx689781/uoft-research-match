"""Embed professor profiles and papers for search.

    python build_embeddings.py                  # incremental: only new/changed texts are embedded
    python build_embeddings.py --model BAAI/bge-base-en-v1.5
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")   # avoids OpenBLAS allocation failures on many-core Windows

import argparse  # noqa: E402
import sys  # noqa: E402

from researchmatch import db  # noqa: E402
from researchmatch.config import load_settings  # noqa: E402
from researchmatch.embedding import from_settings  # noqa: E402
from researchmatch.index_store import build  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="override embedding.model from departments.yaml")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    s = load_settings()
    e = s.embedding
    embedder = from_settings(s, args.model)
    conn = db.connect(s.database_path)
    stats = build(conn, embedder, s.ranking)
    print(f"done: {stats}")
    if args.model and args.model != e.get("model"):
        print(f"note: search uses embedding.model from departments.yaml; set it to {args.model} to use this build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
