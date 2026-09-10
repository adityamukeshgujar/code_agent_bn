"""Parses a natural-language UI change request into structured intent.

    parse_intent(request: str) -> Intent

Uses Groq (chat-completion, JSON mode) rather than OpenAI per this project's
stack. If a value the change needs (e.g. a color) is missing, `Intent.
needs_clarification` is True and `clarification_question` says what to ask —
the caller must surface that and stop, not guess a value.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from groq import Groq

from indexer import config

DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# Actions that inherently need a concrete new value to apply — a bare
# "change the button's color" with no color given can't be patched.
_ACTIONS_REQUIRING_VALUE = {"change_color", "change_text", "change_size"}

_SYSTEM_PROMPT = """You turn a natural-language UI change request into a JSON object with exactly these keys:
  "page": the page/screen the user means (e.g. "Assessment"), or null if unclear
  "element": the UI element being changed (e.g. "submit button"), or null if unclear
  "action": one of "change_color", "change_text", "change_size", "resize", "reorder", "other"
  "value": the new value for the change (e.g. a color name/hex, new text, a size), or null if the user didn't give one

Return ONLY the JSON object. No prose, no markdown fences.
"""


@dataclass
class Intent:
    page: str | None
    element: str | None
    action: str | None
    value: str | None
    raw_request: str
    needs_clarification: bool = False
    clarification_question: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def parse_intent(request: str, model: str = DEFAULT_MODEL) -> Intent:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set — required for intent parsing. Add it to .env.")

    client = Groq(api_key=config.GROQ_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": request},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content
    try:
        data = _extract_json(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Groq did not return valid JSON for intent parsing: {raw!r}") from exc

    page = data.get("page") or None
    element = data.get("element") or None
    action = data.get("action") or None
    value = data.get("value") or None

    missing: list[str] = []
    if not page:
        missing.append("which page")
    if not element:
        missing.append("which element")
    if action in _ACTIONS_REQUIRING_VALUE and not value:
        missing.append("what value to change it to")

    needs_clarification = bool(missing)
    clarification_question = (
        "Could you clarify " + " and ".join(missing) + "?" if needs_clarification else None
    )

    return Intent(
        page=page,
        element=element,
        action=action,
        value=value,
        raw_request=request,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", help="Natural-language change request")
    args = parser.parse_args()
    intent = parse_intent(args.request)
    print(json.dumps(intent.as_dict(), indent=2))


if __name__ == "__main__":
    main()
