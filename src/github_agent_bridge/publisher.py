from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from .core import get_task
from .git import head_sha, run_git
from .security import validate_ai_tree
from .triggers import build_task_pr_body


class PublishError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise PublishError(proc.stderr.strip() or "command failed: " + " ".join(cmd))
    return proc.stdout.strip()


def _view_task_pr(repo: Path, branch: str) -> Optional[dict[str, Any]]:
    try:
        raw = _run(["gh", "pr", "view", branch, "--json", "number,url,state"], repo)
    except PublishError:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublishError(f"invalid `gh pr view` JSON for {branch}: {exc}") from exc
    return value if isinstance(value, dict) else None


def _verify_remote_task_branch(repo: Path, task_id: str, branch: str, base_sha: str) -> str:
    """Verify a pre-existing deterministic task branch is safe to reuse.

    This makes task publication recoverable when push succeeded but PR creation
    failed. We only reuse a branch if it differs from the pinned base exclusively
    under `.ai/` and its machine state contains the expected task/base commit.
    """
    remote = run_git(repo, "ls-remote", "--heads", "origin", branch, check=False).strip()
    if not remote:
        raise PublishError(f"remote task branch not found: {branch}")
    remote_sha = remote.split()[0]
    ref = f"refs/agent-bridge/published-{task_id.lower()}"
    run_git(repo, "fetch", "origin", f"+refs/heads/{branch}:{ref}")
    changed = run_git(repo, "diff", "--name-only", f"{base_sha}..{ref}", check=False)
    unsafe = [line for line in changed.splitlines() if line and not line.startswith(".ai/")]
    if unsafe:
        raise PublishError(f"refusing to reuse task branch with non-.ai changes: {', '.join(unsafe)}")
    raw_state = run_git(repo, "show", f"{ref}:.ai/state/tasks.json", check=False)
    if not raw_state:
        raise PublishError("remote task branch is missing .ai/state/tasks.json")
    try:
        state = json.loads(raw_state)
        task = state["tasks"][task_id]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PublishError(f"remote task branch does not contain expected task {task_id}") from exc
    if (task.get("base") or {}).get("commit") != base_sha:
        raise PublishError("remote task branch base commit does not match local task")
    return remote_sha


def _create_or_reuse_task_pr(repo: Path, task_id: str, branch: str, task: dict[str, Any], commit: str) -> dict[str, Any]:
    existing = _view_task_pr(repo, branch)
    if existing:
        state = str(existing.get("state") or "").upper()
        if state != "OPEN":
            raise PublishError(
                f"existing Task PR #{existing.get('number')} for {branch} is {state or 'not open'}; "
                "reopen it intentionally or create a new task instead of silently reusing a closed dispatch"
            )
        return {
            "task_id": task_id,
            "branch": branch,
            "commit": commit,
            "pr": existing["number"],
            "url": existing["url"],
            "reused": True,
        }
    body = build_task_pr_body(repo, task_id)
    _run([
        "gh", "pr", "create", "--head", branch, "--base", task["base"]["branch"],
        "--title", f"[AI Task] {task_id}: {task['title']}", "--body", body,
    ], repo)
    created = _view_task_pr(repo, branch)
    if not created:
        raise PublishError(f"Task branch {branch} was pushed, but the PR could not be resolved")
    if str(created.get("state") or "").upper() != "OPEN":
        raise PublishError(f"newly created Task PR #{created.get('number')} is not open")
    return {
        "task_id": task_id,
        "branch": branch,
        "commit": commit,
        "pr": created["number"],
        "url": created["url"],
        "reused": False,
    }


def publish_task(repo: Path, task_id: str) -> dict[str, Any]:
    """Publish `.ai/` task artifacts in an isolated worktree and open a Task PR.

    Publication is intentionally idempotent across the common partial-failure
    case where the remote task branch was pushed but `gh pr create` failed.
    """
    findings = validate_ai_tree(repo)
    if findings:
        raise PublishError("refusing to publish .ai with security findings: " + "; ".join(findings))
    task = get_task(repo, task_id)
    base_sha = task["base"]["commit"]
    branch = f"agent-bridge/{task_id.lower()}"

    remote = run_git(repo, "ls-remote", "--heads", "origin", branch, check=False).strip()
    if remote:
        commit = _verify_remote_task_branch(repo, task_id, branch, base_sha)
        return _create_or_reuse_task_pr(repo, task_id, branch, task, commit)

    with tempfile.TemporaryDirectory(prefix="agent-bridge-task-") as tmp:
        worktree = Path(tmp) / "worktree"
        run_git(repo, "worktree", "add", "--detach", str(worktree), base_sha)
        try:
            source_ai = repo / ".ai"
            if not source_ai.exists():
                raise PublishError(".ai is not initialized")
            target_ai = worktree / ".ai"
            if target_ai.exists():
                shutil.rmtree(target_ai)
            shutil.copytree(source_ai, target_ai)
            # Local runtime state must never be published.
            local_state = target_ai / "local"
            if local_state.exists():
                shutil.rmtree(local_state)
            run_git(worktree, "checkout", "-b", branch)
            run_git(worktree, "add", ".ai")
            staged = run_git(worktree, "diff", "--cached", "--name-only")
            if not staged.strip():
                raise PublishError("no .ai task artifacts to publish")
            run_git(worktree, "commit", "-m", f"ai(task): publish {task_id}")
            commit = head_sha(worktree)
            run_git(worktree, "push", "-u", "origin", branch)
        finally:
            run_git(repo, "worktree", "remove", "--force", str(worktree), check=False)

    return _create_or_reuse_task_pr(repo, task_id, branch, task, commit)
