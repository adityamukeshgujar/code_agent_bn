"""Executes a matched skill in identify-only mode: reads the skill's target
file, pinpoints the exact line the request refers to, and reports the
current code plus what needs to change. Never writes, patches, or touches
git — this is the reduced scope for now (see skills/run.py's docstring).

    identify(intent, skill, repo_root) -> IdentificationResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from indexer.tokenize_utils import tokenize
from intent.localizer import classify_styling, find_best_matching_line, resolve_css_class, resolve_css_module

from .loader import Skill


@dataclass
class IdentificationResult:
    ok: bool
    skill_name: str | None = None
    file_path: str | None = None
    line: int | None = None
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
    # Unlike localizer.py (which narrows to a retrieved chunk before falling
    # back to the whole file), the executor already reads a single specific
    # file chosen by the matched skill — so search it in one pass. Per-
    # element approx_line windows tried as separate ranges would be wrong
    # here: find_best_matching_line stops at the first range with ANY
    # match, so an earlier, weakly-overlapping element (e.g. "button" alone
    # matching a `.logout-btn`) would win over a later, better-overlapping
    # one (e.g. "submit"+"button" matching `.submit-btn`) purely by list
    # order — the same bug the max-overlap scoring elsewhere is meant to
    # avoid. A single whole-file range lets the scoring compare all
    # occurrences together and pick the true best.
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
    line_no = match_idx + 1

    result = IdentificationResult(
        ok=True,
        skill_name=skill.name,
        file_path=skill.file,
        line=line_no,
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
        result.required_change = (
            f"Change the color-related property to {intent.value!r}"
            + (f" in `{result.style_file}`" if result.style_file else " (styling mechanism not fully resolved — see note)")
            + "."
        )

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
