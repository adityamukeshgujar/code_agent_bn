# Project: codebase-change-agent

## Goal
Build a single-workflow code agent that takes a natural-language request like
"change the color of the submit button on the Assessment page" and:
1. Locates the relevant file(s) in the codebase
2. Applies a minimal, targeted patch
3. Validates the change (lint, typecheck, build)
4. Opens a GitHub PR with the diff for human review

Do not auto-merge or commit directly to `main`. Every change lands as a PR.

## Stack
- Frontend: Node.js + React (JS/TS/TSX)
- Backend: Python
- Vector DB: Qdrant Cloud (`QDRANT_URL`, `QDRANT_API_KEY` — read from env, never hardcode)
- Embeddings: OpenAI `text-embedding-3-large` (`EMBEDDING_API_KEY` in env) — keep this behind an interface so the model is swappable later
- Git hosting: GitHub (`GITHUB_TOKEN` in env, repo owner/name configurable)

## Build this in phases. Complete and verify each phase before starting the next.

---

### Phase 1 — Indexing pipeline
Build the offline indexer that populates Qdrant from the target repo.

- `chunker.py` — AST-aware chunking using `tree-sitter` for `.js/.jsx/.ts/.tsx/.py`. Chunk at function/class/component boundaries, not fixed-size windows. Each chunk's payload: `file_path, language, chunk_type, symbol_name, start_line, end_line, content, content_hash, is_page` (`is_page` = true if the file lives under `/pages`, `/screens`, or `/routes`).
- `embedder.py` — thin wrapper around the embeddings API, swappable interface (`embed_batch(texts: list[str]) -> list[list[float]]`).
- `setup_collection.py` — creates the Qdrant collection `codebase_index` (cosine distance, vector size matching the embedding model) with payload indexes on `file_path`, `language`, `chunk_type`, `is_page`, `symbol_name`.
- `index_repo.py` — walks the repo (respecting `.gitignore`, excluding `node_modules/`, `dist/`, `build/`, `__pycache__/`, `venv/`), chunks every matching file, embeds in batches, upserts to Qdrant. Use a deterministic point ID (`uuid5` of `file_path:symbol_name:start_line`) so re-runs update rather than duplicate.
- `reindex_changed.py` — incremental version: given a git commit range, diff changed files, delete their old Qdrant points, re-chunk and re-upsert only those files.
- CLI entrypoint: `python -m indexer.index_repo --root <path>` for full index, `python -m indexer.reindex_changed --since <commit>` for incremental.

**Acceptance check**: run the full indexer against this repo, confirm point count in Qdrant roughly matches the number of top-level functions/classes/components across the codebase, and confirm a manual `client.search()` for a known component name returns that component in the top 3 results.

---

### Phase 2 — Retrieval layer
Build the query-time module the agent calls.

- `retrieve.py` exposing `retrieve(query: str, languages: list[str] | None, pages_only: bool, top_k: int) -> list[dict]`, returning `file_path, symbol_name, lines, content, score`.
- Add a cheap keyword/filename pre-check (ripgrep or plain Python glob/grep over file names and route configs) that runs before falling back to semantic search — most requests like "the Assessment page" resolve here without needing a vector query at all.
- `repo_map.py` — generates a compact JSON of `{file_path: [symbol names]}` across the repo using the same tree-sitter parsing, refreshed alongside re-indexing. This is fed to the agent as lightweight standing context, separate from Qdrant retrieval.

**Acceptance check**: given the query "submit button assessment page", the top result should be the actual Assessment page component or its button, not an unrelated file.

---

### Phase 3 — Request parsing and localization
- `intent_parser.py` — takes the raw user request, extracts structured intent: `{page, element, action, value}`. If a required value is missing (e.g. no color given), the agent should ask a clarifying question rather than guessing.
- `localizer.py` — given parsed intent, runs the retrieval pipeline, then reads the actual candidate file(s) end-to-end to confirm the exact element and how its styling is controlled (inline style, CSS module, styled-components, Tailwind class, or a shared design-token/theme file). If it traces back to a shared/global style, flag that explicitly rather than silently editing something that will affect other pages.

**Acceptance check**: for the running example, localizer output should state the exact file path, line range, and styling mechanism (e.g. "Tailwind class on `<Button>` in `pages/Assessment.tsx`, line 42, uses `bg-blue-600` — page-local, not shared").

---

### Phase 4 — Patch application and validation
- `patcher.py` — generates a minimal diff (not a full-file rewrite) implementing the confirmed change, applies it to a working copy of the repo.
- `validator.py` — runs, in order: linter → typechecker → build → relevant test suite (frontend: `npm run lint`, `tsc --noEmit`, `npm run build`; backend: whatever the repo's existing CI uses). On failure, feed the error back into a retry loop (max 2 retries) before giving up and reporting the failure clearly instead of shipping a broken diff.

**Acceptance check**: intentionally break a target file first, confirm the validator catches it and the agent does not proceed to PR creation.

---

### Phase 5 — Git integration
- `git_ops.py` — creates a new branch off the current default branch, commits the validated change, pushes, and opens a PR via the GitHub API with a description referencing the original request and a summary of what changed and why.
- Never commit directly to the default branch. Never force-push.

**Acceptance check**: run the full pipeline end-to-end on the example request and confirm a real PR is opened with a correct, minimal diff and a clear description.

---

### Phase 6 — Orchestration entrypoint
- `agent.py` — single entrypoint tying phases 1–5 together for one workflow run: `python -m agent.run --request "Change the color of the submit button in Assessment Page to green"`.
- Log each stage's output (parsed intent, retrieval hits, localized target, diff, validation result, PR URL) so a human can audit what the agent did and why.

---

## General constraints throughout
- Prefer small, focused modules over one large script — this is meant to be extended to other request types later, not just button colors.
- No hardcoded secrets anywhere — all credentials from environment variables, document required env vars in a `.env.example`.
- Every external action (Qdrant writes, git pushes, PR creation) should be logged.
- Ask before proceeding if a request is ambiguous (e.g. multiple "Assessment" pages found) rather than guessing.
