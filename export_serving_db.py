"""Export the slim, compressed database the deployed API serves from.

    python export_serving_db.py            # -> deploy/research_match.db.gz

Run after build_embeddings.py, then commit deploy/research_match.db.gz and push: Render redeploys with the
new data. Keeps only what search needs (faculty, papers, profile/paper vectors for the configured model);
department/topic vectors are build-time inputs only, and the explanation cache (derived from students'
queries) is dropped because the file is committed to a public repo.
"""
import gzip
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from researchmatch.config import PROJECT_ROOT, load_settings

OUT = PROJECT_ROOT / "deploy" / "research_match.db.gz"


def main() -> int:
    s = load_settings()
    model = s.embedding.get("model")
    with tempfile.TemporaryDirectory() as tmp:
        slim = Path(tmp) / "slim.db"
        src = sqlite3.connect(s.database_path)
        src.execute("VACUUM INTO ?", (str(slim),))
        src.close()
        conn = sqlite3.connect(slim)
        with conn:
            conn.execute("DELETE FROM embeddings WHERE model != ? OR kind NOT IN ('profile', 'paper')", (model,))
            # cached explanations are derived from what students typed: never ship them in the repo
            conn.execute("DROP TABLE IF EXISTS explanations")
        conn.execute("VACUUM")
        n_prof = conn.execute("SELECT COUNT(*) FROM embeddings WHERE kind='profile'").fetchone()[0]
        conn.close()
        if not n_prof:
            print(f"no profile vectors for {model!r}; run build_embeddings.py first", file=sys.stderr)
            return 1
        OUT.parent.mkdir(exist_ok=True)
        with slim.open("rb") as f, gzip.open(OUT, "wb", compresslevel=9) as g:
            shutil.copyfileobj(f, g)
        print(f"{OUT.relative_to(PROJECT_ROOT)}: {slim.stat().st_size / 1e6:.1f} MB -> "
              f"{OUT.stat().st_size / 1e6:.1f} MB gzipped, {n_prof} profiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
