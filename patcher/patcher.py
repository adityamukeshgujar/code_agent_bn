"""Generates a minimal diff implementing a confirmed change, and applies it
to a working copy.

    generate_patch(localization, new_value, repo_root) -> Patch   # pure, no I/O writes
    apply_patch(patch, repo_root) -> None                          # writes target_file

Only handles the styling mechanisms localizer.py can positively identify:
css_class / css_module (edits the resolved stylesheet), inline_style /
tailwind_class (edits the JSX in place). styled_components and unknown
mechanisms raise clearly rather than guessing at an edit.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

_HEXY_RE = re.compile(r"^#|^rgb|^hsl", re.IGNORECASE)
_TAILWIND_COLOR_UTIL_RE = re.compile(r"\b(bg|text|border)-([a-z]+(?:-[a-z]+)?)-(\d{2,3})\b")

# Properties tried in order when patching a color change — background first
# since that's what "the button's color" usually means for a filled button.
_COLOR_PROP_ORDER = ("background-color", "background", "color")
_INLINE_COLOR_PROP_ORDER = ("backgroundColor", "background", "color")


@dataclass
class Patch:
    target_file: str  # POSIX-style, relative to repo root
    original_content: str
    new_content: str
    diff_text: str
    description: str


def _patch_css_rule(css_text: str, class_name: str, new_value: str) -> tuple[str, str]:
    rule_re = re.compile(rf"(\.{re.escape(class_name)}\s*\{{)([^}}]*)(\}})", re.DOTALL)
    m = rule_re.search(css_text)
    if not m:
        raise ValueError(f"Could not find a `.{class_name} {{ ... }}` rule in this stylesheet to patch.")
    header, body, footer = m.group(1), m.group(2), m.group(3)

    new_body, changed_prop = body, None
    for prop in _COLOR_PROP_ORDER:
        prop_re = re.compile(rf"({re.escape(prop)}\s*:\s*)([^;]+)(;)")
        pm = prop_re.search(body)
        if pm:
            new_body = body[: pm.start()] + pm.group(1) + new_value + pm.group(3) + body[pm.end() :]
            changed_prop = prop
            break
    if changed_prop is None:
        stripped = body.rstrip()
        sep = "\n" if stripped and not stripped.endswith("\n") else ""
        new_body = f"{stripped}{sep}  background-color: {new_value};\n"
        changed_prop = "background-color"

    new_css_text = css_text[: m.start()] + header + new_body + footer + css_text[m.end() :]
    return new_css_text, f"Set `{changed_prop}` to `{new_value}` in `.{class_name}`."


def _patch_inline_style(snippet: str, new_value: str) -> tuple[str, str]:
    m = re.search(r"style=\{\{([^}]*)\}\}", snippet, re.DOTALL)
    if not m:
        raise ValueError("Could not find an inline `style={{...}}` block to patch.")
    body = m.group(1)
    for prop in _INLINE_COLOR_PROP_ORDER:
        pm = re.search(rf"({prop}\s*:\s*)('[^']*'|\"[^\"]*\"|[^,}}]+)", body)
        if pm:
            quote = "'" if "'" in pm.group(2) else ('"' if '"' in pm.group(2) else "")
            new_val_text = f"{quote}{new_value}{quote}" if quote else new_value
            new_body = body[: pm.start()] + pm.group(1) + new_val_text + body[pm.end() :]
            new_snippet = snippet[: m.start(1)] + new_body + snippet[m.end(1) :]
            return new_snippet, f"Set `{prop}` to `{new_value}` in the inline style."
    stripped = body.rstrip()
    sep = ", " if stripped and not stripped.endswith(",") else ""
    new_body = f"{stripped}{sep} backgroundColor: '{new_value}'"
    new_snippet = snippet[: m.start(1)] + new_body + snippet[m.end(1) :]
    return new_snippet, f"Added `backgroundColor: '{new_value}'` to the inline style."


def _patch_tailwind_class(snippet: str, new_value: str) -> tuple[str, str]:
    m = _TAILWIND_COLOR_UTIL_RE.search(snippet)
    if not m:
        raise ValueError("Could not find a bg-/text-/border- color utility class to patch.")
    prefix, _, shade = m.groups()
    stripped_value = new_value.strip()
    if _HEXY_RE.match(stripped_value):
        replacement = f"{prefix}-[{stripped_value}]"
    else:
        replacement = f"{prefix}-{stripped_value.lower().replace(' ', '-')}-{shade}"
    new_snippet = snippet[: m.start()] + replacement + snippet[m.end() :]
    return new_snippet, f"Replaced `{m.group(0)}` with `{replacement}`."


def _css_module_class_guess(expr: str) -> str:
    prop = expr.rsplit(".", 1)[-1]
    return re.sub(r"(?<!^)(?=[A-Z])", "-", prop).lower()


def generate_patch(localization, new_value: str, repo_root: str | Path) -> Patch:
    """Pure — reads the target file(s) but never writes. Call apply_patch()
    separately once the diff has been reviewed."""
    repo_root = Path(repo_root)
    mechanism = localization.styling_mechanism

    if mechanism in ("css_class", "css_module"):
        if not localization.style_file:
            raise ValueError(f"No resolved stylesheet for a {mechanism} change — can't patch automatically.")
        target_rel = localization.style_file
        class_name = (
            localization.style_ref.split()[0]
            if mechanism == "css_class"
            else _css_module_class_guess(localization.style_ref)
        )
        target_path = repo_root / target_rel
        original = target_path.read_text(encoding="utf-8")
        new_content, description = _patch_css_rule(original, class_name, new_value)

    elif mechanism in ("inline_style", "tailwind_class"):
        target_rel = localization.file_path
        target_path = repo_root / target_rel
        original = target_path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        lo, hi = localization.start_line, localization.end_line
        window = "".join(lines[lo - 1 : hi])
        patch_fn = _patch_inline_style if mechanism == "inline_style" else _patch_tailwind_class
        new_window, description = patch_fn(window, new_value)
        new_content = "".join(lines[: lo - 1]) + new_window + "".join(lines[hi:])

    else:
        raise ValueError(
            f"Patching for styling mechanism {mechanism!r} isn't implemented yet — "
            "handle it manually, or extend patcher.py to cover it."
        )

    diff_text = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{target_rel}",
            tofile=f"b/{target_rel}",
        )
    )
    return Patch(
        target_file=target_rel,
        original_content=original,
        new_content=new_content,
        diff_text=diff_text,
        description=description,
    )


def apply_patch(patch: Patch, repo_root: str | Path) -> Path:
    target_path = Path(repo_root) / patch.target_file
    target_path.write_text(patch.new_content, encoding="utf-8")
    return target_path


def revert_patch(patch: Patch, repo_root: str | Path) -> None:
    """Restore target_file to its pre-patch content (used on validation failure)."""
    target_path = Path(repo_root) / patch.target_file
    target_path.write_text(patch.original_content, encoding="utf-8")
