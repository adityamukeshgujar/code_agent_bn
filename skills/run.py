"""Skill-based CR entrypoint — an alternative to agent/run.py's free-text
retrieval, for the fixed set of UI change types curated in skills/*.md.

    python -m skills.run --request "Change the submit button color to green" --root <path>

Flow: parse_intent (intent/intent_parser.py) -> match the request to one of
the hand-authored skills (skills/matcher.py) -> read that skill's target
file and pinpoint the exact line (skills/executor.py, reusing intent/
localizer.py's line-matching + styling-resolution helpers) -> optionally
patch/validate/push, reusing the exact same patcher/validator/git_ops
modules agent/run.py uses.

Same opt-in safety gates as agent/run.py:
  - Default: identify only. Prints what needs to change and stops. No
    writes at all.
  - --apply: generates + writes the patch and runs the validator (lint/
    typecheck/build/test), reverting on failure. Only implemented for
    change_color skills today (patcher.py doesn't yet generate patches for
    change_text/enable_disable) — for those, --apply stops with a clear
    "not implemented" reason rather than guessing at an edit.
  - --push-pr: additionally branches/commits/pushes/opens a GitHub PR
    (implies --apply).
  - --allow-shared: required to proceed past an is_shared flag from the
    identification.
"""
from __future__ import annotations

import json

from indexer import config
from intent.intent_parser import parse_intent
from patcher.patcher import apply_patch, generate_patch, revert_patch
from patcher.validator import validate
from skills.executor import identify
from skills.loader import load_skills
from skills.matcher import match_skill
from vcs.git_ops import open_pr

MAX_VALIDATION_RETRIES = 2
_PATCHABLE_CHANGE_TYPES = {"change_color"}  # patcher.py's current coverage


def run(
    request: str,
    root: str,
    github_repo: str | None = None,
    apply: bool = False,
    push_pr: bool = False,
    allow_shared: bool = False,
) -> dict:
    apply = apply or push_pr  # opening a PR implies writing the patch first

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
    out: dict = {
        "ok": result.ok,
        "stage": "identify",
        "intent": intent.as_dict(),
        "matched_skill": skill.name,
        "identification": result.as_dict(),
    }
    if not result.ok:
        return out
    if result.is_shared and not allow_shared:
        out.update(ok=False, stage="stopped", stop_reason=f"Shared/global style flagged, refusing without --allow-shared: {result.shared_note}")
        return out

    if not apply:
        out.update(stage="stopped", stop_reason="Identify-only (pass --apply to write + validate, --push-pr to also open a PR).")
        return out

    if skill.change_type not in _PATCHABLE_CHANGE_TYPES:
        out.update(
            ok=False,
            stage="stopped",
            stop_reason=(
                f"Patch generation for change_type {skill.change_type!r} isn't implemented yet "
                f"(patcher.py currently only generates patches for: {sorted(_PATCHABLE_CHANGE_TYPES)})."
            ),
        )
        return out

    try:
        patch = generate_patch(result, intent.value, root)
    except ValueError as exc:
        out.update(ok=False, stage="stopped", stop_reason=f"Could not generate a patch: {exc}")
        return out
    out["patch"] = {"target_file": patch.target_file, "description": patch.description, "diff": patch.diff_text}

    apply_patch(patch, root)
    attempt = 0
    validation = validate(root, patch.target_file)
    while not validation.ok and attempt < MAX_VALIDATION_RETRIES:
        attempt += 1
        validation = validate(root, patch.target_file)  # see agent/run.py's note on this retry loop's current limits
    out["validation"] = {"ok": validation.ok, "side": validation.side, "steps": [s.__dict__ for s in validation.steps]}

    if not validation.ok:
        revert_patch(patch, root)
        out.update(ok=False, stage="stopped", stop_reason="Validation failed after retries — patch reverted, not proceeding to PR.")
        return out

    if not push_pr:
        out.update(ok=True, stage="applied", stop_reason="Applied and validated locally (pass --push-pr to open a PR).")
        return out

    owner_repo = github_repo or config.GITHUB_REPO
    if not owner_repo:
        out.update(ok=False, stage="stopped", stop_reason="No GITHUB_REPO configured (env or --github-repo) — can't open a PR.")
        return out

    pr_result = open_pr(root, owner_repo, patch, request, result.required_change)
    out["pr_result"] = {"ok": pr_result.ok, "pr_url": pr_result.pr_url, "branch": pr_result.branch, "error": pr_result.error}
    out["ok"] = pr_result.ok
    out["stage"] = "pr_opened" if pr_result.ok else "stopped"
    if not pr_result.ok:
        out["stop_reason"] = f"PR creation failed: {pr_result.error}"
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--request", required=True, help="Natural-language change request")
    parser.add_argument("--root", required=True, help="Local path to the target repo")
    parser.add_argument("--github-repo", help="owner/name (defaults to GITHUB_REPO from .env)")
    parser.add_argument("--apply", action="store_true", help="Write the patch and run the validator (default: identify only)")
    parser.add_argument("--push-pr", action="store_true", help="Also branch/commit/push and open a GitHub PR (implies --apply)")
    parser.add_argument("--allow-shared", action="store_true", help="Proceed even if the target style is flagged as shared/global")
    args = parser.parse_args()

    result = run(
        request=args.request,
        root=args.root,
        github_repo=args.github_repo,
        apply=args.apply,
        push_pr=args.push_pr,
        allow_shared=args.allow_shared,
    )
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
