from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .config import load_config
from .core import get_task
from .writers import detect_writer

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

This PR publishes a commit-pinned task for ChatGPT development. The active Codex dispatcher relays this contract to an ordinary browser Chat. Publishing this PR alone does not deliver it to Chat. Never create a Work task.

- Developer: `{task.get('developer', task.get('assigned_to', 'chatgpt'))}`
- Reviewer: `{task.get('reviewer', 'chatgpt')}`
- Base: `{task['base']['branch']}@{task['base']['commit']}`
- Target branch: `{task.get('target_branch') or 'to be created by ChatGPT'}`
"""


def build_implementation_pr_body(repo: Path, task_id: str, summary: str = "") -> str:
    task = get_task(repo, task_id)
    implementation = task.get("implementation") or {}
    return f"""{implementation_marker(task_id)}
# Agent Bridge Implementation

**Task:** `{task_id}` — {task['title']}

{summary.strip() or 'Implementation produced by ChatGPT after planning and self-review.'}

- Implementation commit: `{implementation.get('commit') or 'HEAD'}`
- Reviewer: `{task.get('reviewer', 'chatgpt')}`
- Merge policy: human approval required

Send the exact new PR head SHA and test evidence to the assigned reviewer in ordinary Chat. Human approval is required for merge.
"""


def build_chatgpt_chat_prompt(repo: Path, task_id: str, *, phase: str = "implement") -> str:
    task = get_task(repo, task_id)
    config = load_config(repo)
    writer = detect_writer(repo)
    if phase not in {"design", "implement", "review", "fix"}:
        raise RuntimeError("phase must be design, implement, review, or fix")

    action = {
        "design": "Ask any remaining questions and design a concrete solution in this Chat. Return the design and implementation steps; do not delegate to Work.",
        "implement": "Use the agreed Chat design, implement it, write tests, self-review, and publish an implementation PR or return a patch if no writer is available.",
        "review": "Review the exact supplied PR head against the pinned base in this Chat. Return APPROVE or REVISE, findings with file/line evidence, and actual test evidence or explicit untested limitations. Do not edit during review.",
        "fix": "Read the latest Chat review, fix justified findings, update tests, self-review, and return the updated implementation and exact new head for another Chat review.",
    }[phase]
    writer_note = (
        f"Writer mode `{writer['mode']}` is configured as write-ready. Use the connected writer for branch/file/PR writes. Unattended writes are {'confirmed' if writer['unattended_ready'] else 'not confirmed; the platform may still request approval'}."
        if writer["ready"]
        else f"Writer mode `{writer['mode']}` is not write-ready. Do not pretend to push; produce a patch/artifact and report the missing writer capability."
    )

    return f"""You are the planner, developer and reviewer in ordinary ChatGPT Web Chat for github-agent-bridge.
Never invoke, create or delegate to Work or a Codex model task. If this is not ordinary Chat, stop.

Task: {task_id} — {task['title']}
Pinned base: {task['base']['branch']}@{task['base']['commit']}
Development phase: {phase}

{action}

Implementation procedure (only implement/fix may edit or publish; design/review return their requested artifacts):
1. Read `.ai/tasks/{task_id}.md`, `.ai/context/*`, repository instructions, and current GitHub PR/review state.
2. Verify the task is still valid against the pinned base commit. If code drift materially changes the task, stop and report the drift rather than guessing.
3. Do the architecture/design work before editing code.
4. Implement on the task-specific branch from the exact pinned base commit; never push directly to the protected/base branch.
5. Add or update tests appropriate to the change. Report actual execution separately from reasoning. If ordinary Chat cannot execute tests, report that gap; the dispatcher only executes commands with user authorization.
6. Self-review the exact diff once before handing off; fix obvious correctness, security, concurrency, compatibility, and maintainability issues.
7. Publish/update an implementation PR containing `{implementation_marker(task_id)}`. Never merge it yourself.
8. Record the exact implementation commit in the bridge task/handoff state when the writer allows it.

{writer_note}

Role policy: dispatcher={config['workflow']['dispatcher']}, developer={config['workflow']['developer']}, reviewer={config['workflow']['reviewer']}.
"""


def build_chatgpt_work_prompt(repo: Path, task_id: str, *, phase: str = "implement") -> str:
    raise RuntimeError("Work dispatch is disabled; use `agent-bridge chat prepare <TASK> --phase " + phase + "`")


def build_work_automation_setup(repo: Path) -> str:
    return """ORDINARY CHAT DISPATCH
Use `agent-bridge chat prepare <TASK> --phase design`.
Use the connected logged-in browser to create/select ordinary Chat and relay the packet.
Verify Chat mode, selected model and the assistant acknowledgment before recording delivery.
Do not use create_thread(target=chatgptWorkCloud), Work triggers, schedules or polling as a substitute.
A Task PR or prepared prompt is not delivery. No supported ordinary-Chat creation API is bundled.
See references/browser-chat.md for the browser transport and setup chat binding.
"""
