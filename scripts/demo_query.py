"""Manual acceptance-check helper for Phase 1/2.

    python scripts/demo_query.py "submit button assessment page"

Requires QDRANT_URL / QDRANT_API_KEY in .env and a repo already indexed via:

    python -m indexer.index_repo --root <path-to-a-repo>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.retrieve import retrieve


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python scripts/demo_query.py "<query>"')
        raise SystemExit(1)
    query = " ".join(sys.argv[1:])
    results = retrieve(query, top_k=5)
    if not results:
        print("No results. Did you run `python -m indexer.index_repo --root <path>` first?")
        return
    print(f"Top {len(results)} result(s) for: {query!r}\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['file_path']}  ({r['symbol_name']}, {r['chunk_type']})  lines {r['lines'][0]}-{r['lines'][1]}  score={r['score']:.3f}")


if __name__ == "__main__":
    main()
