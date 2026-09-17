from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .core import get_task

TASK_RE = re.compile(r"<!--\s*agent-bridge:task\s+task=(TASK-\d{6})\s*-->")
IMPL_RE = re.compile(
    r"<!--\s*agent-bridge:implementation\s+"
    r"task=(TASK-\d{6})\s+base=([0-9a-f]{40})\s+head=([0-9a-f]{40})\s*-->"
)
REVIEW_RE = re.compile(
    r"<!--\s*agent-bridge:codex-review\s+"
    r"task=(TASK-\d{6})\s+verdict=(APPROVE|REVISE)\s+head=([0-9a-fA-F]{40})\s*-->"
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def task_marker(task_id: str) -> str:
    return f"<!-- agent-bridge:task task={task_id} -->"


def implementation_marker(task_id: str, base_sha: str, head_sha: str) -> str:
    if not _SHA_RE.fullmatch(base_sha) or not _SHA_RE.fullmatch(head_sha):
        raise RuntimeError("implementation marker requires full 40-character base/head SHAs")
    return (
        f"<!-- agent-bridge:implementation task={task_id} "
        f"base={base_sha} head={head_sha} -->"
    )


def parse_task_marker(body: str) -> Optional[str]:
    match = TASK_RE.search(body or "")
    return match.group(1) if match else None


def parse_implementation_marker(body: str) -> Optional[dict[str, str]]:
    match = IMPL_RE.search(body or "")
    if not match:
        return None
    return {
        "task_id": match.group(1),
        "base_sha": match.group(2),
        "head_sha": match.group(3),
    }


def codex_review_marker(task_id: str, verdict: str, head_sha: str) -> str:
    if verdict not in {"APPROVE", "REVISE"}:
        raise RuntimeError("verdict must be APPROVE or REVISE")
    if not _SHA_RE.fullmatch(head_sha):
        raise RuntimeError("Codex review marker requires a full 40-character head SHA")
    return f"<!-- agent-bridge:codex-review task={task_id} verdict={verdict} head={head_sha} -->"


def parse_codex_review_marker(body: str) -> Optional[dict[str, str]]:
    match = REVIEW_RE.search(body or "")
    if not match:
        return None
    return {
        "task_id": match.group(1),
        "verdict": match.group(2),
        "head_sha": match.group(3),
    }


def build_task_pr_body(repo: Path, task_id: str) -> str:
    task = get_task(repo, task_id)
    return f"""{task_marker(task_id)}
# Agent Bridge Task

**Task:** `{task_id}` — {task['title']}

This PR publishes a commit-pinned task contract. Publishing/opening this PR is durable GitHub
state only; it is never an implementation dispatch event.

- Developer: `{task.get('developer', task.get('assigned_to', 'chatgpt'))}`
- Reviewer: `{task.get('reviewer', 'codex')}`
- Base: `{task['base']['branch']}@{task['base']['commit']}`
- Target branch: `{task.get('target_branch') or 'not configured'}`
- Merge policy: human approval required
"""


def build_implementation_pr_body(
    repo: Path,
    task_id: str,
    head_sha: str,
    summary: str = "",
) -> str:
    task = get_task(repo, task_id)
    marker = implementation_marker(task_id, task["base"]["commit"], head_sha)
    return f"""{marker}
# Agent Bridge Implementation

**Task:** `{task_id}` — {task['title']}

{summary.strip() or 'Implementation produced by the configured active implementation backend.'}

- Pinned base: `{task['base']['branch']}@{task['base']['commit']}`
- Implementation commit: `{head_sha}`
- Target branch: `{task.get('target_branch')}`
- Reviewer: `codex`
- Merge policy: human approval required

The bridge must independently verify the remote branch, this marker, and the exact PR head SHA.
Model output alone is not implementation-completion evidence.
"""
