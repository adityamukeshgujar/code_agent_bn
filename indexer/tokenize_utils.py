"""Shared identifier-aware tokenizer used by both the hashing embedder and
the retriever's keyword re-rank.

Plain `\\w+` tokenization treats `AssessmentPage` or `submit_btn` as one
opaque blob, which means a query like "submit button assessment page" never
matches the symbol `AssessmentPage` at all (lowercased whole-token compare:
"assessmentpage" != "assessment"/"page"). Since most of the signal in code
lives in identifier names, and those are near-universally camelCase,
PascalCase, or snake_case, splitting on those boundaries is what makes
lexical matching actually work here.
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def split_identifier(token: str) -> list[str]:
    """snake_case / camelCase / PascalCase -> lowercase sub-words."""
    words: list[str] = []
    for part in token.split("_"):
        if not part:
            continue
        words.extend(w.lower() for w in _CAMEL_BOUNDARY_RE.split(part) if w)
    return words


def tokenize(text: str) -> list[str]:
    """Every identifier-like run in `text`, as both its lowercased whole form
    (so exact-symbol queries still match) and its split sub-words."""
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text):
        tokens.append(raw.lower())
        tokens.extend(split_identifier(raw))
    return tokens
