"""Sync a local checkout from a GitHub repo, so the indexer always has a real
filesystem tree to walk (see index_repo.py's docstring for why the indexer
works off a local clone rather than the GitHub API).

    sync_from_github(repo_url, clone_dir, branch=None) -> Path

- If `clone_dir` isn't a git checkout yet: `git clone` it (shallow `--branch`
  checkout if `branch` is given).
- If it already is one: fetch + hard-reset to the remote branch, discarding
  any local changes — this is meant for a read-only mirror used for
  indexing, not a working copy you edit by hand. (Phase 4/5's patcher/git_ops
  will use their own separate working copy once built.)

Private repos: if GITHUB_TOKEN is set (see indexer/config.py), it's injected
into the URL for auth. Otherwise a plain `git clone`/`fetch` runs, which
works for public repos or relies on whatever git credential helper is
already configured locally — note that in a non-interactive context a
credential prompt will just fail rather than pausing for input.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import config

_HTTPS_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")
_SSH_URL_RE = re.compile(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$")


def _run_git(args: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def _authed_url(repo_url: str) -> str:
    if config.GITHUB_TOKEN and repo_url.startswith("https://github.com/"):
        return repo_url.replace("https://github.com/", f"https://{config.GITHUB_TOKEN}@github.com/", 1)
    return repo_url


def repo_name_from_url(repo_url: str) -> str:
    name = repo_url.rstrip("/").rsplit("/", 1)[-1]
    return name[: -len(".git")] if name.endswith(".git") else name


def owner_repo_from_url(repo_url: str) -> str | None:
    """'https://github.com/owner/repo(.git)?' or 'git@github.com:owner/repo.git'
    -> 'owner/repo', for use with the GitHub REST API (vcs/git_ops.py takes
    exactly this form). None if it doesn't look like a GitHub URL at all —
    the caller should fall back to something explicit (e.g. GITHUB_REPO)
    rather than guess."""
    for pattern in (_HTTPS_URL_RE, _SSH_URL_RE):
        m = pattern.match(repo_url.strip())
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    return None


def sync_from_github(repo_url: str, clone_dir: str | Path, branch: str | None = None) -> Path:
    clone_dir = Path(clone_dir)
    url = _authed_url(repo_url)

    if (clone_dir / ".git").exists():
        print(f"Updating existing checkout at {clone_dir} ...")
        _run_git(["fetch", "--all", "--prune"], cwd=str(clone_dir))
        ref = branch or _run_git(["remote", "show", "origin"], cwd=str(clone_dir))
        if not branch:
            # parse "HEAD branch: main" out of `git remote show origin`
            ref = next(
                (line.split(":", 1)[1].strip() for line in ref.splitlines() if "HEAD branch" in line),
                "main",
            )
        _run_git(["checkout", ref], cwd=str(clone_dir))
        _run_git(["reset", "--hard", f"origin/{ref}"], cwd=str(clone_dir))
    else:
        print(f"Cloning {repo_url} into {clone_dir} ...")
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--depth", "1"]
        if branch:
            args += ["--branch", branch]
        args += [url, str(clone_dir)]
        _run_git(args)

    return clone_dir
