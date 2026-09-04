from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    out = run_git(start, "rev-parse", "--show-toplevel")
    return Path(out).resolve()


def head_sha(repo: Path) -> str:
    return run_git(repo, "rev-parse", "HEAD")


def current_branch(repo: Path) -> str:
    return run_git(repo, "branch", "--show-current") or "DETACHED"


def resolve_ref(repo: Path, ref: str) -> str:
    return run_git(repo, "rev-parse", ref)


def changed_files_between(repo: Path, base: str, head: str) -> list[str]:
    out = run_git(repo, "diff", "--name-only", f"{base}..{head}", check=False)
    return [line for line in out.splitlines() if line.strip()]
