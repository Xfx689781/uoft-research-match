"""Text embedders. Anything with `.name` and `.encode(texts, is_query)` returning L2-normalized rows works."""
from __future__ import annotations

from typing import Protocol

import numpy as np


class Embedder(Protocol):
    name: str

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray: ...


def normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, query_prefix: str = "", batch_size: int = 64):
        from sentence_transformers import SentenceTransformer   # heavy import: only when used

        self.name = model_name
        self.query_prefix = query_prefix
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        if is_query and self.query_prefix:
            texts = [self.query_prefix + t for t in texts]
        vecs = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                 show_progress_bar=len(texts) > 500, convert_to_numpy=True)
        return vecs.astype(np.float32)


def from_settings(settings) -> SentenceTransformerEmbedder:
    e = settings.embedding
    return SentenceTransformerEmbedder(e.get("model", "BAAI/bge-small-en-v1.5"),
                                       e.get("query_prefix", ""), int(e.get("batch_size", 64)))
