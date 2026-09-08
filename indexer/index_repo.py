"""Full-repo indexer: walks a repo, chunks every matching file, embeds the
chunks in batches, and upserts them into Qdrant.

Respects .gitignore, and always excludes node_modules/, dist/, build/,
__pycache__/, venv/ regardless of .gitignore contents.

Uses a deterministic point ID (uuid5 of "file_path:symbol_name:start_line")
so re-running the indexer updates existing points instead of duplicating
them.

CLI:
    # index a repo you already have checked out locally
    python -m indexer.index_repo --root <path> [--recreate]

    # or sync a local mirror from GitHub first, then index that
    python -m indexer.index_repo --repo-url https://github.com/<owner>/<repo> \\
        [--branch main] [--clone-dir <path>] [--recreate]
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path
from typing import Iterator

import pathspec
from qdrant_client.http import models as qm

from .chunker import Chunk, SUPPORTED_EXTENSIONS, chunk_file
from .embedder import get_embedder
from .github_source import repo_name_from_url, sync_from_github
from .setup_collection import COLLECTION_NAME, setup_collection

DEFAULT_CLONE_ROOT = Path(__file__).resolve().parent.parent / "repos"

ALWAYS_EXCLUDED_DIRS = {"node_modules", "dist", "build", "__pycache__", "venv", ".venv", ".git"}
BATCH_SIZE = 64
POINT_NAMESPACE = uuid.NAMESPACE_URL


def _load_gitignore(root: Path) -> pathspec.PathSpec | None:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None
    lines = gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def iter_source_files(root: Path) -> Iterator[Path]:
    spec = _load_gitignore(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if ALWAYS_EXCLUDED_DIRS & set(rel.parts[:-1]):
            continue
        if spec is not None and spec.match_file(rel.as_posix()):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        yield path


def point_id(file_path: str, symbol_name: str, start_line: int) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, f"{file_path}:{symbol_name}:{start_line}"))


def chunk_repo(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in iter_source_files(root):
        try:
            chunks.extend(chunk_file(path, root))
        except Exception as exc:  # keep indexing the rest of the repo
            print(f"  ! skipped {path}: {exc}")
    return chunks


def index_repo(root: str | Path, recreate: bool = False) -> int:
    root = Path(root).resolve()
    client = setup_collection(recreate=recreate)
    embedder = get_embedder()

    files = list(iter_source_files(root))
    print(f"Found {len(files)} source file(s) under {root}")

    chunks = chunk_repo(root)
    print(f"Extracted {len(chunks)} chunk(s)")

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        vectors = embedder.embed_batch([c.content for c in batch])
        points = [
            qm.PointStruct(
                id=point_id(c.file_path, c.symbol_name, c.start_line),
                vector=vector,
                payload=c.as_dict(),
            )
            for c, vector in zip(batch, vectors)
        ]
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"  upserted {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)}")

    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", help="Path to a repo you already have checked out locally")
    source.add_argument("--repo-url", help="GitHub URL to sync a local mirror from before indexing")
    parser.add_argument(
        "--clone-dir",
        help="Where to sync --repo-url into (default: ./repos/<repo-name> under code_agent)",
    )
    parser.add_argument("--branch", help="Branch to check out when using --repo-url (default: repo's default branch)")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the collection first")
    args = parser.parse_args()

    if args.repo_url:
        clone_dir = args.clone_dir or (DEFAULT_CLONE_ROOT / repo_name_from_url(args.repo_url))
        root = sync_from_github(args.repo_url, clone_dir, branch=args.branch)
    else:
        root = args.root

    n = index_repo(root, recreate=args.recreate)
    print(f"Done. Indexed {n} chunk(s).")


if __name__ == "__main__":
    main()
