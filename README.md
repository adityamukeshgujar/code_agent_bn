# codebase-change-agent

See [CLAUDE.md](CLAUDE.md) for the full spec. This is the phased build of it.

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Indexing pipeline | Chunker + embedder + Qdrant setup + full indexer done. `reindex_changed.py` (incremental) not built yet. |
| 2 | Retrieval layer | `retrieve.py` done (vector search + keyword re-rank). `repo_map.py` not built yet. |
| 3 | Intent parsing & localization | Not started |
| 4 | Patch application & validation | Not started |
| 5 | Git integration | Deferred (per user request) |
| 6 | Orchestration entrypoint | Not started |

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # then fill in QDRANT_URL / QDRANT_API_KEY
```

No embedding API key is wired in — see `indexer/embedder.py`. The default
`HashingEmbedder` is a deterministic, dependency-free lexical embedding
(feature hashing), so indexing and retrieval work today with just Qdrant
credentials. Swap in a real model later without touching any caller.

`GROQ_API_KEY` / `GITHUB_TOKEN` are placeholders for later phases (intent
parsing, patch generation, PR creation) — not used yet.

## Usage

```
# one-time: create the Qdrant collection + payload indexes
python -m indexer.setup_collection

# index a repo you already have checked out locally
python -m indexer.index_repo --root /path/to/some/repo

# or index straight from GitHub — clones/pulls into ./repos/<name> first,
# then indexes that local mirror (the indexer always needs a real
# filesystem tree; see indexer/github_source.py)
python -m indexer.index_repo --repo-url https://github.com/<owner>/<repo> --branch main

# re-index from scratch
python -m indexer.index_repo --root /path/to/some/repo --recreate

# query it
python scripts/demo_query.py "submit button assessment page"

# chunker sanity check (no Qdrant/network needed)
python scripts/test_chunker.py
```

## Chunker design notes

`indexer/chunker.py` chunks `.py` / `.js` / `.jsx` / `.ts` / `.tsx` at
function/class boundaries using tree-sitter (via `tree-sitter-language-pack`,
so no manual grammar builds on Windows).

- Nested/inner functions are **not** split into their own chunks — once a
  function or class boundary matches, the walk stops descending into it
  (except one level into a class body, to also pull out its methods as
  separate `method` chunks).
- A function/arrow-function assigned to a capitalized name (`const Foo = () =>
  ...`, `function Foo() {...}`) is tagged `chunk_type="component"` instead of
  `"function"` — this is what Phase 3's localizer will look for when asked
  about "the X page".
- `export` / `export default` wrappers are folded into the chunk's span.
- `is_page` is true when the file lives under a `pages/`, `screens/`, or
  `routes/` directory (case-insensitive).

## Retrieval design notes

`retriever/retrieve.py` always does a Qdrant vector search first, then
re-ranks the candidate pool by a cheap keyword-overlap boost against
`file_path`/`symbol_name`. Since the current embedder is lexical rather than
truly semantic, this keeps "the Assessment page" style queries resolving on
filename/symbol overlap without a second filesystem pass — a pragmatic
merge of the spec's "keyword pre-check, then semantic fallback" idea rather
than two separate stages.
