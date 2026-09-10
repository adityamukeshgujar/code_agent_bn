"""Given parsed intent, runs retrieval, then reads the actual candidate
file(s) end-to-end to pin down the exact element and how its styling is
controlled — inline style, CSS module, styled-components, Tailwind class,
or a plain CSS class. If that traces back to a shared/global stylesheet,
that's flagged explicitly rather than silently edited.

    localize(intent: Intent, repo_root: str | Path, top_k: int = 5) -> LocalizationResult
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from indexer.tokenize_utils import tokenize
from retriever.retrieve import retrieve

# Directories never worth scanning for style definitions / other usages.
_EXCLUDED_DIR_PARTS = {"node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".git"}

# Stylesheet filenames that are global/app-wide by convention, as opposed to
# a component-scoped stylesheet (e.g. `Button.css` next to `Button.jsx`).
_GLOBAL_STYLE_FILENAMES = {"index.css", "global.css", "globals.css", "app.css", "theme.css", "variables.css"}

_TAILWIND_HINT_RE = re.compile(
    r"\b(bg|text|border|rounded|shadow|font|p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|w|h|flex|grid)-[\w./\[\]#%-]+"
)
_STYLE_PROP_RE = re.compile(r"style=\{\{")
_CLASSNAME_EXPR_RE = re.compile(r"className=\{([^}]+)\}")
_CLASSNAME_LITERAL_RE = re.compile(r'className="([^"]+)"')
_CSS_MODULE_IMPORT_RE = re.compile(r"""import\s+(\w+)\s+from\s+['"](.+?\.module\.css)['"]""")


@dataclass
class LocalizationResult:
    ok: bool
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    element_snippet: str | None = None
    styling_mechanism: str | None = None  # inline_style | css_module | styled_components | css_class | tailwind_class | unknown
    style_ref: str | None = None  # the class name / style expression as written in the JSX
    style_file: str | None = None  # where the rule actually lives, if resolved
    is_shared: bool = False
    shared_note: str | None = None
    other_usages: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    ambiguous_files: list[str] = field(default_factory=list)
    summary: str = ""
    note: str | None = None

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d.pop("candidates", None)  # verbose; keep out of the printed summary
        return d


def _page_match_score(hit: dict, page_tokens: set[str]) -> int:
    if not page_tokens:
        return 0
    haystack = set(tokenize(hit["file_path"])) | set(tokenize(hit["symbol_name"]))
    return len(page_tokens & haystack)


def _classify_styling(snippet: str) -> tuple[str, str]:
    if _STYLE_PROP_RE.search(snippet):
        return "inline_style", "style={{...}}"
    m = _CLASSNAME_EXPR_RE.search(snippet)
    if m:
        expr = m.group(1).strip()
        if re.search(r"\b(styles|classes)\.\w+", expr):
            return "css_module", expr
        if "styled" in expr.lower():
            return "styled_components", expr
        return "unknown", expr
    m = _CLASSNAME_LITERAL_RE.search(snippet)
    if m:
        classes = m.group(1)
        if _TAILWIND_HINT_RE.search(classes):
            return "tailwind_class", classes
        return "css_class", classes.split()[0]
    return "unknown", ""


def _iter_files(repo_root: Path, *suffixes: str):
    for suffix in suffixes:
        for path in repo_root.rglob(f"*{suffix}"):
            if _EXCLUDED_DIR_PARTS & set(path.parts):
                continue
            yield path


def _resolve_css_class(repo_root: Path, owning_file: str, class_name: str):
    selector_re = re.compile(rf"\.{re.escape(class_name)}\b")
    style_file = None
    for css_path in _iter_files(repo_root, ".css", ".scss"):
        try:
            text = css_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if selector_re.search(text):
            style_file = css_path.relative_to(repo_root).as_posix()
            break

    is_shared = bool(style_file) and Path(style_file).name.lower() in _GLOBAL_STYLE_FILENAMES

    other_usages: list[str] = []
    for src_path in _iter_files(repo_root, ".jsx", ".tsx", ".js", ".ts"):
        rel = src_path.relative_to(repo_root).as_posix()
        if rel == owning_file:
            continue
        try:
            text = src_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if class_name in text:
            other_usages.append(rel)

    shared_note = None
    if style_file and is_shared:
        if other_usages:
            shared_note = (
                f"`.{class_name}` is defined in the global stylesheet `{style_file}` and also used in: "
                + ", ".join(other_usages)
                + " — changing it will affect those too."
            )
        else:
            shared_note = (
                f"`.{class_name}` is defined in the global stylesheet `{style_file}`, but no other file "
                f"currently references it — low blast radius today, still flagged because the file itself is shared."
            )
    elif style_file and other_usages:
        shared_note = f"`.{class_name}` ({style_file}) is also used in: " + ", ".join(other_usages)

    return style_file, is_shared, shared_note, other_usages


def _resolve_css_module(repo_root: Path, owning_file_text: str, owning_file: str, expr: str):
    m = re.search(r"\.(\w+)\s*$", expr)  # "styles.submitBtn" -> "submitBtn"
    if not m:
        return None, False, None, []
    prop_name = m.group(1)
    import_m = _CSS_MODULE_IMPORT_RE.search(owning_file_text)
    if not import_m:
        return None, False, None, []
    module_rel_import = import_m.group(2)
    module_path = (repo_root / owning_file).parent / module_rel_import
    if not module_path.exists():
        return None, False, None, []
    # CSS-module class names in the file are typically the literal JS property
    # name, or its kebab-case form — try both.
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", prop_name).lower()
    style_file = module_path.resolve()
    try:
        style_file = style_file.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        style_file = str(style_file)
    text = module_path.read_text(encoding="utf-8", errors="replace")
    for candidate in (prop_name, kebab):
        if re.search(rf"\.{re.escape(candidate)}\b", text):
            # CSS modules are scoped per-file by the build tool — not "shared"
            # in the global-stylesheet sense, but flag if >1 component imports it.
            other = [
                p.relative_to(repo_root).as_posix()
                for p in _iter_files(repo_root, ".jsx", ".tsx", ".js", ".ts")
                if p.relative_to(repo_root).as_posix() != owning_file
                and module_rel_import.split("/")[-1] in p.read_text(encoding="utf-8", errors="replace")
            ]
            is_shared = len(other) > 0
            shared_note = (
                f"CSS module `{style_file}` is also imported by: " + ", ".join(other) if other else None
            )
            return style_file, is_shared, shared_note, other
    return style_file, False, None, []


def localize(intent, repo_root: str | Path, top_k: int = 5) -> LocalizationResult:
    repo_root = Path(repo_root).resolve()

    query = " ".join(p for p in (intent.element, intent.page) if p) or intent.raw_request
    hits = retrieve(query, pages_only=bool(intent.page), top_k=top_k)
    if not hits:
        hits = retrieve(query, top_k=top_k)
    if not hits:
        return LocalizationResult(ok=False, note=f"No retrieval hits for {query!r}.")

    page_tokens = set(tokenize(intent.page)) if intent.page else set()
    ranked = sorted(hits, key=lambda h: (_page_match_score(h, page_tokens), h["score"]), reverse=True)
    top = ranked[0]
    top_score = _page_match_score(top, page_tokens)
    ambiguous_files = sorted(
        {
            h["file_path"]
            for h in ranked[1:]
            if h["file_path"] != top["file_path"]
            and _page_match_score(h, page_tokens) == top_score
            and abs(h["score"] - top["score"]) < 0.05
        }
    )

    top_file = top["file_path"]
    abs_path = repo_root / top_file
    try:
        full_text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return LocalizationResult(ok=False, candidates=ranked, note=f"Could not read {top_file}: {exc}")
    lines = full_text.splitlines()

    element_tokens = set(tokenize(intent.element)) if intent.element else set()
    start, end = top["lines"]
    match_idx = None
    # Pick the line with the MOST overlapping element tokens, not the first
    # with any overlap — a generic token like "button" alone would otherwise
    # match the first <button> in the file regardless of which one the
    # request actually means (e.g. "submit button" vs. an unrelated logout
    # button that happens to share the "button" token).
    for lo, hi in ((start, end), (1, len(lines))):
        best_score = 0
        for i in range(max(lo - 1, 0), min(hi, len(lines))):
            if "<" not in lines[i]:
                continue
            line_tokens = set(tokenize(lines[i]))
            score = len(element_tokens & line_tokens)
            if score > best_score:
                best_score = score
                match_idx = i
        if match_idx is not None:
            break

    if match_idx is None:
        snippet = "\n".join(lines[start - 1 : end])
        return LocalizationResult(
            ok=True,
            file_path=top_file,
            start_line=start,
            end_line=end,
            element_snippet=snippet,
            styling_mechanism="unknown",
            candidates=ranked,
            ambiguous_files=ambiguous_files,
            note="Could not pinpoint the exact element line within the matched component — returning the whole component instead.",
            summary=f"{top['symbol_name']} in `{top_file}`, lines {start}-{end} — exact element line not pinpointed.",
        )

    window_lo, window_hi = max(0, match_idx - 2), min(len(lines), match_idx + 3)
    snippet = "\n".join(lines[window_lo:window_hi])
    line_no = match_idx + 1

    mechanism, style_ref = _classify_styling(snippet)

    style_file = is_shared = shared_note = None
    other_usages: list[str] = []
    if mechanism == "css_class":
        style_file, is_shared, shared_note, other_usages = _resolve_css_class(repo_root, top_file, style_ref)
    elif mechanism == "css_module":
        style_file, is_shared, shared_note, other_usages = _resolve_css_module(repo_root, full_text, top_file, style_ref)

    mechanism_label = {
        "inline_style": "an inline `style` prop",
        "css_module": "a CSS-module class",
        "styled_components": "a styled-components component",
        "css_class": "a plain CSS class",
        "tailwind_class": "a Tailwind utility class",
        "unknown": "an unrecognized styling mechanism",
    }[mechanism]

    summary = (
        f"{mechanism_label} (`{style_ref}`) on the matched element in `{top_file}`, line {line_no}"
        + (f" — defined in `{style_file}`" if style_file else "")
        + (" — SHARED/global style, other elements may be affected" if is_shared else " — page-local")
        + "."
    )

    return LocalizationResult(
        ok=True,
        file_path=top_file,
        start_line=line_no,
        end_line=line_no,
        element_snippet=snippet,
        styling_mechanism=mechanism,
        style_ref=style_ref,
        style_file=style_file,
        is_shared=bool(is_shared),
        shared_note=shared_note,
        other_usages=other_usages,
        candidates=ranked,
        ambiguous_files=ambiguous_files,
        note=(f"Multiple similarly-ranked files also matched: {ambiguous_files} — confirm before proceeding." if ambiguous_files else None),
        summary=summary,
    )


def main() -> None:
    import argparse
    import json

    from intent.intent_parser import parse_intent

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", help="Natural-language change request")
    parser.add_argument("--root", required=True, help="Repo root to localize within")
    args = parser.parse_args()

    intent = parse_intent(args.request)
    if intent.needs_clarification:
        print(f"Clarification needed: {intent.clarification_question}")
        return
    result = localize(intent, args.root)
    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
