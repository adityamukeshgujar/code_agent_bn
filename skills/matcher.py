"""Matches a natural-language CR to the single best-fitting skill (or none)
out of a fixed, hand-authored list — as opposed to intent/localizer.py's
free-text retrieval across the whole repo.

    match_skill(request, intent, skills) -> Skill | None
"""
from __future__ import annotations

import json
import os

from groq import Groq

from indexer import config

from .loader import Skill

DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

_SYSTEM_PROMPT_TEMPLATE = """You match a UI change request to the single best-fitting skill from a fixed list.
Each skill has a name, a description of what it covers, the file it targets, and a
change_type (change_color / change_text / enable_disable).

Skills:
{skills_json}

Given the request and its parsed action/element, return ONLY a JSON object:
  {{"skill_name": "<one of the names above>", "confidence": "high" or "low"}}
or, if truly none of them fit:
  {{"skill_name": null, "confidence": "low"}}

Prefer a skill whose change_type matches the parsed action, and whose file/description
plausibly covers the mentioned element/page. Return ONLY the JSON object, no prose, no
markdown fences.
"""


def _skills_summary(skills: list[Skill]) -> str:
    return json.dumps(
        [{"name": s.name, "description": s.description, "file": s.file, "change_type": s.change_type} for s in skills],
        indent=2,
    )


def match_skill(request: str, intent, skills: list[Skill], model: str = DEFAULT_MODEL) -> Skill | None:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set — required for skill matching. Add it to .env.")
    if not skills:
        return None

    client = Groq(api_key=config.GROQ_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT_TEMPLATE.format(skills_json=_skills_summary(skills))},
            {
                "role": "user",
                "content": (
                    f"Request: {request}\n"
                    f"Parsed: page={intent.page!r} element={intent.element!r} "
                    f"action={intent.action!r} value={intent.value!r}"
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Groq did not return valid JSON for skill matching: {raw!r}") from exc

    skill_name = data.get("skill_name")
    if not skill_name:
        return None
    return next((s for s in skills if s.name == skill_name), None)  # None if the model hallucinated a name
