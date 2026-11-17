"""Build and load embeddings for the search index (SQLite BLOBs; swap for pgvector later)."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

import numpy as np

from .embedding import normalize
from .profiles import (Professor, assemble_profile, department_text, load_professors, paper_text,
                       topics_text)
from .ranking import SearchIndex


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def _put(conn, kind, ref_id, model, text_hash, vec):
    conn.execute(
        "INSERT INTO embeddings (kind, ref_id, model, text_hash, dim, vector) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(kind, ref_id, model) DO UPDATE SET text_hash=excluded.text_hash, dim=excluded.dim, "
        "vector=excluded.vector", (kind, ref_id, model, text_hash, int(vec.shape[-1]),
                                   np.asarray(vec, dtype="<f4").tobytes()))


def _get_all(conn, kind, model) -> dict[str, tuple[str, np.ndarray]]:
    return {r[0]: (r[1], np.frombuffer(r[2], dtype="<f4"))
            for r in conn.execute("SELECT ref_id, text_hash, vector FROM embeddings WHERE kind=? AND model=?",
                                  (kind, model))}


def build(conn, embedder, ranking: dict, log=print, chunk_size: int = 256) -> dict:
    """Embed every text that changed since the last build, then (re)assemble all profile vectors."""
    t0 = time.time()
    model = embedder.name
    profs = load_professors(conn)
    abstract_chars = int(ranking.get("abstract_chars", 1500))

    # 1. collect texts
    todo: list[tuple[str, str, str]] = []     # (kind, ref_id, text)
    for p in profs:
        if (t := department_text(p)):
            todo.append(("dept", p.id, t))
        if (t := topics_text(p)):
            todo.append(("topics", p.id, t))
        for paper in p.papers:
            todo.append(("paper", f"{p.id}|{paper.work_id}", paper_text(paper, p, abstract_chars)))

    existing = {k: _get_all(conn, k, model) for k in ("dept", "topics", "paper")}
    stale = [(k, ref, txt) for k, ref, txt in todo if existing[k].get(ref, ("",))[0] != _hash(txt)]
    log(f"texts: {len(todo)} total, {len(stale)} new or changed -> embedding with {model}")

    # 2. embed what changed, committing each chunk so an interrupted run (e.g. out of memory) keeps its progress
    for i in range(0, len(stale), chunk_size):
        chunk = stale[i:i + chunk_size]
        vecs = embedder.encode([t for _, _, t in chunk])
        with conn:
            for (k, ref, txt), v in zip(chunk, vecs):
                _put(conn, k, ref, model, _hash(txt), v)
        if len(stale) > chunk_size:
            log(f"    saved {i + len(chunk)}/{len(stale)}")

    # drop vectors whose text no longer exists (e.g. a re-linked professor lost papers)
    live = {(k, ref) for k, ref, _ in todo}
    with conn:
        for k in ("dept", "topics", "paper"):
            for ref in existing[k]:
                if (k, ref) not in live:
                    conn.execute("DELETE FROM embeddings WHERE kind=? AND ref_id=? AND model=?", (k, ref, model))

    # 3. profiles
    vec = {k: {ref: v for ref, (_, v) in _get_all(conn, k, model).items()} for k in ("dept", "topics", "paper")}
    mix, decay = ranking.get("profile_mix", {}), float(ranking.get("recency_decay", 0.8))
    n_profiles = 0
    with conn:
        conn.execute("DELETE FROM embeddings WHERE kind='profile' AND model=?", (model,))
        for p in profs:
            pv = [vec["paper"][f"{p.id}|{w.work_id}"] for w in p.papers if f"{p.id}|{w.work_id}" in vec["paper"]]
            prof_vec = assemble_profile(vec["dept"].get(p.id), vec["topics"].get(p.id),
                                        np.stack(pv) if pv else None, [w.year for w in p.papers], mix, decay)
            if prof_vec is not None:
                _put(conn, "profile", p.id, model, "", prof_vec)
                n_profiles += 1
        conn.execute("INSERT INTO build_info (key, value) VALUES ('embeddings_built_at', ?) ON CONFLICT(key) "
                     "DO UPDATE SET value=excluded.value", (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
        conn.execute("INSERT INTO build_info (key, value) VALUES ('embedding_model', ?) ON CONFLICT(key) "
                     "DO UPDATE SET value=excluded.value", (model,))
    return {"professors": len(profs), "profiles": n_profiles, "embedded": len(stale),
            "papers": sum(len(p.papers) for p in profs), "seconds": round(time.time() - t0, 1)}


def load_index(conn, model: str, ranking: dict) -> SearchIndex:
    profs = load_professors(conn)
    prof_vecs = {ref: v for ref, (_, v) in _get_all(conn, "profile", model).items()}
    paper_vecs = {ref: v for ref, (_, v) in _get_all(conn, "paper", model).items()}
    if not prof_vecs:
        raise RuntimeError(f"No embeddings for model {model!r}. Run: python build_embeddings.py")
    dim = len(next(iter(prof_vecs.values())))
    pm = np.zeros((len(profs), dim), dtype=np.float32)
    papers_m = []
    for i, p in enumerate(profs):
        if p.id in prof_vecs:
            pm[i] = prof_vecs[p.id]
        keep = [(w, paper_vecs[f"{p.id}|{w.work_id}"]) for w in p.papers if f"{p.id}|{w.work_id}" in paper_vecs]
        p.papers = [w for w, _ in keep]
        papers_m.append(normalize(np.stack([v for _, v in keep])) if keep else None)
    return SearchIndex(profs, normalize(pm) * (np.linalg.norm(pm, axis=1, keepdims=True) > 0), papers_m, ranking)
