"""Creates (or re-creates) the Qdrant collection used for the codebase index.

CLI:
    python -m indexer.setup_collection [--recreate]
"""
from __future__ import annotations

import argparse

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from . import config
from .embedder import DEFAULT_DIM

COLLECTION_NAME = "codebase_index"

_PAYLOAD_INDEXES: dict[str, qm.PayloadSchemaType] = {
    "file_path": qm.PayloadSchemaType.KEYWORD,
    "language": qm.PayloadSchemaType.KEYWORD,
    "chunk_type": qm.PayloadSchemaType.KEYWORD,
    "is_page": qm.PayloadSchemaType.BOOL,
    "symbol_name": qm.PayloadSchemaType.KEYWORD,
}


def get_client() -> QdrantClient:
    if not config.QDRANT_URL:
        raise RuntimeError(
            "QDRANT_URL is not set. Copy .env.example to .env and fill in "
            "QDRANT_URL / QDRANT_API_KEY."
        )
    return QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)


def setup_collection(recreate: bool = False, dim: int = DEFAULT_DIM) -> QdrantClient:
    client = get_client()
    exists = client.collection_exists(COLLECTION_NAME)
    if exists and not recreate:
        print(f"Collection {COLLECTION_NAME!r} already exists — leaving it as is.")
    else:
        if exists:
            print(f"Recreating collection {COLLECTION_NAME!r} (dim={dim})...")
        else:
            print(f"Creating collection {COLLECTION_NAME!r} (dim={dim})...")
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        for field_name, schema in _PAYLOAD_INDEXES.items():
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=schema,
            )
        print(f"Created payload indexes on: {', '.join(_PAYLOAD_INDEXES)}")
    return client


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate if it already exists")
    args = parser.parse_args()
    setup_collection(recreate=args.recreate)


if __name__ == "__main__":
    main()
