from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .core import get_task

TASK_RE = re.compile(r"<!--\s*agent-bridge:task\s+task=(TASK-\d{6})\s*-->")
IMPL_RE = re.compile(r"<!--\s*agent-bridge:implementation\s+task=(TASK-\d{6})\s*-->")
REVIEW_RE = re.compile(r"<!--\s*agent-bridge:codex-review\s+task=(TASK-\d{6})\s+verdict=(APPROVE|REVISE)\s+head=([0-9a-fA-F]{7,40})\s*-->")


def task_marker(task_id: str) -> str:
    return f"<!-- agent-bridge:task task={task_id} -->"


def implementation_marker(task_id: str) -> str:
    return f"<!-- agent-bridge:implementation task={task_id} -->"


def parse_task_marker(body: str) -> Optional[str]:
    match = TASK_RE.search(body or "")
    return match.group(1) if match else None


def parse_implementation_marker(body: str) -> Optional[str]:
    match = IMPL_RE.search(body or "")
    return match.group(1) if match else None


def codex_review_marker(task_id: str, verdict: str, head_sha: str) -> str:
    if verdict not in {"APPROVE", "REVISE"}:
        raise RuntimeError("verdict must be APPROVE or REVISE")
    return f"<!-- agent-bridge:codex-review task={task_id} verdict={verdict} head={head_sha} -->"


def parse_codex_review_marker(body: str) -> Optional[dict[str, str]]:
    match = REVIEW_RE.search(body or "")
    if not match:
        return None
    return {"task_id": match.group(1), "verdict": match.group(2), "head_sha": match.group(3)}


def build_task_pr_body(repo: Path, task_id: str) -> str:
    task = get_task(repo, task_id)
    return f"""{task_marker(task_id)}
# Agent Bridge Task

**Task:** `{task_id}` — {task['title']}

This PR publishes the commit-pinned task contract. `github-agent-bridge` actively dispatches the task after publication; opening, updating, or marking this PR ready does not trigger implementation.

- Developer: `{task.get('developer', task.get('assigned_to', 'chatgpt'))}`
- Reviewer: `{task.get('reviewer', 'codex')}`
- Base: `{task['base']['branch']}@{task['base']['commit']}`
- Target branch: `{task['target_branch']}`
- Merge policy: human approval required
"""


def build_implementation_pr_body(repo: Path, task_id: str, summary: str = "") -> str:
    task = get_task(repo, task_id)
    implementation = task.get("implementation") or {}
    return f"""{implementation_marker(task_id)}
# Agent Bridge Implementation

**Task:** `{task_id}` — {task['title']}

{summary.strip() or 'Implementation produced by the actively dispatched implementation agent after tests and self-review.'}

- Implementation commit: `{implementation.get('commit') or 'HEAD'}`
- Reviewer: `{task.get('reviewer', 'codex')}`
- Merge policy: human approval required

The local Codex watcher reviews each new PR head SHA exactly once and posts a machine-marked APPROVE or REVISE result. A REVISE result is actively re-dispatched by the bridge; GitHub comments are evidence, not dispatch triggers.
"""
