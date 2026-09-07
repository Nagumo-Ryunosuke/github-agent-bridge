"""Repeatable repository onboarding from a GitHub remote URL."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from .config import configure_review, configure_writer, load_config
from .core import init_repo
from .doctor import doctor_report
from .git import repo_root, run_git
from .skill_install import install_skill


def normalize_remote(remote: str) -> tuple[str, str]:
    """Accept clone URLs only, never credentials, arbitrary hosts or Git options."""
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
        r"([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9_.-]+?)(?:\.git)?/?",
        remote.strip(), re.IGNORECASE,
    )
    if not match or match[2] in {".", ".."}:
        raise ValueError("Provide a GitHub HTTPS or git@github.com clone URL without credentials, query parameters or fragments")
    slug = f"{match[1]}/{match[2]}"
    return slug, f"https://github.com/{slug}.git"


def destination_for(slug: str, directory: Optional[str] = None) -> Path:
    if directory:
        return Path(directory).expanduser().resolve()
    return (Path.home() / "github-agent-bridge" / "repos" / slug.lower()).resolve()


def check_destination(destination: Path, slug: str) -> bool:
    if not destination.exists():
        return False
    if not destination.is_dir() or not (destination / ".git").exists():
        raise ValueError(f"Destination already exists and is not a Git checkout: {destination}; use --directory for another location")
    if repo_root(destination) != destination.resolve():
        raise ValueError("Destination must be the checkout root")
    existing, _ = normalize_remote(run_git(destination, "remote", "get-url", "origin"))
    if existing.lower() != slug.lower():
        raise ValueError(f"Destination belongs to {existing}, not {slug}; no files were changed")
    return True


def _run(command: list[str], cwd: Optional[Path] = None) -> str:
    proc = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8",
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"Command failed: {command[0]}")
    return proc.stdout.strip()


def infer_tests(repo: Path) -> list[str]:
    """Use recognizable test suites; never silently approve a project with no tests."""
    package = repo / "package.json"
    if package.exists():
        scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        test = scripts.get("test", "")
        if isinstance(test, str) and test.strip() and "no test specified" not in test:
            manager = "pnpm" if (repo / "pnpm-lock.yaml").exists() else "yarn" if (repo / "yarn.lock").exists() else "npm"
            return [f"{manager} test"]
    if (repo / "Cargo.toml").exists():
        return ["cargo test"]
    if (repo / "go.mod").exists():
        return ["go test ./..."]
    tests = list((repo / "tests").glob("test*.py"))
    if tests:
        python = subprocess.list2cmdline([sys.executable]) if os.name == "nt" else shlex.quote(sys.executable)
        uses_pytest = any(re.search(r"(?:^|\n)\s*(?:import pytest|from pytest\b|def test_)", p.read_text(encoding="utf-8")) for p in tests)
        command = f"{python} -m pytest" if uses_pytest else f"{python} -m unittest discover -s tests -v"
        # Worktrees must import their own source, not an editable install elsewhere.
        prefix = 'set "PYTHONPATH=src" && ' if os.name == "nt" else "PYTHONPATH=src "
        return [prefix + command] if (repo / "src").is_dir() else [command]
    return []


def prepare_repository(
    remote: str, *, directory: Optional[str] = None,
    test_commands: Optional[list[str]] = None,
    runner: Callable[..., str] = _run,
) -> dict[str, Any]:
    slug, url = normalize_remote(remote)
    destination = destination_for(slug, directory)
    reused = check_destination(destination, slug)
    metadata = json.loads(runner(["gh", "api", f"repos/{slug}"]))
    if not metadata.get("permissions", {}).get("push"):
        raise RuntimeError(f"GitHub account needs Contents write and Pull requests write access to {slug}; rerun the same connect command after granting access")
    if not reused:
        destination.parent.mkdir(parents=True, exist_ok=True)
        runner(["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
                "clone", "--", url, str(destination)])
    # Empty repositories cannot support exact-base task contracts yet.
    run_git(destination, "rev-parse", "--verify", "HEAD")
    # Scope authentication helpers to this checkout, not the user's global Git config.
    run_git(destination, "config", "credential.https://github.com.helper", "!gh auth git-credential")
    if not run_git(destination, "config", "user.name", check=False) or not run_git(destination, "config", "user.email", check=False):
        user = json.loads(runner(["gh", "api", "user"]))
        if not run_git(destination, "config", "user.name", check=False):
            run_git(destination, "config", "user.name", user["login"])
        if not run_git(destination, "config", "user.email", check=False):
            run_git(destination, "config", "user.email", f"{user['id']}+{user['login']}@users.noreply.github.com")
    init_repo(destination)
    config = load_config(destination)
    github = config["github"]
    configure_writer(destination, mode=github["mode"], repositories=[slug])
    commands = test_commands if test_commands is not None else config["review"]["test_commands"] or infer_tests(destination)
    codex = config["review"].get("codex_command", "codex")
    if codex == "codex":
        codex = shutil.which("codex") or codex
    configure_review(destination, test_commands=commands, codex_command=codex)
    install_skill(scope="repo", repo=destination)
    report = doctor_report(destination)
    return {
        "repository": slug, "directory": str(destination), "reused": reused,
        "repository_prepared": True, "test_commands": commands,
        "zero_touch_ready": report["zero_touch_ready"],
        "pending": [c for c in report["checks"] if c["critical"] and c["status"] != "pass"],
    }
