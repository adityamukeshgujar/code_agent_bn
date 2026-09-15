"""Loads skill definitions from skills/*.md — a YAML frontmatter block
(name, description, file, change_type, elements) followed by a markdown
"Steps" section meant for a human (or an LLM) to follow.

    load_skills() -> list[Skill]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parent
_REQUIRED_FIELDS = {"name", "description", "file", "change_type"}
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    file: str  # repo-relative path this skill targets
    change_type: str  # change_color | change_text | enable_disable
    elements: list[dict] = field(default_factory=list)
    steps: str = ""  # markdown body
    source_path: Path | None = None


def _parse_skill_file(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{path}: missing YAML frontmatter (expected a leading '---' block)")
    frontmatter_text, body = m.group(1), m.group(2)
    data = yaml.safe_load(frontmatter_text) or {}
    missing = _REQUIRED_FIELDS - data.keys()
    if missing:
        raise ValueError(f"{path}: frontmatter missing required field(s): {sorted(missing)}")
    return Skill(
        name=data["name"],
        description=str(data["description"]).strip(),
        file=data["file"],
        change_type=data["change_type"],
        elements=data.get("elements") or [],
        steps=body.strip(),
        source_path=path,
    )


def load_skills(skills_dir: Path = SKILLS_DIR) -> list[Skill]:
    return [_parse_skill_file(p) for p in sorted(skills_dir.glob("*.md"))]
