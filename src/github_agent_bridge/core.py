from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .git import changed_files_between, current_branch, head_sha, resolve_ref

SCHEMA_VERSION = 1
STATE_PATH = Path(".ai/state/tasks.json")
TASKS_DIR = Path(".ai/tasks")
HANDOFFS_DIR = Path(".ai/handoffs")
REVIEWS_DIR = Path(".ai/reviews")
DECISIONS_DIR = Path(".ai/decisions")
CONTEXT_DIR = Path(".ai/context")

VALID_STATUSES = {"draft", "ready", "claimed", "in_progress", "blocked", "review_required", "reviewing", "changes_requested", "approved", "done", "stale"}
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
    from .config import DEFAULT_CONFIG, CONFIG_PATH, save_config

    created: list[Path] = []
    dirs = [TASKS_DIR, HANDOFFS_DIR, REVIEWS_DIR, DECISIONS_DIR, CONTEXT_DIR, STATE_PATH.parent]
    for rel in dirs:
        (repo / rel).mkdir(parents=True, exist_ok=True)
    state_file = repo / STATE_PATH
    if not state_file.exists():
        _write_json(state_file, {"schema_version": SCHEMA_VERSION, "tasks": {}})
        created.append(state_file)
    config_file = repo / CONFIG_PATH
    if not config_file.exists():
        save_config(repo, DEFAULT_CONFIG)
        created.append(config_file)
    default_files = {
        Path(".ai/README.md"): """# AI Collaboration State\n\nGitHub is the durable transport and source of truth. ChatGPT is the primary planner/developer; Codex is the local reviewer and test executor.\n\n- `context/`: durable project context\n- `tasks/`: commit-pinned task contracts\n- `handoffs/`: implementation reports\n- `reviews/`: commit-pinned review results\n- `state/`: machine-readable workflow state\n- `config.json`: role, writer, trigger, and local-review configuration\n""",
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


def create_task(repo: Path, *, title: str, objective: str, assigned_to: str, created_by: str, priority: str, base_branch: Optional[str], target_branch: Optional[str], reviewer: Optional[str] = None) -> str:
    from .config import load_config

    state = load_state(repo)
    config = load_config(repo)
    task_id = next_task_id(state)
    branch = base_branch or current_branch(repo)
    base_commit = resolve_ref(repo, branch) if branch != "DETACHED" else head_sha(repo)
    created_at = now_iso()
    developer = assigned_to or config["workflow"]["developer"]
    reviewer = reviewer or config["workflow"]["reviewer"]
    task = {
        "task_id": task_id,
        "title": title,
        "status": "ready",
        "priority": priority,
        "assigned_to": developer,
        "developer": developer,
        "reviewer": reviewer,
        "requested_by": created_by,
        "base": {"branch": branch, "commit": base_commit},
        "target_branch": target_branch or f"ai/{task_id.lower()}",
        "next_agent": developer,
        "created_at": created_at,
        "updated_at": created_at,
        "implementation": None,
        "review": None,
        "self_reviewed": False,
    }
    state["tasks"][task_id] = task
    save_state(repo, state)
    target = target_branch or f"ai/{task_id.lower()}"
    (repo / TASKS_DIR / f"{task_id}.md").write_text(
        f"""---\nschema_version: {SCHEMA_VERSION}\ntask_id: {task_id}\ntitle: {title}\ncreated_by: {created_by}\ncreated_at: {created_at}\ndeveloper: {developer}\nreviewer: {reviewer}\nstatus: ready\npriority: {priority}\nbase_branch: {branch}\nbase_commit: {base_commit}\ntarget_branch: {target}\n---\n\n# Objective\n\n{objective.strip()}\n\n# Development Policy\n\n- ChatGPT performs architecture/design, implementation, tests, and first self-review.\n- Codex performs the second review and authoritative local test/debug pass.\n- Neither agent merges the implementation PR automatically.\n\n# Constraints\n\n- Respect `.ai/context/constraints.md` and repository instructions.\n- Do not commit secrets or credentials.\n\n# Acceptance Criteria\n\n- Implementation is traceable to an exact commit and PR.\n- ChatGPT self-review completed before Codex handoff.\n- Codex local validation passes or findings are routed back to ChatGPT.\n""",
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
    state = load_state(repo); task = state["tasks"].get(task_id)
    if not task: raise RuntimeError(f"task not found: {task_id}")
    transition(task, "claimed"); task["assigned_to"] = agent; task["developer"] = agent; task["next_agent"] = agent; save_state(repo, state)


def start_task(repo: Path, task_id: str) -> None:
    state = load_state(repo); task = state["tasks"].get(task_id)
    if not task: raise RuntimeError(f"task not found: {task_id}")
    if task["status"] in {"changes_requested", "blocked"}: transition(task, "in_progress")
    else: transition(task, "in_progress")
    save_state(repo, state)


def mark_self_reviewed(repo: Path, task_id: str, *, agent: str = "chatgpt") -> None:
    state = load_state(repo); task = state["tasks"].get(task_id)
    if not task: raise RuntimeError(f"task not found: {task_id}")
    if task["status"] not in {"in_progress", "changes_requested"}:
        raise RuntimeError(f"self-review requires in_progress/changes_requested, got {task['status']}")
    task["self_reviewed"] = True
    task["self_reviewed_by"] = agent
    task["self_reviewed_at"] = now_iso()
    task["updated_at"] = now_iso()
    save_state(repo, state)


def drift_report(repo: Path, task_id: str) -> dict[str, Any]:
    task = get_task(repo, task_id); base_branch = task["base"]["branch"]; expected = task["base"]["commit"]
    try: current = resolve_ref(repo, base_branch)
    except Exception: current = expected
    changed = [] if current == expected else changed_files_between(repo, expected, current)
    metadata_only = bool(changed) and all(path.startswith(".ai/") for path in changed)
    return {"task_id": task_id, "base_branch": base_branch, "expected_commit": expected, "current_commit": current, "drift": current != expected, "metadata_only": metadata_only, "changed_files": changed}


def finish_task(repo: Path, task_id: str, *, implementation_commit: str, branch: str, pr: Optional[int], summary: str, agent: str) -> Path:
    state = load_state(repo); task = state["tasks"].get(task_id)
    if not task: raise RuntimeError(f"task not found: {task_id}")
    if task["status"] in {"claimed", "changes_requested", "blocked"}: transition(task, "in_progress")
    if agent == "chatgpt" and not task.get("self_reviewed"):
        raise RuntimeError("ChatGPT implementation cannot be handed to Codex before first self-review")
    transition(task, "review_required")
    task["implementation"] = {"branch": branch, "commit": implementation_commit, "pr": pr, "agent": agent}
    task["next_agent"] = task.get("reviewer") or "codex"
    save_state(repo, state)
    path = repo / HANDOFFS_DIR / f"{task_id}-{agent}.md"
    path.write_text(f"""---\nschema_version: {SCHEMA_VERSION}\ntask_id: {task_id}\nagent: {agent}\nstatus: implementation_completed\nbase_commit: {task['base']['commit']}\nimplementation_commit: {implementation_commit}\nbranch: {branch}\npr: {pr if pr is not None else 'null'}\ncreated_at: {now_iso()}\n---\n\n# Summary\n\n{summary.strip()}\n\n# Self Review\n\n{'Completed.' if task.get('self_reviewed') else 'Not recorded.'}\n\n# Validation\n\nChatGPT may reason about tests; Codex local validation is authoritative.\n""", encoding="utf-8")
    return path


def review_task(repo: Path, task_id: str, *, result: str, reviewed_commit: str, summary: str, reviewer: str) -> Path:
    state = load_state(repo); task = state["tasks"].get(task_id)
    if not task: raise RuntimeError(f"task not found: {task_id}")
    if task["status"] == "review_required": transition(task, "reviewing")
    if task["status"] != "reviewing": raise RuntimeError(f"task must be review_required/reviewing, got {task['status']}")
    expected = (task.get("implementation") or {}).get("commit")
    if expected and reviewed_commit != expected: raise RuntimeError(f"review commit mismatch: expected {expected}, got {reviewed_commit}")
    if result == "approve": transition(task, "approved"); next_agent = "human"
    elif result == "request-changes": transition(task, "changes_requested"); next_agent = task.get("developer") or task.get("assigned_to") or "chatgpt"; task["self_reviewed"] = False
    else: raise RuntimeError("review result must be approve or request-changes")
    task["review"] = {"result": result, "reviewed_commit": reviewed_commit, "reviewer": reviewer, "reviewed_at": now_iso()}
    task["next_agent"] = next_agent; save_state(repo, state)
    path = repo / REVIEWS_DIR / f"{task_id}-review.md"
    path.write_text(f"""---\nschema_version: {SCHEMA_VERSION}\ntask_id: {task_id}\nreviewer: {reviewer}\nresult: {result}\nreviewed_commit: {reviewed_commit}\nreviewed_at: {now_iso()}\n---\n\n# Review Result\n\n{summary.strip()}\n\n# Required Changes\n\n{'None.' if result == 'approve' else 'ChatGPT must address the findings and push a new implementation commit for automatic re-review.'}\n""", encoding="utf-8")
    return path


def complete_task(repo: Path, task_id: str) -> None:
    state = load_state(repo); task = state["tasks"].get(task_id)
    if not task: raise RuntimeError(f"task not found: {task_id}")
    transition(task, "done"); task["next_agent"] = None; save_state(repo, state)


def validate_state(repo: Path) -> list[str]:
    errors: list[str] = []; state = load_state(repo)
    for task_id, task in state["tasks"].items():
        if task.get("task_id") != task_id: errors.append(f"task id mismatch: key={task_id} value={task.get('task_id')}")
        if task.get("status") not in VALID_STATUSES: errors.append(f"{task_id}: invalid status {task.get('status')}")
        base = task.get("base") or {}
        if not base.get("commit") or not base.get("branch"): errors.append(f"{task_id}: missing base branch/commit")
        if not task.get("developer") or not task.get("reviewer"): errors.append(f"{task_id}: missing developer/reviewer role")
        if not (repo / TASKS_DIR / f"{task_id}.md").exists(): errors.append(f"{task_id}: missing task file")
    return errors
