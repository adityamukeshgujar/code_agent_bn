# codebase-change-agent

See [CLAUDE.md](CLAUDE.md) for the full spec. This is the phased build of it.

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Indexing pipeline | Chunker + embedder + Qdrant setup + full indexer done. `reindex_changed.py` (incremental) not built yet. |
| 2 | Retrieval layer | `retrieve.py` done (vector search + keyword re-rank). `repo_map.py` not built yet. |
| 3 | Intent parsing & localization | Done — `intent_parser.py` (Groq) + `localizer.py`. |
| 4 | Patch application & validation | Done — `patcher.py` (css_class/css_module/inline_style/tailwind_class) + `validator.py`. |
| 5 | Git integration | Done — `git_ops.py`. Live push/PR not yet run end-to-end (dry-run/local-apply verified only). |
| 6 | Orchestration entrypoint | Done — `agent/run.py`, with dry-run/`--apply`/`--push-pr`/`--allow-shared` safety gates. |
| — | Skills library (identify-only) | Done — `skills/` — see "Skills" below. A curated alternative to Phase 2/3's free-text retrieval+localization for a fixed set of known UI change types; outputs only what needs to change, never patches. |

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # then fill in QDRANT_URL / QDRANT_API_KEY
```

No embedding API key is wired in — see `indexer/embedder.py`. The default
`HashingEmbedder` is a deterministic, dependency-free lexical embedding
(feature hashing), so indexing and retrieval work today with just Qdrant
credentials. Swap in a real model later without touching any caller.

`GROQ_API_KEY` (+ `GROQ_MODEL`, default `openai/gpt-oss-120b`) drives intent
parsing (Phase 3). `GITHUB_TOKEN` + `GITHUB_REPO` (`owner/name`) drive PR
creation (Phase 5).

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

# full agent run — dry run by default (parses intent, localizes, prints the
# diff, stops — writes nothing)
python -m agent.run --request "Change the color of the submit button in Assessment Page to green" --root /path/to/some/repo

# --apply writes the patch + runs lint/typecheck/build/test, reverting on failure
# --push-pr additionally branches/commits/pushes/opens a GitHub PR (implies --apply)
# --allow-shared is required if the target style is flagged as shared/global
python -m agent.run --request "..." --root /path/to/some/repo --apply --push-pr --allow-shared

# skills pipeline — identify only, never writes/patches/touches git
python -m skills.run --request "Change the submit button color to green" --root /path/to/some/repo
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

## Localization design notes

`intent/localizer.py` picks the best-matching element line by *token-overlap
count*, not first-match — a generic token like "button" alone would
otherwise latch onto the first `<button>` in the file regardless of which
one the request actually means. It classifies the styling mechanism
(`inline_style` / `css_module` / `styled_components` / `css_class` /
`tailwind_class`) from the matched JSX, and for `css_class`/`css_module`
resolves the actual stylesheet the rule lives in — flagging `is_shared` when
that file is a global/app-wide stylesheet (`index.css`, `globals.css`,
`theme.css`, etc.) rather than a component-scoped one, and listing any other
files that reference the same class.

## Patch generation design notes

`patcher/patcher.py` only ever edits the specific rule/prop it already knows
how to locate — a CSS rule's color property, an inline `style={{...}}`
prop, or a Tailwind color-utility token — via `difflib.unified_diff` against
the real file, never a full-file rewrite. `styled_components` and any
unrecognized mechanism raise clearly rather than guessing at an edit.
`generate_patch()` is pure (no writes); `apply_patch()`/`revert_patch()` are
the only functions that touch disk.

## Validation design notes

`patcher/validator.py` runs whatever the target repo actually defines —
frontend steps come from `package.json`'s own `scripts` (a missing script
is reported as skipped-with-a-reason, never silently skipped), backend
lint/typecheck/test tools are detected from `requirements.txt` (ruff/flake8/
pylint, mypy, pytest), falling back to a clearly-labeled syntax-only
`py_compile` check when the repo has no test tooling configured at all —
not a substitute for real tests, and reported as such rather than passing
silently.

## Git integration design notes

`vcs/git_ops.py` fetches the repo's real default branch from the GitHub API
(don't assume `main`), refuses to run at all if the local working tree has
uncommitted changes, and restores whatever branch was checked out before it
started in a `finally` block regardless of outcome — the new branch is
still created and pushed either way, the caller's own checkout just isn't
left switched out from under them. Never commits to the default branch,
never force-pushes.

## Orchestration (agent/run.py)

Three independent, opt-in safety gates, each stricter than the last:
`--apply` (write + validate locally, revert on failure) it defaults to off
(dry run: diff only); `--push-pr` (also branch/commit/push/open a PR)
implies `--apply`; `--allow-shared` is required to proceed past a
localization flagged `is_shared`. Every stage's output is printed as it
happens and also collected into a `RunLog` for programmatic/audit use.

## Skills

`skills/` is a curated, hand-authored alternative to the free-text
retrieval + heuristic localization in Phases 2-3, for a fixed set of known
UI change types on a fixed set of files. Where `agent/run.py` searches the
whole indexed repo and infers the styling mechanism from whatever it finds,
`skills/run.py` matches the request to one of a small number of
pre-written skill files and follows that skill's own notes about exactly
where to look and what's already there — more reliable for a change type
that's been seen before, at the cost of only covering what's been
authored.

- `skills/*.md` — one skill per (file, change-type) pair: YAML frontmatter
  (`name`, `description` used for matching, `file`, `change_type`:
  `change_color`/`change_text`/`enable_disable`, `elements`: known
  anchors with approximate line numbers) + a human-readable "Steps"
  section.
- `skills/loader.py` — parses the frontmatter + body.
- `skills/matcher.py` — Groq call that picks the single best-fitting
  skill for a request (or none, rather than forcing a bad match).
- `skills/executor.py` — reads the matched skill's target file and
  pinpoints the exact line via the same max-token-overlap scoring as
  `intent/localizer.py` (`find_best_matching_line`, `classify_styling`,
  `resolve_css_class`/`resolve_css_module` are shared between the two,
  not duplicated). Unlike the localizer, it searches its one target file
  in a single pass rather than per-element windows — an early bug here
  showed why: trying each declared element's line window as a separate
  fallback range stops at the first one with *any* overlap, so a weakly
  related earlier element beat a strongly related later one purely by
  list order.
- `skills/run.py` — `python -m skills.run --request "..." --root <path>`.
  **Reduced scope, intentionally**: identifies the code and describes the
  needed change only. No patch, no write, no git — that comes later once
  this identify-only step has been exercised against real requests.

Currently covers 3 files × 3 change types — `AssessmentPage.jsx`,
`LoginPage.jsx`, `PdfHighlightViewer.jsx` (`frontend/src/components/` in
the target repo used to build these) — = 9 skills.
