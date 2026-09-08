"""Query-time retrieval over the Qdrant codebase index.

    retrieve(query, languages=None, pages_only=False, top_k=10) -> list[dict]

Each result: {file_path, symbol_name, lines: [start, end], content, score}.

Because the current embedder (see indexer/embedder.py) is a lexical
hashing-trick vector rather than a real semantic embedding, this also folds
in a cheap keyword boost: candidates whose file_path/symbol_name literally
contain query tokens are ranked up. This is the same "keyword/filename
pre-check before falling back to pure semantic search" idea from the spec,
applied as a re-ranking pass over the vector-search candidates rather than a
separate filesystem scan — cheap, and it means results are already
Qdrant-filtered by language/is_page before the boost is applied.
"""
from __future__ import annotations

from qdrant_client.http import models as qm

from indexer.config import QDRANT_URL  # noqa: F401  (import triggers load_dotenv via config)
from indexer.embedder import get_embedder
from indexer.setup_collection import COLLECTION_NAME, get_client
from indexer.tokenize_utils import tokenize

# candidate pool fetched from Qdrant before the keyword re-rank narrows it to top_k
_CANDIDATE_MULTIPLIER = 4
KEYWORD_BOOST_PER_HIT = 0.15


def _keyword_boost(query_tokens: set[str], payload: dict) -> float:
    if not query_tokens:
        return 0.0
    haystack = set(tokenize(payload.get("file_path", ""))) | set(tokenize(payload.get("symbol_name", "")))
    hits = len(query_tokens & haystack)
    return hits * KEYWORD_BOOST_PER_HIT


def retrieve(
    query: str,
    languages: list[str] | None = None,
    pages_only: bool = False,
    top_k: int = 10,
) -> list[dict]:
    client = get_client()
    embedder = get_embedder()
    vector = embedder.embed_batch([query])[0]

    must: list[qm.FieldCondition] = []
    if languages:
        must.append(qm.FieldCondition(key="language", match=qm.MatchAny(any=languages)))
    if pages_only:
        must.append(qm.FieldCondition(key="is_page", match=qm.MatchValue(value=True)))
    query_filter = qm.Filter(must=must) if must else None

    hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        query_filter=query_filter,
        limit=top_k * _CANDIDATE_MULTIPLIER,
        with_payload=True,
    ).points

    query_tokens = set(tokenize(query))
    scored = [
        {
            "file_path": hit.payload["file_path"],
            "symbol_name": hit.payload["symbol_name"],
            "lines": [hit.payload["start_line"], hit.payload["end_line"]],
            "content": hit.payload["content"],
            "chunk_type": hit.payload["chunk_type"],
            "language": hit.payload["language"],
            "is_page": hit.payload["is_page"],
            "score": hit.score + _keyword_boost(query_tokens, hit.payload),
        }
        for hit in hits
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_k]
