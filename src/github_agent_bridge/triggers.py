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

This PR publishes a commit-pinned task for ChatGPT development. An event-triggered ChatGPT Work task should read the task contract and begin implementation after this PR is opened/updated according to the configured trigger.

- Developer: `{task.get('developer', task.get('assigned_to', 'chatgpt'))}`
- Reviewer: `{task.get('reviewer', 'codex')}`
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
- Reviewer: `{task.get('reviewer', 'codex')}`
- Merge policy: human approval required

Codex watcher should review each new PR head SHA exactly once, run configured local tests, and post structured findings back to GitHub.
"""


def build_chatgpt_work_prompt(repo: Path, task_id: str, *, phase: str = "implement") -> str:
    task = get_task(repo, task_id)
    config = load_config(repo)
    writer = detect_writer(repo)
    if phase not in {"implement", "fix"}:
        raise RuntimeError("phase must be implement or fix")

    action = (
        "Design the solution, implement it, write tests, perform a first self-review, and publish an implementation PR."
        if phase == "implement"
        else "Read the latest Codex review, fix every justified finding, update tests, self-review again, and push a new commit to the existing implementation PR."
    )
    writer_note = (
        f"Writer mode `{writer['mode']}` is configured as write-ready. Use the connected writer for branch/file/PR writes. Unattended writes are {'confirmed' if writer['unattended_ready'] else 'not confirmed; the platform may still request approval'}."
        if writer["ready"]
        else f"Writer mode `{writer['mode']}` is not write-ready. Do not pretend to push; produce a patch/artifact and report the missing writer capability."
    )

    return f"""You are the primary developer in github-agent-bridge.

Task: {task_id} — {task['title']}
Pinned base: {task['base']['branch']}@{task['base']['commit']}
Development phase: {phase}

{action}

Required procedure:
1. Read `.ai/tasks/{task_id}.md`, `.ai/context/*`, repository instructions, and current GitHub PR/review state.
2. Verify the task is still valid against the pinned base commit. If code drift materially changes the task, stop and report the drift rather than guessing.
3. Do the architecture/design work before editing code.
4. Implement on the task-specific branch from the exact pinned base commit; never push directly to the protected/base branch.
5. Add or update tests appropriate to the change. You may reason about tests, but Codex will perform authoritative local execution later.
6. Self-review the exact diff once before handing off; fix obvious correctness, security, concurrency, compatibility, and maintainability issues.
7. Publish/update an implementation PR containing `{implementation_marker(task_id)}`. Never merge it yourself.
8. Record the exact implementation commit in the bridge task/handoff state when the writer allows it.

{writer_note}

Role policy: dispatcher={config['workflow']['dispatcher']}, developer={config['workflow']['developer']}, reviewer={config['workflow']['reviewer']}.
"""


def build_work_automation_setup(repo: Path) -> str:
    config = load_config(repo)
    repositories = ", ".join(config["github"].get("repositories") or []) or "the connected repository"
    return f"""ONE-TIME CHATGPT WORK SETUP

Create these event-triggered tasks in ChatGPT Work on Web, iOS, or Android. The desktop app can display existing tasks but currently cannot create/edit their trigger conditions.

Authorized repository scope: {repositories}

1. IMPLEMENT TASK
Trigger: GitHub pull request opened or marked ready for review.
Condition: PR body contains `agent-bridge:task`.
Prompt: Identify the TASK id from the PR body, read `.ai/tasks/<TASK>.md` and repository context, then follow the `agent-bridge trigger work-prompt <TASK> --phase implement` policy. Use the configured GitHub writer. Never merge the implementation PR.

2. FIX AFTER CODEX REVIEW
Trigger: new GitHub pull request comment.
Condition: comment contains `agent-bridge:codex-review` and `verdict=REVISE`.
Prompt: Identify the TASK id and reviewed head from the machine marker, read the latest Codex findings and current implementation PR, then follow the fix policy. Address justified findings, self-review, and push a new commit. Never merge.

After both tasks are saved and authorized, run:

    agent-bridge setup work-trigger --confirm
    agent-bridge watch

Keep the watcher running under a persistent user service/supervisor. Then, from another shell after a heartbeat is recorded:

    agent-bridge doctor

Configured writer mode: {config['github']['mode']}.
"""
