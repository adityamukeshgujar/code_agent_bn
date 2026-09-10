"""Runs linter -> typechecker -> build -> test suite against a working copy
after a patch has been applied, in that order, stopping at the first
failure.

    validate(repo_root, changed_file) -> ValidationResult

Frontend steps come straight from the nearest package.json's own "scripts"
— only the ones that actually exist are run; a missing script (e.g. no
typecheck script in a plain-JS project) is reported as skipped with a
reason, not silently ignored. Backend has no fixed toolchain assumed: if the
repo defines one (ruff/flake8/pylint, mypy, pytest — detected via
requirements.txt or config files) it's used; otherwise the fallback is a
plain `python -m py_compile` syntax check, clearly labeled as a minimal
fallback rather than a real lint/test pass.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT = 300


@dataclass
class StepResult:
    name: str
    ran: bool
    ok: bool
    command: str | None = None
    output: str = ""
    skipped_reason: str | None = None


@dataclass
class ValidationResult:
    ok: bool
    side: str  # "frontend" | "backend" | "unknown"
    steps: list[StepResult] = field(default_factory=list)

    def first_failure(self) -> StepResult | None:
        for step in self.steps:
            if step.ran and not step.ok:
                return step
        return None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "side": self.side,
            "steps": [
                {
                    "name": s.name,
                    "ran": s.ran,
                    "ok": s.ok,
                    "command": s.command,
                    "skipped_reason": s.skipped_reason,
                    "output": s.output[-4000:],  # keep logs from ballooning
                }
                for s in self.steps
            ],
        }


def _run(command: list[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, shell=False
        )
    except FileNotFoundError as exc:
        return False, f"Command not found: {exc}"
    except subprocess.TimeoutExpired as exc:
        return False, f"Timed out after {timeout}s: {exc}"
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output


def _find_nearest(start: Path, filename: str, stop_at: Path) -> Path | None:
    current = start
    while True:
        candidate = current / filename
        if candidate.exists():
            return candidate
        if current == stop_at or current.parent == current:
            return None
        current = current.parent


def _resolve_exe(name: str) -> str | None:
    """shutil.which() finds npm/npx fine (it checks PATHEXT), but on Windows
    they're .cmd shims — subprocess.run(shell=False) needs the resolved path
    (with extension) to actually launch them; the bare name fails with
    WinError 2 even though `which` succeeded."""
    return shutil.which(name)


def _npm_exists() -> bool:
    return _resolve_exe("npm") is not None


def _validate_frontend(repo_root: Path, package_json_path: Path) -> list[StepResult]:
    package_dir = package_json_path.parent
    scripts: dict[str, str] = json.loads(package_json_path.read_text(encoding="utf-8")).get("scripts", {})
    steps: list[StepResult] = []

    npm = _resolve_exe("npm")
    if not npm:
        return [StepResult("lint", ran=False, ok=False, skipped_reason="npm not found on PATH")]

    # lint
    if "lint" in scripts:
        cmd = [npm, "run", "lint"]
        ok, out = _run(cmd, package_dir)
        steps.append(StepResult("lint", ran=True, ok=ok, command="npm run lint", output=out))
    else:
        steps.append(StepResult("lint", ran=False, ok=True, skipped_reason="no 'lint' script in package.json"))
    if not steps[-1].ok and steps[-1].ran:
        return steps

    # typecheck — only meaningful for a TS project
    has_tsconfig = (package_dir / "tsconfig.json").exists()
    if "typecheck" in scripts:
        cmd = [npm, "run", "typecheck"]
        ok, out = _run(cmd, package_dir)
        steps.append(StepResult("typecheck", ran=True, ok=ok, command="npm run typecheck", output=out))
    elif has_tsconfig:
        npx = _resolve_exe("npx") or npm  # fall back rather than hard-fail if only npm resolved
        cmd = [npx, "tsc", "--noEmit"]
        ok, out = _run(cmd, package_dir)
        steps.append(StepResult("typecheck", ran=True, ok=ok, command="npx tsc --noEmit", output=out))
    else:
        steps.append(
            StepResult("typecheck", ran=False, ok=True, skipped_reason="no tsconfig.json / typecheck script (plain JS project)")
        )
    if not steps[-1].ok and steps[-1].ran:
        return steps

    # build
    if "build" in scripts:
        cmd = [npm, "run", "build"]
        ok, out = _run(cmd, package_dir)
        steps.append(StepResult("build", ran=True, ok=ok, command="npm run build", output=out))
    else:
        steps.append(StepResult("build", ran=False, ok=True, skipped_reason="no 'build' script in package.json"))
    if not steps[-1].ok and steps[-1].ran:
        return steps

    # tests
    if "test" in scripts:
        cmd = [npm, "test", "--", "--watchAll=false"]
        ok, out = _run(cmd, package_dir)
        steps.append(StepResult("test", ran=True, ok=ok, command="npm test -- --watchAll=false", output=out))
    else:
        steps.append(StepResult("test", ran=False, ok=True, skipped_reason="no 'test' script in package.json"))

    return steps


def _validate_backend(repo_root: Path, changed_file: Path, backend_dir: Path) -> list[StepResult]:
    steps: list[StepResult] = []
    requirements = backend_dir / "requirements.txt"
    reqs_text = requirements.read_text(encoding="utf-8", errors="ignore") if requirements.exists() else ""

    def has_dep(name: str) -> bool:
        return name.lower() in reqs_text.lower()

    # lint
    if has_dep("ruff"):
        cmd = ["python", "-m", "ruff", "check", "."]
    elif has_dep("flake8"):
        cmd = ["python", "-m", "flake8", "."]
    elif has_dep("pylint"):
        cmd = ["python", "-m", "pylint", "."]
    else:
        cmd = None
    if cmd:
        ok, out = _run(cmd, backend_dir)
        steps.append(StepResult("lint", ran=True, ok=ok, command=" ".join(cmd), output=out))
    else:
        steps.append(StepResult("lint", ran=False, ok=True, skipped_reason="no backend linter configured in this repo (checked requirements.txt for ruff/flake8/pylint)"))
    if not steps[-1].ok and steps[-1].ran:
        return steps

    # typecheck
    if has_dep("mypy"):
        cmd = ["python", "-m", "mypy", "."]
        ok, out = _run(cmd, backend_dir)
        steps.append(StepResult("typecheck", ran=True, ok=ok, command=" ".join(cmd), output=out))
    else:
        steps.append(StepResult("typecheck", ran=False, ok=True, skipped_reason="mypy not in requirements.txt"))
    if not steps[-1].ok and steps[-1].ran:
        return steps

    # build — not generally applicable to a Python backend
    steps.append(StepResult("build", ran=False, ok=True, skipped_reason="no build step for a Python backend"))

    # tests
    has_tests_dir = (backend_dir / "tests").exists() or list(backend_dir.glob("test_*.py")) or list(backend_dir.glob("*_test.py"))
    if has_dep("pytest") or has_tests_dir:
        cmd = ["python", "-m", "pytest", "-q"]
        ok, out = _run(cmd, backend_dir)
        steps.append(StepResult("test", ran=True, ok=ok, command=" ".join(cmd), output=out))
    else:
        # Minimal fallback so a broken patch is still caught — not a
        # substitute for real tests, and reported as such.
        cmd = ["python", "-m", "py_compile", str(changed_file)]
        ok, out = _run(cmd, backend_dir)
        steps.append(
            StepResult(
                "test",
                ran=True,
                ok=ok,
                command=" ".join(cmd),
                output=out,
                skipped_reason="no pytest/tests/ in this repo — fell back to a syntax-only py_compile check, NOT a real test run",
            )
        )
    return steps


def validate(repo_root: str | Path, changed_file: str) -> ValidationResult:
    repo_root = Path(repo_root).resolve()
    changed_path = repo_root / changed_file

    package_json = _find_nearest(changed_path.parent, "package.json", repo_root)
    requirements_txt = _find_nearest(changed_path.parent, "requirements.txt", repo_root)

    if package_json is not None and (requirements_txt is None or len(str(package_json.parent)) >= len(str(requirements_txt.parent))):
        side = "frontend"
        steps = _validate_frontend(repo_root, package_json)
    elif requirements_txt is not None:
        side = "backend"
        steps = _validate_backend(repo_root, changed_path, requirements_txt.parent)
    elif changed_file.endswith(".py"):
        side = "backend"
        ok, out = _run_py_compile_only(changed_path)
        steps = [StepResult("test", ran=True, ok=ok, output=out)]
    else:
        side = "unknown"
        steps = [StepResult("lint", ran=False, ok=True, skipped_reason="could not find package.json or requirements.txt above this file")]

    ok = all(s.ok for s in steps)
    return ValidationResult(ok=ok, side=side, steps=steps)


def _run_py_compile_only(changed_path: Path) -> tuple[bool, str]:
    ok, out = _run(["python", "-m", "py_compile", str(changed_path)], changed_path.parent)
    return ok, out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--file", required=True, help="Repo-relative path of the changed file")
    args = parser.parse_args()
    result = validate(args.root, args.file)
    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
