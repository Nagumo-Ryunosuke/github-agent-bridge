from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .config import load_config
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

This PR publishes a commit-pinned task for ChatGPT development. An event-triggered ChatGPT Work broker may detect the task and prepare a compact handoff, but architecture, implementation, test design, and self-review belong in a normal ChatGPT Web Chat.

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
    if phase not in {"implement", "fix"}:
        raise RuntimeError("phase must be implement or fix")

    handoff_goal = (
        "Prepare a compact implementation handoff for the normal ChatGPT Web Chat."
        if phase == "implement"
        else "Prepare a compact revision handoff containing the latest Codex findings for the normal ChatGPT Web Chat."
    )

    return f"""You are a bounded ChatGPT Work event broker for github-agent-bridge, not the primary developer.

Task: {task_id} — {task['title']}
Pinned base: {task['base']['branch']}@{task['base']['commit']}
Event phase: {phase}

{handoff_goal}

Non-negotiable resource-control policy:
1. Do not design the architecture or solve the implementation in Work.
2. Do not edit repository files, create commits, push branches, create/update an implementation PR, or invoke a configured writer.
3. Do not run broad repository analysis or tests. Read only enough task/PR metadata to identify the handoff accurately.
4. Do not create, invoke, or delegate to another Work task.
5. Do not escalate the configured model or reasoning level merely because a stronger/newer model is available.
6. Any future ad-hoc Chat-to-Work delegation requires explicit user approval first. Before that approval, Chat must explain the capability gap, the bounded operation, and the intended model/reasoning level. If model selection is unavailable, Chat must say that the platform default would be used and ask whether to proceed.

Required broker procedure:
1. Read the task marker, `.ai/tasks/{task_id}.md`, the pinned base identity, and only the current PR/review metadata needed for this event.
2. If this is a revision event, include the reviewed head SHA and the justified Codex findings that Chat must consider.
3. Produce a concise handoff containing: task ID, title, pinned base, relevant PR/head, phase, required next action, and any blocking drift/capability issue.
4. Tell the user to continue the design and implementation in a normal ChatGPT Web Chat using `$github-agent-bridge` and this task ID.
5. Stop. Do not perform implementation work in this Work run.

Role policy: dispatcher={config['workflow']['dispatcher']}, developer={config['workflow']['developer']}, reviewer={config['workflow']['reviewer']}. ChatGPT Web Chat owns development decisions; Work is only the bounded event broker described above.
"""


def build_work_automation_setup(repo: Path) -> str:
    config = load_config(repo)
    repositories = ", ".join(config["github"].get("repositories") or []) or "the connected repository"
    return f"""ONE-TIME CHATGPT WORK BROKER SETUP

These optional GitHub event-triggered Work tasks are brokers only. They must never become the primary planner/developer or perform implementation work.

Authorized repository scope: {repositories}

RESOURCE / MODEL GATE — BEFORE SAVING EITHER TRIGGER:
- Show the user the intended Work model and reasoning level and obtain explicit approval.
- Prefer the least costly model/reasoning level that can reliably parse the GitHub event and prepare the handoff; never choose the newest or strongest model by default.
- If the platform does not expose model selection for the trigger, state clearly that the platform default Work model will be used and ask the user whether to continue.
- Saving the trigger authorizes only this bounded event-ingress role. It does not authorize Chat to invoke Work later for implementation.

1. IMPLEMENTATION HANDOFF BROKER
Trigger: GitHub pull request opened or marked ready for review.
Condition: PR body contains `agent-bridge:task`.
Prompt: Identify the TASK id, pinned base and Task PR. Read only the minimum task/PR metadata needed to prepare a compact handoff for a normal ChatGPT Web Chat. Do not design, edit code, run tests, use the writer, or create an implementation PR. Tell the user to continue in Chat with `$github-agent-bridge` and the TASK id.

2. REVISION HANDOFF BROKER
Trigger: new GitHub pull request comment.
Condition: comment contains `agent-bridge:codex-review` and `verdict=REVISE`.
Prompt: Identify the TASK id, reviewed head and Codex findings. Prepare a compact revision handoff for the normal ChatGPT Web Chat. Do not fix code, run tests, use the writer, or push a new head. Tell the user to continue in Chat with `$github-agent-bridge` and the TASK id.

For both triggers, the detailed broker policy is rendered by:

    agent-bridge trigger work-prompt <TASK> --phase implement
    agent-bridge trigger work-prompt <TASK> --phase fix

After both broker tasks are saved, model-approved, and authorized, run:

    agent-bridge setup work-trigger --confirm
    agent-bridge watch

Keep the watcher running under a persistent user service/supervisor. Then, from another shell after a heartbeat is recorded:

    agent-bridge doctor

Configured writer mode: {config['github']['mode']}.

AD-HOC WORK RULE:
A normal ChatGPT Web Chat must never invoke Work automatically. If Chat later encounters a capability gap, it must first explain the gap and bounded operation, ask whether Work may be used, ask which model/reasoning level to use (or disclose that only the platform default is available), and wait for explicit approval.
"""
