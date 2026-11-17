"""Text embedders. Anything with `.name` and `.encode(texts, is_query)` returning L2-normalized rows works."""
from __future__ import annotations

import os
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

        if not texts:
            return np.zeros((0, 0), np.float32)
        with torch.inference_mode():                        # callers chunk large inputs (see index_store.build)
            out = self.model.encode(texts, batch_size=self.batch_size,
                                    normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(out, dtype=np.float32)


class FastEmbedEmbedder:
    """ONNX runtime instead of PyTorch: same vectors for the bge models (checked to cosine 1.0000 with the
    same truncation), in a fraction of the memory. Used by the deployed API, which only embeds queries."""

    def __init__(self, model_name: str, query_prefix: str = "", max_seq_length: int | None = None,
                 threads: int | None = None):
        from fastembed import TextEmbedding

        self.name = model_name
        self.query_prefix = query_prefix
        self.model = TextEmbedding(model_name, threads=threads)
        if max_seq_length:
            self.model.model.tokenizer.enable_truncation(max_length=int(max_seq_length))

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), np.float32)
        if is_query and self.query_prefix:
            texts = [self.query_prefix + t for t in texts]
        return normalize(np.array(list(self.model.embed(texts))))


def from_settings(settings, model: str | None = None, backend: str | None = None):
    """backend: 'sentence-transformers' (default; needed for building) or 'fastembed' (light, for serving).
    The EMBEDDING_BACKEND environment variable overrides departments.yaml."""
    e = settings.embedding
    name = model or e.get("model", "BAAI/bge-small-en-v1.5")
    backend = backend or os.getenv("EMBEDDING_BACKEND") or e.get("backend", "sentence-transformers")
    if backend == "fastembed":
        return FastEmbedEmbedder(name, e.get("query_prefix", ""), e.get("max_seq_length"), e.get("threads"))
    return SentenceTransformerEmbedder(name, e.get("query_prefix", ""), int(e.get("batch_size", 64)),
                                       e.get("max_seq_length"), e.get("threads"))
