"""Embedding backend — thin, swappable wrapper.

Every backend implements the same interface:

    embed_batch(texts: list[str]) -> list[list[float]]

No paid embedding API is wired in yet:
- OpenAI is out of scope for this project (per CLAUDE.md, Groq is the model
  provider instead).
- Groq's API serves chat/completion models, not embeddings — there is
  nothing to point at there for this file.

Until a real embedding backend is chosen, `HashingEmbedder` is the default:
a deterministic, dependency-free "hashing trick" bag-of-words embedding
(feature hashing with signed contributions, then L2-normalized). It has no
real semantic understanding, but chunks that share identifiers/words score
as similar, which is enough to exercise the full indexing + Qdrant +
retrieval pipeline end-to-end today. Swap in a real model later by adding a
class here with the same `embed_batch` signature and pointing
`EMBEDDING_BACKEND` at it.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from typing import Protocol

DEFAULT_DIM = int(os.environ.get("EMBED_DIM", "512"))

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Embedder(Protocol):
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _hash_token(token: str, dim: int) -> tuple[int, float]:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % dim
    sign = 1.0 if int(digest[8], 16) % 2 == 0 else -1.0
    return index, sign


class HashingEmbedder:
    """Deterministic feature-hashing embedder. No network calls, no API key."""

    def __init__(self, dim: int = DEFAULT_DIM):
        self.dim = dim

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token, count in Counter(_tokenize(text)).items():
            idx, sign = _hash_token(token, self.dim)
            vec[idx] += sign * count
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_embedder() -> Embedder:
    backend = os.environ.get("EMBEDDING_BACKEND", "hashing").lower()
    if backend == "hashing":
        return HashingEmbedder()
    raise ValueError(
        f"Unknown EMBEDDING_BACKEND {backend!r}. Only 'hashing' is wired in "
        "for now — add a real backend class above and register it here "
        "once one is chosen."
    )
