"""JSON API for the skills pipeline (skills/run.py's logic, but split into
an "apply" phase and a separate, human-gated "push" phase instead of one
CLI call). Pure API — the frontend is the React app in webui/frontend/
(see its README for how to run it); this process only serves /api/*.

    python -m webui.app
    -> API on http://127.0.0.1:5000 (CORS-open, for the Vite dev server)

Flow: submit a CR -> watch progress (intent parsed -> skill matched ->
identified -> patch generated -> applied -> validated) -> review the diff
-> Confirm & Push (or Reject, which reverts) -> PR link.

Local-only (binds 127.0.0.1), single-process, in-memory job store — this is
a convenience UI for one person driving the pipeline by hand, not a hosted
service. Same real backend as the CLI: real Groq calls, real Qdrant, real
tree-sitter parsing, real `npm run lint`/`build` subprocesses, real git/
GitHub push — nothing here is simulated.

Only change_color skills can reach a pushable patch today (patcher.py's
current coverage) — change_text/enable_disable requests still identify
correctly but stop before a patch, same as the CLI.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid

from flask import Flask, jsonify, request

from indexer import config
from intent.intent_parser import parse_intent
from patcher.patcher import apply_patch, generate_patch, revert_patch
from patcher.validator import validate
from skills.executor import identify
from skills.loader import load_skills
from skills.matcher import match_skill
from vcs.git_ops import open_pr

app = Flask(__name__)


@app.after_request
def _allow_cors(response):
    # Local dev only (127.0.0.1-bound API, Vite dev server on a different
    # port) — permissive on purpose, not a public-facing deployment.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()

_PATCHABLE_CHANGE_TYPES = {"change_color"}


def _new_job() -> tuple[str, dict]:
    job_id = str(uuid.uuid4())
    job = {"status": "running", "message": "", "stages": [], "created": time.time()}
    with _LOCK:
        _JOBS[job_id] = job
    return job_id, job


def _log(job: dict, stage: str, **data) -> None:
    with _LOCK:
        job["stages"].append({"stage": stage, "ts": time.time(), **data})


def _run_pipeline(job_id: str, req_text: str, root: str) -> None:
    job = _JOBS[job_id]
    try:
        intent = parse_intent(req_text)
        _log(job, "intent_parsed", intent=intent.as_dict())
        if intent.needs_clarification:
            job["status"] = "needs_clarification"
            job["message"] = intent.clarification_question
            return

        skills = load_skills()
        skill = match_skill(req_text, intent, skills)
        if skill is None:
            job["status"] = "failed"
            job["message"] = "No skill matched this request."
            _log(job, "skill_match_failed", available_skills=[s.name for s in skills])
            return
        _log(job, "skill_matched", skill=skill.name, change_type=skill.change_type)

        result = identify(intent, skill, root)
        _log(job, "identified", identification=result.as_dict())
        if not result.ok:
            job["status"] = "failed"
            job["message"] = result.note or "Could not identify the target code."
            return

        if skill.change_type not in _PATCHABLE_CHANGE_TYPES:
            job["status"] = "identified_only"
            job["message"] = (
                f"Identified the target, but patch generation for '{skill.change_type}' isn't "
                "implemented yet — nothing was changed."
            )
            return

        try:
            patch = generate_patch(result, intent.value, root)
        except ValueError as exc:
            job["status"] = "failed"
            job["message"] = f"Could not generate a patch: {exc}"
            return
        _log(job, "patch_generated", target_file=patch.target_file, description=patch.description, diff=patch.diff_text)

        apply_patch(patch, root)
        _log(job, "patch_applied")

        val = validate(root, patch.target_file)
        _log(job, "validated", ok=val.ok, side=val.side, steps=[s.__dict__ for s in val.steps])
        if not val.ok:
            revert_patch(patch, root)
            job["status"] = "failed"
            job["message"] = "Validation failed — the patch was reverted, nothing left on disk."
            return

        with _LOCK:
            job["patch"] = patch
            job["result"] = result
            job["root"] = root
            job["request"] = req_text
        job["status"] = "awaiting_confirmation"
        job["message"] = "Applied and validated locally. Review the diff and confirm to push."

    except Exception as exc:  # keep the UI informative even on an unexpected failure
        job["status"] = "failed"
        job["message"] = f"Unexpected error: {exc}"
        _log(job, "error", traceback=traceback.format_exc())


def _push_pr(job_id: str) -> None:
    job = _JOBS[job_id]
    try:
        owner_repo = config.GITHUB_REPO
        if not owner_repo:
            job["status"] = "failed"
            job["message"] = "No GITHUB_REPO configured in .env — can't open a PR."
            return
        pr = open_pr(job["root"], owner_repo, job["patch"], job["request"], job["result"].required_change)
        _log(job, "pr_result", ok=pr.ok, pr_url=pr.pr_url, branch=pr.branch, error=pr.error)
        if pr.ok:
            job["status"] = "done"
            job["pr_url"] = pr.pr_url
            job["message"] = f"Pushed — PR opened: {pr.pr_url}"
        else:
            job["status"] = "failed"
            job["message"] = f"PR creation failed: {pr.error}"
    except Exception as exc:
        job["status"] = "failed"
        job["message"] = f"Unexpected error while pushing: {exc}"
        _log(job, "error", traceback=traceback.format_exc())


@app.post("/api/run")
def api_run():
    data = request.get_json(force=True) or {}
    req_text = (data.get("request") or "").strip()
    root = (data.get("root") or "").strip()
    if not req_text or not root:
        return jsonify({"error": "both 'request' and 'root' are required"}), 400

    job_id, job = _new_job()
    threading.Thread(target=_run_pipeline, args=(job_id, req_text, root), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/status/<job_id>")
def api_status(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "unknown job_id"}), 404
    return jsonify(
        {
            "status": job["status"],
            "message": job.get("message", ""),
            "stages": job["stages"],
            "pr_url": job.get("pr_url"),
        }
    )


@app.post("/api/confirm/<job_id>")
def api_confirm(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "unknown job_id"}), 404
    if job["status"] != "awaiting_confirmation":
        return jsonify({"error": f"job is not awaiting confirmation (status={job['status']!r})"}), 400
    job["status"] = "pushing"
    job["message"] = "Pushing to GitHub..."
    threading.Thread(target=_push_pr, args=(job_id,), daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/reject/<job_id>")
def api_reject(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "unknown job_id"}), 404
    if job["status"] == "awaiting_confirmation" and job.get("patch"):
        revert_patch(job["patch"], job["root"])
        _log(job, "reverted")
    job["status"] = "rejected"
    job["message"] = "Discarded — the local file was reverted, nothing was pushed."
    return jsonify({"ok": True})


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
