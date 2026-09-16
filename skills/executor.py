"""Executes a matched skill in identify-only mode: reads the skill's target
file, pinpoints the exact line the request refers to, and reports the
current code plus what needs to change. Never writes, patches, or touches
git — this is the reduced scope for now (see skills/run.py's docstring).

    identify(intent, skill, repo_root) -> IdentificationResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from indexer.chunker import EXT_TO_LANGUAGE
from indexer.tokenize_utils import tokenize
from intent.localizer import (
    classify_styling,
    find_best_matching_element,
    find_best_matching_line,
    resolve_css_class,
    resolve_css_module,
)

from .loader import Skill


@dataclass
class IdentificationResult:
    ok: bool
    skill_name: str | None = None
    file_path: str | None = None
    line: int | None = None
    end_line: int | None = None
    current_code: str | None = None
    styling_mechanism: str | None = None
    style_ref: str | None = None
    style_file: str | None = None
    is_shared: bool = False
    shared_note: str | None = None
    required_change: str = ""
    note: str | None = None
    matched_elements: list[dict] = field(default_factory=list)  # skill.elements, for context in the output

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    @property
    def start_line(self) -> int | None:
        """Alias so an IdentificationResult can be passed anywhere a
        LocalizationResult is expected (patcher.generate_patch() reads
        .start_line/.end_line/.file_path/.styling_mechanism/.style_ref/
        .style_file — duck typing, not a shared base class, since the two
        results otherwise serve different callers)."""
        return self.line


def identify(intent, skill: Skill, repo_root: str | Path) -> IdentificationResult:
    repo_root = Path(repo_root)
    target_path = repo_root / skill.file
    try:
        full_text = target_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return IdentificationResult(
            ok=False, skill_name=skill.name, file_path=skill.file, note=f"Could not read {skill.file}: {exc}"
        )
    lines = full_text.splitlines()

    element_tokens = set(tokenize(intent.element)) if intent.element else set()
    language = EXT_TO_LANGUAGE.get(Path(skill.file).suffix.lower())

    # Prefer the tree-sitter element matcher — it scores a JSX element's
    # FULL span regardless of how many lines its attributes/text spread
    # across (Prettier-style formatting routinely puts the opening tag on
    # its own line, with attributes/text children several lines below —
    # a line-by-line scorer never even sees those tokens). Falls back to
    # line-based scoring only for non-JSX languages or if nothing scored.
    #
    # Unlike localizer.py (which narrows to a retrieved chunk before
    # falling back to the whole file), the executor already reads a single
    # specific file chosen by the matched skill, so the line-based fallback
    # searches it in one pass rather than per-element approx_line windows —
    # those would be wrong here for the same reason max-overlap scoring
    # exists at all: find_best_matching_line stops at the first range with
    # ANY match, so an earlier, weakly-overlapping element (e.g. "button"
    # alone matching `.logout-btn`) would beat a later, better-overlapping
    # one (e.g. "submit"+"button" matching `.submit-btn`) purely by list
    # order.
    element_span = find_best_matching_element(full_text, language, element_tokens) if language else None
    if element_span is not None:
        line_no, end_line_no = element_span
        snippet = "\n".join(lines[line_no - 1 : end_line_no])
    else:
        match_idx = find_best_matching_line(lines, element_tokens, [(1, len(lines))])
        if match_idx is None:
            return IdentificationResult(
                ok=False,
                skill_name=skill.name,
                file_path=skill.file,
                matched_elements=skill.elements,
                note=(
                    "Could not pinpoint a specific line for this element wording within "
                    f"{skill.file}. Skill elements considered: {[e.get('label') for e in skill.elements]}"
                ),
            )
        window_lo, window_hi = max(0, match_idx - 2), min(len(lines), match_idx + 3)
        snippet = "\n".join(lines[window_lo:window_hi])
        line_no = end_line_no = match_idx + 1

    result = IdentificationResult(
        ok=True,
        skill_name=skill.name,
        file_path=skill.file,
        line=line_no,
        end_line=end_line_no,
        current_code=snippet,
        matched_elements=skill.elements,
    )

    if skill.change_type == "change_color":
        mechanism, style_ref = classify_styling(snippet)
        result.styling_mechanism = mechanism
        result.style_ref = style_ref
        if mechanism == "css_class":
            style_file, is_shared, shared_note, _ = resolve_css_class(repo_root, skill.file, style_ref)
            result.style_file, result.is_shared, result.shared_note = style_file, bool(is_shared), shared_note
        elif mechanism == "css_module":
            style_file, is_shared, shared_note, _ = resolve_css_module(repo_root, full_text, skill.file, style_ref)
            result.style_file, result.is_shared, result.shared_note = style_file, bool(is_shared), shared_note
        if mechanism in ("inline_style", "tailwind_class"):
            location = f"directly in `{skill.file}` at this line"
        elif result.style_file:
            location = f"in `{result.style_file}`"
        elif mechanism in ("css_class", "css_module"):
            location = "in an unresolved stylesheet — the rule's file couldn't be located"
        else:
            location = "location not determined — unrecognized styling mechanism"
        result.required_change = f"Change the color-related property to {intent.value!r}, {location}."

    elif skill.change_type == "change_text":
        result.required_change = (
            f"Change the text to {intent.value!r} — first confirm this is a literal string at this "
            "line and not a data-bound expression (see this skill's Steps for known exceptions)."
        )

    elif skill.change_type == "enable_disable":
        want = "disable" if (intent.value or "").lower().startswith("dis") else "enable"
        result.required_change = (
            f"{want.capitalize()} this element — add or adjust its `disabled` condition "
            "(see this skill's Steps for what's already available to gate on)."
        )

    return result
