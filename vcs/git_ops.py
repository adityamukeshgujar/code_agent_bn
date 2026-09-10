"""Branch -> commit -> push -> open PR via the GitHub REST API.

Never commits directly to the repo's default branch. Never force-pushes.
Refuses to run at all if the working tree already has uncommitted changes
(so it can't be blamed for losing something that was already there), and
always restores whatever branch was checked out before it started, win or
lose — the new branch is still created and pushed, the user's own working
branch just isn't left switched out from under them.

    open_pr(repo_root, owner_repo, patch, request_text, summary_text) -> PrResult
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import requests

from indexer import config

GITHUB_API = "https://api.github.com"


@dataclass
class PrResult:
    ok: bool
    pr_url: str | None = None
    pr_number: int | None = None
    branch: str | None = None
    error: str | None = None


def _run_git(args: list[str], cwd: str) -> str:
    import subprocess

    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def working_tree_is_clean(repo_root: str) -> bool:
    return _run_git(["status", "--porcelain"], repo_root).strip() == ""


def current_branch(repo_root: str) -> str:
    return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root).strip()


def _github_headers() -> dict:
    if not config.GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set — required for Phase 5. Add it to .env.")
    return {"Authorization": f"Bearer {config.GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}


def get_default_branch(owner_repo: str) -> str:
    resp = requests.get(f"{GITHUB_API}/repos/{owner_repo}", headers=_github_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()["default_branch"]


def create_branch_and_commit(
    repo_root: str, branch_name: str, base_branch: str, files_changed: list[str], commit_message: str
) -> None:
    _run_git(["fetch", "origin", base_branch], repo_root)
    _run_git(["checkout", "-B", branch_name, f"origin/{base_branch}"], repo_root)
    _run_git(["add", *files_changed], repo_root)
    _run_git(["commit", "-m", commit_message], repo_root)


def push_branch(repo_root: str, branch_name: str) -> None:
    _run_git(["push", "--set-upstream", "origin", branch_name], repo_root)  # never --force


def open_pull_request(owner_repo: str, branch_name: str, base_branch: str, title: str, body: str) -> dict:
    resp = requests.post(
        f"{GITHUB_API}/repos/{owner_repo}/pulls",
        headers=_github_headers(),
        json={"title": title, "head": branch_name, "base": base_branch, "body": body},
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"GitHub PR creation failed ({resp.status_code}): {resp.text}")
    return resp.json()


def build_pr_body(request_text: str, summary_text: str, diff_text: str) -> str:
    return (
        "## Original request\n\n"
        f"> {request_text}\n\n"
        "## What changed and why\n\n"
        f"{summary_text}\n\n"
        "## Diff\n\n"
        f"```diff\n{diff_text}\n```\n\n"
        "---\n"
        "_Opened automatically by codebase-change-agent._\n"
    )


def open_pr(
    repo_root: str,
    owner_repo: str,
    patch,
    request_text: str,
    summary_text: str,
    branch_prefix: str = "agent",
) -> PrResult:
    original_branch: str | None = None
    try:
        if not working_tree_is_clean(repo_root):
            return PrResult(
                ok=False,
                error="Working tree has uncommitted changes — refusing to touch branches. Commit or stash first.",
            )

        original_branch = current_branch(repo_root)
        base_branch = get_default_branch(owner_repo)
        slug = re.sub(r"[^a-z0-9]+", "-", request_text.lower()).strip("-")[:40]
        branch_name = f"{branch_prefix}/{slug}-{int(time.time())}"

        create_branch_and_commit(
            repo_root,
            branch_name,
            base_branch,
            files_changed=[patch.target_file],
            commit_message=f"{summary_text}\n\nRequest: {request_text}",
        )
        push_branch(repo_root, branch_name)

        body = build_pr_body(request_text, summary_text, patch.diff_text)
        pr = open_pull_request(owner_repo, branch_name, base_branch, title=request_text[:70], body=body)
        return PrResult(ok=True, pr_url=pr["html_url"], pr_number=pr["number"], branch=branch_name)

    except Exception as exc:
        return PrResult(ok=False, error=str(exc))

    finally:
        if original_branch is not None:
            try:
                _run_git(["checkout", original_branch], repo_root)
            except RuntimeError:
                pass  # best-effort — don't mask the real result with a restore failure
