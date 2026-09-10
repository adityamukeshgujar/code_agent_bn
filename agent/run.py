"""Single entrypoint tying phases 1-5 together for one workflow run.

    python -m agent.run --request "Change the color of the submit button in Assessment Page to green" --root <repo>

Safety gates (each is opt-in, matching CLAUDE.md's "never auto-merge / always
a PR for review" and "ask before proceeding if ambiguous" constraints):
  - Default (no flags beyond --request/--root): dry run. Parses intent,
    localizes the target, generates the diff, PRINTS it, and stops. No
    file on disk is touched.
  - --apply: additionally writes the patch and runs the validator (lint /
    typecheck / build / test). Reverts the write if validation fails.
  - --allow-shared: required to go past a localization that is flagged
    is_shared — without it, the agent stops and reports the shared-style
    warning instead of silently editing something that affects other pages.
  - --push-pr: additionally branches, commits, pushes, and opens a real
    GitHub PR (implies --apply). Never runs without this flag. Never
    commits to the default branch, never force-pushes (see vcs/git_ops.py).

Every stage's output (parsed intent, retrieval hits, localized target, diff,
validation result, PR URL) is logged as it happens, and the full structured
log is also available via run(...) -> RunLog for programmatic use / audit.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field

from indexer import config
from intent.intent_parser import parse_intent
from intent.localizer import localize
from patcher.patcher import apply_patch, generate_patch, revert_patch
from patcher.validator import validate
from vcs.git_ops import open_pr

MAX_VALIDATION_RETRIES = 2


@dataclass
class RunLog:
    request: str
    stages: list[dict] = field(default_factory=list)
    ok: bool = False
    stop_reason: str | None = None
    pr_url: str | None = None

    def log(self, stage: str, **data) -> None:
        entry = {"stage": stage, **data}
        self.stages.append(entry)
        print(f"\n=== [{stage}] ===")
        for k, v in data.items():
            if isinstance(v, str) and "\n" in v:
                print(f"{k}:\n{v}")
            else:
                print(f"{k}: {v}")

    def as_dict(self) -> dict:
        return asdict(self)


def run(
    request: str,
    root: str,
    github_repo: str | None = None,
    apply: bool = False,
    push_pr: bool = False,
    allow_shared: bool = False,
) -> RunLog:
    log = RunLog(request=request)
    apply = apply or push_pr  # opening a PR implies writing the patch first

    # --- Phase 3a: intent parsing -------------------------------------------------
    intent = parse_intent(request)
    log.log("intent_parsed", **intent.as_dict())
    if intent.needs_clarification:
        log.stop_reason = f"Clarification needed: {intent.clarification_question}"
        log.log("stopped", reason=log.stop_reason)
        return log

    # --- Phase 3b: localization -----------------------------------------------
    localization = localize(intent, root)
    log.log(
        "localized",
        ok=localization.ok,
        file_path=localization.file_path,
        lines=[localization.start_line, localization.end_line],
        styling_mechanism=localization.styling_mechanism,
        style_ref=localization.style_ref,
        style_file=localization.style_file,
        is_shared=localization.is_shared,
        shared_note=localization.shared_note,
        summary=localization.summary,
        note=localization.note,
    )
    if not localization.ok:
        log.stop_reason = localization.note or "Localization failed."
        log.log("stopped", reason=log.stop_reason)
        return log
    if localization.ambiguous_files:
        log.stop_reason = f"Ambiguous target — multiple files matched equally: {localization.ambiguous_files}. Refine the request."
        log.log("stopped", reason=log.stop_reason)
        return log
    if localization.is_shared and not allow_shared:
        log.stop_reason = f"Shared/global style flagged, refusing without --allow-shared: {localization.shared_note}"
        log.log("stopped", reason=log.stop_reason)
        return log

    # --- Phase 4a: patch generation (pure — no writes yet) -------------------
    try:
        patch = generate_patch(localization, intent.value, root)
    except ValueError as exc:
        log.stop_reason = f"Could not generate a patch: {exc}"
        log.log("stopped", reason=log.stop_reason)
        return log
    log.log("patch_generated", target_file=patch.target_file, description=patch.description, diff=patch.diff_text)

    if not apply:
        log.ok = True
        log.stop_reason = "Dry run (pass --apply to write + validate, --push-pr to also open a PR)."
        log.log("stopped", reason=log.stop_reason)
        return log

    # --- Phase 4b: apply + validate, with a bounded retry loop -----------------
    apply_patch(patch, root)
    log.log("patch_applied", target_file=patch.target_file)

    attempt = 0
    validation = validate(root, patch.target_file)
    while not validation.ok and attempt < MAX_VALIDATION_RETRIES:
        attempt += 1
        failure = validation.first_failure()
        log.log(
            "validation_failed",
            attempt=attempt,
            step=failure.name if failure else None,
            output=(failure.output if failure else ""),
        )
        # NOTE: patcher.py is currently rule-based, not LLM-regenerated, so
        # re-running generate_patch on the same inputs reproduces the same
        # edit — this retry loop is structurally in place per the spec, but
        # only becomes meaningful once patch generation can take the
        # validator's error text as feedback (e.g. an LLM-based patcher).
        validation = validate(root, patch.target_file)

    log.log("validation_result", ok=validation.ok, side=validation.side, steps=[s.__dict__ for s in validation.steps])

    if not validation.ok:
        revert_patch(patch, root)
        log.stop_reason = "Validation failed after retries — patch reverted, not proceeding to PR."
        log.log("stopped", reason=log.stop_reason)
        return log

    if not push_pr:
        log.ok = True
        log.stop_reason = "Applied and validated locally (pass --push-pr to open a PR)."
        log.log("stopped", reason=log.stop_reason)
        return log

    # --- Phase 5: git integration ----------------------------------------------
    owner_repo = github_repo or config.GITHUB_REPO
    if not owner_repo:
        log.stop_reason = "No GITHUB_REPO configured (env or --github-repo) — can't open a PR."
        log.log("stopped", reason=log.stop_reason)
        return log

    pr_result = open_pr(root, owner_repo, patch, request, localization.summary)
    log.log("pr_result", ok=pr_result.ok, pr_url=pr_result.pr_url, branch=pr_result.branch, error=pr_result.error)

    if pr_result.ok:
        log.ok = True
        log.pr_url = pr_result.pr_url
    else:
        log.stop_reason = f"PR creation failed: {pr_result.error}"
    return log


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--request", required=True, help="Natural-language change request")
    parser.add_argument("--root", required=True, help="Local path to the target repo")
    parser.add_argument("--github-repo", help="owner/name (defaults to GITHUB_REPO from .env)")
    parser.add_argument("--apply", action="store_true", help="Write the patch and run the validator (default: dry run, diff only)")
    parser.add_argument("--push-pr", action="store_true", help="Also branch/commit/push and open a GitHub PR (implies --apply)")
    parser.add_argument("--allow-shared", action="store_true", help="Proceed even if the target style is flagged as shared/global")
    args = parser.parse_args()

    log = run(
        request=args.request,
        root=args.root,
        github_repo=args.github_repo,
        apply=args.apply,
        push_pr=args.push_pr,
        allow_shared=args.allow_shared,
    )
    print("\n=== [summary] ===")
    print(json.dumps({"ok": log.ok, "stop_reason": log.stop_reason, "pr_url": log.pr_url}, indent=2))
    sys.exit(0 if log.ok else 1)


if __name__ == "__main__":
    main()
