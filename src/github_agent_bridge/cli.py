from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import (
    claim_task,
    complete_task,
    create_task,
    drift_report,
    finish_task,
    get_task,
    init_repo,
    load_state,
    review_task,
    start_task,
    validate_state,
)
from .git import GitError, current_branch, head_sha, repo_root
from .security import validate_ai_tree


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-bridge", description="GitHub-native AI agent handoff protocol")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize .ai collaboration state")
    sub.add_parser("status", help="Show active handoff tasks")

    task = sub.add_parser("task", help="Task operations")
    task_sub = task.add_subparsers(dest="task_command", required=True)

    create = task_sub.add_parser("create", help="Create a commit-pinned task contract")
    create.add_argument("--title", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--assigned-to", default="codex")
    create.add_argument("--created-by", default="chatgpt")
    create.add_argument("--priority", default="normal", choices=["low", "normal", "high", "critical"])
    create.add_argument("--base-branch")
    create.add_argument("--target-branch")

    show = task_sub.add_parser("show", help="Show one task")
    show.add_argument("task_id")

    claim = task_sub.add_parser("claim", help="Claim a ready task")
    claim.add_argument("task_id")
    claim.add_argument("--agent", default="codex")

    start = task_sub.add_parser("start", help="Move a claimed task to in_progress")
    start.add_argument("task_id")

    finish = task_sub.add_parser("finish", help="Record implementation handoff")
    finish.add_argument("task_id")
    finish.add_argument("--commit", dest="implementation_commit", required=True)
    finish.add_argument("--branch", required=True)
    finish.add_argument("--pr", type=int)
    finish.add_argument("--summary", required=True)
    finish.add_argument("--agent", default="codex")

    complete = task_sub.add_parser("complete", help="Mark an approved task done")
    complete.add_argument("task_id")

    drift = sub.add_parser("drift", help="Compare a task base commit with its base branch")
    drift.add_argument("task_id")

    review = sub.add_parser("review", help="Create a commit-pinned review")
    review.add_argument("task_id")
    review.add_argument("--result", required=True, choices=["approve", "request-changes"])
    review.add_argument("--commit", dest="reviewed_commit", required=True)
    review.add_argument("--summary", required=True)
    review.add_argument("--reviewer", default="chatgpt")

    sub.add_parser("validate", help="Validate state and scan .ai for likely secrets")
    return parser


def _repo() -> Path:
    return repo_root(Path.cwd())


def cmd_status(repo: Path) -> int:
    state = load_state(repo)
    print(f"Repository: {repo.name}")
    print(f"Branch: {current_branch(repo)}")
    print(f"HEAD: {head_sha(repo)}")
    print("\nTasks:")
    if not state["tasks"]:
        print("  (none)")
        return 0
    for task_id, task in sorted(state["tasks"].items()):
        print(f"  {task_id}  {task['status']:<18} next={task.get('next_agent') or '-':<10} {task['title']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = _repo()
        if args.command == "init":
            created = init_repo(repo)
            print(f"Initialized {repo}")
            for path in created:
                print(f"  + {path.relative_to(repo)}")
            return 0
        if args.command == "status":
            return cmd_status(repo)
        if args.command == "task":
            if args.task_command == "create":
                task_id = create_task(
                    repo,
                    title=args.title,
                    objective=args.objective,
                    assigned_to=args.assigned_to,
                    created_by=args.created_by,
                    priority=args.priority,
                    base_branch=args.base_branch,
                    target_branch=args.target_branch,
                )
                print(task_id)
                return 0
            if args.task_command == "show":
                print(json.dumps(get_task(repo, args.task_id), ensure_ascii=False, indent=2))
                return 0
            if args.task_command == "claim":
                claim_task(repo, args.task_id, args.agent)
                print(f"{args.task_id}: claimed by {args.agent}")
                return 0
            if args.task_command == "start":
                start_task(repo, args.task_id)
                print(f"{args.task_id}: in_progress")
                return 0
            if args.task_command == "finish":
                path = finish_task(
                    repo,
                    args.task_id,
                    implementation_commit=args.implementation_commit,
                    branch=args.branch,
                    pr=args.pr,
                    summary=args.summary,
                    agent=args.agent,
                )
                print(path.relative_to(repo))
                return 0
            if args.task_command == "complete":
                complete_task(repo, args.task_id)
                print(f"{args.task_id}: done")
                return 0
        if args.command == "drift":
            report = drift_report(repo, args.task_id)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2 if report["drift"] else 0
        if args.command == "review":
            path = review_task(
                repo,
                args.task_id,
                result=args.result,
                reviewed_commit=args.reviewed_commit,
                summary=args.summary,
                reviewer=args.reviewer,
            )
            print(path.relative_to(repo))
            return 0
        if args.command == "validate":
            errors = validate_state(repo)
            errors.extend(validate_ai_tree(repo))
            if errors:
                for error in errors:
                    print(f"ERROR: {error}")
                return 1
            print("OK: handoff state is valid and no obvious secrets were detected in .ai")
            return 0
    except (RuntimeError, GitError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
