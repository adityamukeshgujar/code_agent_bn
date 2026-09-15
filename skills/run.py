"""Skill-based CR entrypoint — an alternative to agent/run.py's free-text
retrieval, for the fixed set of UI change types curated in skills/*.md.

    python -m skills.run --request "Change the submit button color to green" --root <path>

Flow: parse_intent (intent/intent_parser.py) -> match the request to one of
the hand-authored skills (skills/matcher.py) -> read that skill's target
file and pinpoint the exact line (skills/executor.py, reusing intent/
localizer.py's line-matching + styling-resolution helpers).

Reduced scope, intentionally: this ONLY identifies the code and describes
the change needed. It never generates a patch, writes a file, or touches
git — unlike agent/run.py, there is no --apply/--push-pr here yet.
"""
from __future__ import annotations

import json

from intent.intent_parser import parse_intent
from skills.executor import identify
from skills.loader import load_skills
from skills.matcher import match_skill


def run(request: str, root: str) -> dict:
    intent = parse_intent(request)
    if intent.needs_clarification:
        return {"ok": False, "stage": "intent", "stop_reason": intent.clarification_question}

    skills = load_skills()
    skill = match_skill(request, intent, skills)
    if skill is None:
        return {
            "ok": False,
            "stage": "skill_match",
            "stop_reason": "No skill matched this request.",
            "available_skills": [s.name for s in skills],
        }

    result = identify(intent, skill, root)
    return {
        "ok": result.ok,
        "stage": "identify",
        "intent": intent.as_dict(),
        "matched_skill": skill.name,
        "identification": result.as_dict(),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--request", required=True, help="Natural-language change request")
    parser.add_argument("--root", required=True, help="Local path to the target repo")
    args = parser.parse_args()

    result = run(args.request, args.root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
