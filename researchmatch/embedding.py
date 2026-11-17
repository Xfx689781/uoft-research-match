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
    def __init__(self, model_name: str, query_prefix: str = "", batch_size: int = 64,
                 max_seq_length: int | None = None, threads: int | None = None):
        import torch
        from sentence_transformers import SentenceTransformer   # heavy import: only when used

        if threads:
            torch.set_num_threads(threads)
        self.name = model_name
        self.query_prefix = query_prefix
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device="cpu")
        if max_seq_length:
            self.model.max_seq_length = max_seq_length      # caps memory per batch

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        if is_query and self.query_prefix:
            texts = [self.query_prefix + t for t in texts]
        import torch

        out = []
        with torch.inference_mode():
            for i in range(0, len(texts), 512):            # chunk so progress is visible and memory bounded
                out.append(self.model.encode(texts[i:i + 512], batch_size=self.batch_size,
                                             normalize_embeddings=True, convert_to_numpy=True))
                if len(texts) > 512:
                    print(f"    embedded {min(i + 512, len(texts))}/{len(texts)}", flush=True)
        return np.concatenate(out).astype(np.float32) if out else np.zeros((0, 0), np.float32)


def from_settings(settings, model: str | None = None) -> SentenceTransformerEmbedder:
    e = settings.embedding
    return SentenceTransformerEmbedder(model or e.get("model", "BAAI/bge-small-en-v1.5"),
                                       e.get("query_prefix", ""), int(e.get("batch_size", 64)),
                                       e.get("max_seq_length"), e.get("threads"))
