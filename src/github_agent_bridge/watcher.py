from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .config import load_config
from .core import get_task, now_iso
from .reviewer import ReviewResult, review_pr_head
from .triggers import codex_review_marker, parse_codex_review_marker, parse_implementation_marker


def watcher_state_path(repo: Path) -> Path:
    proc = subprocess.run(["git", "rev-parse", "--git-path", "agent-bridge/watcher.json"], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"cannot resolve git-local watcher state: {proc.stderr.strip()}")
    path = Path(proc.stdout.strip())
    return path if path.is_absolute() else (repo / path).resolve()


def load_watcher_state(repo: Path) -> dict[str, Any]:
    path = watcher_state_path(repo)
    if not path.exists():
        return {"schema_version": 1, "reviewed_heads": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_watcher_state(repo: Path, state: dict[str, Any]) -> None:
    path = watcher_state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_implementation_prs(repo: Path) -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["gh", "pr", "list", "--state", "open", "--json", "number,title,body,headRefOid,headRefName,baseRefName,url,isCrossRepository"],
        cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {proc.stderr.strip()}")
    data = json.loads(proc.stdout or "[]")
    return [item for item in data if parse_implementation_marker(item.get("body") or "")]


def _task_from_git_ref(repo: Path, ref: str, task_id: str) -> Optional[dict[str, Any]]:
    proc = subprocess.run(
        ["git", "show", f"{ref}:.ai/state/tasks.json"],
        cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return None
    try:
        state = json.loads(proc.stdout)
        task = state.get("tasks", {}).get(task_id)
    except (json.JSONDecodeError, AttributeError):
        return None
    return task if isinstance(task, dict) else None


def resolve_task_for_review(repo: Path, task_id: str, base_ref_name: Optional[str] = None) -> dict[str, Any]:
    """Resolve the durable task contract locally or from GitHub-backed refs.

    The dispatcher may have published the task in a Task PR that is not merged
    into the reviewer's current checkout. Fall back to the deterministic Task
    branch, then to the implementation PR base branch, so GitHub remains the
    source of truth instead of requiring hidden local state.
    """
    try:
        return get_task(repo, task_id)
    except RuntimeError:
        pass

    task_branch = f"agent-bridge/{task_id.lower()}"
    task_ref = f"refs/agent-bridge/task-contract-{task_id.lower()}"
    fetch = subprocess.run(
        ["git", "fetch", "origin", f"+refs/heads/{task_branch}:{task_ref}"],
        cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if fetch.returncode == 0:
        task = _task_from_git_ref(repo, task_ref, task_id)
        if task:
            return task

    if base_ref_name:
        base_ref = f"refs/agent-bridge/base-{task_id.lower()}"
        fetch = subprocess.run(
            ["git", "fetch", "origin", f"+refs/heads/{base_ref_name}:{base_ref}"],
            cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if fetch.returncode == 0:
            task = _task_from_git_ref(repo, base_ref, task_id)
            if task:
                return task

    raise RuntimeError(
        f"task {task_id} is not available locally or from GitHub task/base refs; "
        "ensure its Task PR/branch still exists or merge the task metadata first"
    )


def review_to_markdown(task_id: str, head_sha: str, result: ReviewResult) -> str:
    lines = [codex_review_marker(task_id, result.verdict, head_sha), "", f"## Codex local review — `{task_id}`", "", f"**Verdict:** `{result.verdict}`", f"**Reviewed head:** `{head_sha}`", "", result.summary, "", "### Findings"]
    if result.findings:
        for finding in result.findings:
            lines.append(f"- **{finding['severity'].upper()} — {finding['title']}**: {finding['detail']}")
    else:
        lines.append("- None.")
    lines.extend(["", "### Local validation"])
    if result.tests:
        for test in result.tests:
            lines.append(f"- `{test['command']}` → exit `{test['exit_code']}`")
    else:
        lines.append("- No explicit test commands configured.")
    return "\n".join(lines) + "\n"


def post_review_comment(repo: Path, pr_number: int, body: str) -> None:
    marker = parse_codex_review_marker(body)
    if marker:
        existing = subprocess.run(["gh", "pr", "view", str(pr_number), "--json", "comments"], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if existing.returncode == 0:
            try:
                comments = json.loads(existing.stdout).get("comments", [])
                for comment in comments:
                    parsed = parse_codex_review_marker(comment.get("body") or "")
                    if parsed == marker:
                        return
            except json.JSONDecodeError:
                pass
    proc = subprocess.run(["gh", "pr", "comment", str(pr_number), "--body", body], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr comment failed: {proc.stderr.strip()}")


def process_once(
    repo: Path,
    *,
    prs: Optional[list[dict[str, Any]]] = None,
    reviewer: Callable[..., ReviewResult] = review_pr_head,
    poster: Callable[[Path, int, str], None] = post_review_comment,
    record_heartbeat: bool = False,
) -> list[dict[str, Any]]:
    """Review each marked implementation PR head exactly once.

    GitHub PR head SHA is the live implementation truth. We intentionally do not
    mutate/commit `.ai/state/tasks.json` from the watcher because that checkout
    may be on a protected base branch and because ChatGPT fix iterations advance
    the PR head independently. The review comment itself is the event that routes
    control back to ChatGPT Work.
    """
    state = load_watcher_state(repo)
    events: list[dict[str, Any]] = []
    for pr in prs if prs is not None else list_implementation_prs(repo):
        task_id = parse_implementation_marker(pr.get("body") or "")
        if not task_id:
            continue
        if pr.get("isCrossRepository"):
            head_sha = pr["headRefOid"]
            key = str(pr["number"])
            if state["reviewed_heads"].get(key) != head_sha:
                events.append({"task_id": task_id, "pr": int(pr["number"]), "status": "skipped", "reason": "cross-repository PRs are not executed locally"})
                state["reviewed_heads"][key] = head_sha
                save_watcher_state(repo, state)
            continue
        prefix = str(load_config(repo)["automation"].get("implementation_branch_prefix", "ai/"))
        if prefix and not str(pr.get("headRefName") or "").startswith(prefix):
            head_sha = pr["headRefOid"]
            key = str(pr["number"])
            if state["reviewed_heads"].get(key) != head_sha:
                events.append({"task_id": task_id, "pr": int(pr["number"]), "status": "skipped", "reason": f"implementation branch must start with {prefix}"})
                state["reviewed_heads"][key] = head_sha
                save_watcher_state(repo, state)
            continue
        head_sha = pr["headRefOid"]
        key = str(pr["number"])
        if state["reviewed_heads"].get(key) == head_sha:
            continue
        task = resolve_task_for_review(repo, task_id, base_ref_name=pr.get("baseRefName"))
        result = reviewer(repo, task_id=task_id, pr_number=int(pr["number"]), head_sha=head_sha, base_commit=task["base"]["commit"])
        poster(repo, int(pr["number"]), review_to_markdown(task_id, head_sha, result))
        state["reviewed_heads"][key] = head_sha
        save_watcher_state(repo, state)
        events.append({"task_id": task_id, "pr": int(pr["number"]), "head_sha": head_sha, "verdict": result.verdict})
    if record_heartbeat:
        state["last_poll_at"] = now_iso()
        save_watcher_state(repo, state)
    return events


def watch(repo: Path, interval: Optional[int] = None) -> None:
    config = load_config(repo)
    sleep_for = interval or int(config["automation"]["watch_interval_seconds"])
    while True:
        try:
            events = process_once(repo, record_heartbeat=True)
            for event in events:
                print(json.dumps(event, ensure_ascii=False), flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"agent-bridge watcher error: {exc}", flush=True)
        time.sleep(sleep_for)
