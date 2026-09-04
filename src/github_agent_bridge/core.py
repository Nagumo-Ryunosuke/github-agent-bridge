from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .git import changed_files_between, current_branch, head_sha, resolve_ref

SCHEMA_VERSION = 1
STATE_PATH = Path(".ai/state/tasks.json")
TASKS_DIR = Path(".ai/tasks")
HANDOFFS_DIR = Path(".ai/handoffs")
REVIEWS_DIR = Path(".ai/reviews")
DECISIONS_DIR = Path(".ai/decisions")
CONTEXT_DIR = Path(".ai/context")

VALID_STATUSES = {
    "draft",
    "ready",
    "claimed",
    "in_progress",
    "blocked",
    "review_required",
    "reviewing",
    "changes_requested",
    "approved",
    "done",
    "stale",
}

ALLOWED_TRANSITIONS = {
    "draft": {"ready"},
    "ready": {"claimed", "stale"},
    "claimed": {"in_progress", "blocked", "stale"},
    "in_progress": {"blocked", "review_required", "stale"},
    "blocked": {"in_progress", "stale"},
    "review_required": {"reviewing", "stale"},
    "reviewing": {"changes_requested", "approved", "stale"},
    "changes_requested": {"in_progress", "stale"},
    "approved": {"done"},
    "done": set(),
    "stale": {"ready"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def init_repo(repo: Path) -> list[Path]:
    created: list[Path] = []
    dirs = [TASKS_DIR, HANDOFFS_DIR, REVIEWS_DIR, DECISIONS_DIR, CONTEXT_DIR, STATE_PATH.parent]
    for rel in dirs:
        (repo / rel).mkdir(parents=True, exist_ok=True)

    state_file = repo / STATE_PATH
    if not state_file.exists():
        _write_json(state_file, {"schema_version": SCHEMA_VERSION, "tasks": {}})
        created.append(state_file)

    default_files = {
        Path(".ai/README.md"): """# AI Collaboration State\n\nThis directory is the repository-local coordination layer for AI agents.\n\n- `context/`: durable project context and constraints\n- `tasks/`: task contracts pinned to a base commit\n- `handoffs/`: implementation/blocker reports\n- `reviews/`: commit-pinned review results\n- `decisions/`: durable architecture decisions\n- `state/tasks.json`: machine-readable workflow state\n\nGit history and exact commit SHAs are authoritative. Chat history is not.\n""",
        Path(".ai/context/project.md"): "# Project Context\n\nDescribe the repository purpose, major components, and common commands.\n",
        Path(".ai/context/architecture.md"): "# Architecture\n\nRecord durable architecture context here.\n",
        Path(".ai/context/constraints.md"): "# Constraints\n\nRecord compatibility, security, testing, and delivery constraints here.\n",
    }
    for rel, content in default_files.items():
        path = repo / rel
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(path)
    return created


def load_state(repo: Path) -> dict[str, Any]:
    path = repo / STATE_PATH
    if not path.exists():
        raise RuntimeError("handoff state is not initialized; run `agent-bridge init`")
    state = _read_json(path)
    if state.get("schema_version") != SCHEMA_VERSION or not isinstance(state.get("tasks"), dict):
        raise RuntimeError("unsupported or invalid .ai/state/tasks.json")
    return state


def save_state(repo: Path, state: dict[str, Any]) -> None:
    _write_json(repo / STATE_PATH, state)


def next_task_id(state: dict[str, Any]) -> str:
    max_id = 0
    for key in state["tasks"]:
        m = re.fullmatch(r"TASK-(\d{6})", key)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return f"TASK-{max_id + 1:06d}"


def transition(task: dict[str, Any], new_status: str) -> None:
    old_status = task["status"]
    if new_status not in VALID_STATUSES:
        raise RuntimeError(f"unknown status: {new_status}")
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
        raise RuntimeError(f"invalid transition: {old_status} -> {new_status}")
    task["status"] = new_status
    task["updated_at"] = now_iso()


def create_task(
    repo: Path,
    *,
    title: str,
    objective: str,
    assigned_to: str,
    created_by: str,
    priority: str,
    base_branch: str | None,
    target_branch: str | None,
) -> str:
    state = load_state(repo)
    task_id = next_task_id(state)
    branch = base_branch or current_branch(repo)
    base_commit = resolve_ref(repo, branch) if branch != "DETACHED" else head_sha(repo)
    created_at = now_iso()
    task = {
        "task_id": task_id,
        "title": title,
        "status": "ready",
        "priority": priority,
        "assigned_to": assigned_to,
        "requested_by": created_by,
        "base": {"branch": branch, "commit": base_commit},
        "target_branch": target_branch,
        "next_agent": assigned_to,
        "created_at": created_at,
        "updated_at": created_at,
        "implementation": None,
        "review": None,
    }
    state["tasks"][task_id] = task
    save_state(repo, state)

    task_path = repo / TASKS_DIR / f"{task_id}.md"
    target = target_branch or "TBD"
    task_path.write_text(
        f"""---\nschema_version: {SCHEMA_VERSION}\ntask_id: {task_id}\ntitle: {title}\ncreated_by: {created_by}\ncreated_at: {created_at}\nassigned_to: {assigned_to}\nstatus: ready\npriority: {priority}\nbase_branch: {branch}\nbase_commit: {base_commit}\ntarget_branch: {target}\n---\n\n# Objective\n\n{objective.strip()}\n\n# Requirements\n\n- Define concrete requirements before implementation when they are not already explicit.\n\n# Constraints\n\n- Respect `.ai/context/constraints.md` and repository-local instructions.\n- Do not commit secrets or credentials.\n\n# Acceptance Criteria\n\n- Relevant tests pass.\n- Implementation is traceable to an exact commit.\n- A handoff report is produced before review.\n\n# Deliverables\n\n- implementation\n- tests/validation evidence\n- handoff report\n- PR or exact implementation commit\n""",
        encoding="utf-8",
    )
    return task_id


def get_task(repo: Path, task_id: str) -> dict[str, Any]:
    state = load_state(repo)
    try:
        return state["tasks"][task_id]
    except KeyError as exc:
        raise RuntimeError(f"task not found: {task_id}") from exc


def claim_task(repo: Path, task_id: str, agent: str) -> None:
    state = load_state(repo)
    task = state["tasks"].get(task_id)
    if not task:
        raise RuntimeError(f"task not found: {task_id}")
    transition(task, "claimed")
    task["assigned_to"] = agent
    task["next_agent"] = agent
    save_state(repo, state)


def start_task(repo: Path, task_id: str) -> None:
    state = load_state(repo)
    task = state["tasks"].get(task_id)
    if not task:
        raise RuntimeError(f"task not found: {task_id}")
    transition(task, "in_progress")
    save_state(repo, state)


def drift_report(repo: Path, task_id: str) -> dict[str, Any]:
    task = get_task(repo, task_id)
    base_branch = task["base"]["branch"]
    expected = task["base"]["commit"]
    try:
        current = resolve_ref(repo, base_branch)
    except Exception:
        current = expected
    changed = [] if current == expected else changed_files_between(repo, expected, current)
    return {
        "task_id": task_id,
        "base_branch": base_branch,
        "expected_commit": expected,
        "current_commit": current,
        "drift": current != expected,
        "changed_files": changed,
    }


def finish_task(
    repo: Path,
    task_id: str,
    *,
    implementation_commit: str,
    branch: str,
    pr: int | None,
    summary: str,
    agent: str,
) -> Path:
    state = load_state(repo)
    task = state["tasks"].get(task_id)
    if not task:
        raise RuntimeError(f"task not found: {task_id}")
    if task["status"] in {"claimed", "changes_requested", "blocked"}:
        transition(task, "in_progress")
    transition(task, "review_required")
    task["implementation"] = {"branch": branch, "commit": implementation_commit, "pr": pr}
    task["next_agent"] = "chatgpt"
    save_state(repo, state)

    path = repo / HANDOFFS_DIR / f"{task_id}-{agent}.md"
    path.write_text(
        f"""---\nschema_version: {SCHEMA_VERSION}\ntask_id: {task_id}\nagent: {agent}\nstatus: implementation_completed\nbase_commit: {task['base']['commit']}\nimplementation_commit: {implementation_commit}\nbranch: {branch}\npr: {pr if pr is not None else 'null'}\ncreated_at: {now_iso()}\n---\n\n# Summary\n\n{summary.strip()}\n\n# Validation\n\nRecord commands executed and their results here.\n\n# Changed Files\n\nReference the commit/PR diff; list only high-signal files when useful.\n\n# Remaining Risks\n\nNone recorded.\n\n# Questions For Reviewer\n\nNone recorded.\n""",
        encoding="utf-8",
    )
    return path


def begin_review(repo: Path, task_id: str) -> None:
    state = load_state(repo)
    task = state["tasks"].get(task_id)
    if not task:
        raise RuntimeError(f"task not found: {task_id}")
    transition(task, "reviewing")
    task["next_agent"] = "chatgpt"
    save_state(repo, state)


def review_task(
    repo: Path,
    task_id: str,
    *,
    result: str,
    reviewed_commit: str,
    summary: str,
    reviewer: str,
) -> Path:
    state = load_state(repo)
    task = state["tasks"].get(task_id)
    if not task:
        raise RuntimeError(f"task not found: {task_id}")
    if task["status"] == "review_required":
        transition(task, "reviewing")
    if task["status"] != "reviewing":
        raise RuntimeError(f"task must be review_required/reviewing, got {task['status']}")
    expected = (task.get("implementation") or {}).get("commit")
    if expected and reviewed_commit != expected:
        raise RuntimeError(f"review commit mismatch: expected {expected}, got {reviewed_commit}")

    if result == "approve":
        transition(task, "approved")
        next_agent = "human"
    elif result == "request-changes":
        transition(task, "changes_requested")
        next_agent = task.get("assigned_to") or "codex"
    else:
        raise RuntimeError("review result must be approve or request-changes")

    task["review"] = {
        "result": result,
        "reviewed_commit": reviewed_commit,
        "reviewer": reviewer,
        "reviewed_at": now_iso(),
    }
    task["next_agent"] = next_agent
    save_state(repo, state)

    path = repo / REVIEWS_DIR / f"{task_id}-review.md"
    path.write_text(
        f"""---\nschema_version: {SCHEMA_VERSION}\ntask_id: {task_id}\nreviewer: {reviewer}\nresult: {result}\nreviewed_commit: {reviewed_commit}\nreviewed_at: {now_iso()}\n---\n\n# Review Result\n\n{summary.strip()}\n\n# Critical\n\nNone recorded.\n\n# Major\n\nNone recorded.\n\n# Minor\n\nNone recorded.\n\n# Required Changes\n\n{'None.' if result == 'approve' else 'See review result above.'}\n""",
        encoding="utf-8",
    )
    return path


def complete_task(repo: Path, task_id: str) -> None:
    state = load_state(repo)
    task = state["tasks"].get(task_id)
    if not task:
        raise RuntimeError(f"task not found: {task_id}")
    transition(task, "done")
    task["next_agent"] = None
    save_state(repo, state)


def validate_state(repo: Path) -> list[str]:
    errors: list[str] = []
    state = load_state(repo)
    seen = set()
    for task_id, task in state["tasks"].items():
        if task_id in seen:
            errors.append(f"duplicate task id: {task_id}")
        seen.add(task_id)
        if task.get("task_id") != task_id:
            errors.append(f"task id mismatch: key={task_id} value={task.get('task_id')}")
        if task.get("status") not in VALID_STATUSES:
            errors.append(f"{task_id}: invalid status {task.get('status')}")
        base = task.get("base") or {}
        if not base.get("commit") or not base.get("branch"):
            errors.append(f"{task_id}: missing base branch/commit")
        task_file = repo / TASKS_DIR / f"{task_id}.md"
        if not task_file.exists():
            errors.append(f"{task_id}: missing task file {task_file.relative_to(repo)}")
    return errors
