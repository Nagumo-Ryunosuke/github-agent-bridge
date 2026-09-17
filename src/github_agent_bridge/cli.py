from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .config import bootstrap_config, configure_dispatch, configure_review, configure_writer, load_config
from .core import (
    claim_task,
    complete_task,
    create_task,
    drift_report,
    finish_task,
    get_task,
    init_repo,
    load_state,
    mark_self_reviewed,
    review_task,
    start_task,
    validate_state,
)
from .dispatch import DispatchError, dispatch_status, dispatch_task, refresh_dispatch_status
from .doctor import doctor_report, format_doctor_report, infer_github_repository
from .git import GitError, current_branch, head_sha, repo_root
from .publisher import publish_task
from .security import validate_ai_tree
from .triggers import build_implementation_pr_body, build_task_pr_body
from .watcher import process_once, watch
from .writers import detect_writer, writer_contract


def _add_writer_confirmation_flags(parser: argparse.ArgumentParser) -> None:
    write_group = parser.add_mutually_exclusive_group()
    write_group.add_argument("--confirm-write", action="store_true", help="Confirm that the configured connection exposes write actions")
    write_group.add_argument("--clear-write", action="store_true", help="Revoke the stored write-capability confirmation")
    unattended_group = parser.add_mutually_exclusive_group()
    unattended_group.add_argument("--confirm-unattended", action="store_true", help="Confirm that workspace/app policy permits unattended writes")
    unattended_group.add_argument("--clear-unattended", action="store_true", help="Revoke the stored unattended-write confirmation")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-bridge", description="GitHub-native active Chat dispatch / Codex exact-SHA review automation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize .ai collaboration state and config")
    sub.add_parser("status", help="Show tasks, dispatch state, role routing, and writer status")
    sub.add_parser("capabilities", help="Show configured GitHub writer capabilities")
    doctor = sub.add_parser("doctor", help="Verify end-to-end zero-touch readiness")
    doctor.add_argument("--json", action="store_true", dest="json_output", help="Emit machine-readable diagnostic JSON")

    setup = sub.add_parser("setup", help="Configure bridge integrations")
    setup_sub = setup.add_subparsers(dest="setup_command", required=True)

    bootstrap = setup_sub.add_parser("bootstrap", help="One-shot local setup for the active-dispatch workflow")
    bootstrap.add_argument("--mode", choices=["managed", "custom-mcp", "readonly"], help="Preserve the current writer mode unless explicitly changed")
    bootstrap.add_argument("--connection-name")
    bootstrap.add_argument("--mcp-server")
    _add_writer_confirmation_flags(bootstrap)
    bootstrap.add_argument("--repository", action="append", dest="repositories", help="Allowed owner/name repository; defaults to/merges the GitHub origin when detectable")
    bootstrap.add_argument("--test-command", action="append", dest="test_commands", help="Trusted local test command; repeat for multiple commands")
    bootstrap.add_argument("--codex-command")
    bootstrap.add_argument("--codex-api-key-env")
    bootstrap.add_argument("--timeout", type=int)
    bootstrap.add_argument("--dispatch-api-key-env")
    bootstrap.add_argument("--dispatch-model")
    bootstrap.add_argument("--dispatch-mcp-server-url")
    bootstrap.add_argument("--dispatch-mcp-token-env")
    bootstrap_tests = bootstrap.add_mutually_exclusive_group()
    bootstrap_tests.add_argument("--require-tests", action="store_true")
    bootstrap_tests.add_argument("--allow-no-tests", action="store_true")

    writer = setup_sub.add_parser("writer", help="Configure optional GitHub writer metadata")
    writer.add_argument("--mode", required=True, choices=["managed", "custom-mcp", "readonly"])
    writer.add_argument("--connection-name")
    writer.add_argument("--mcp-server")
    _add_writer_confirmation_flags(writer)
    writer.add_argument("--repository", action="append", dest="repositories", help="Allowed owner/name repository; repeat to add more")

    dispatch_setup = setup_sub.add_parser("dispatch", help="Configure active API Chat dispatch")
    dispatch_setup.add_argument("--provider", choices=["openai"])
    dispatch_setup.add_argument("--credential-kind", choices=["service-account", "workspace-agent"])
    dispatch_setup.add_argument("--api-base")
    dispatch_setup.add_argument("--api-key-env")
    dispatch_setup.add_argument("--model")
    dispatch_setup.add_argument("--mcp-server-url")
    dispatch_setup.add_argument("--mcp-token-env")
    dispatch_setup.add_argument("--timeout", type=int)

    review_setup = setup_sub.add_parser("review", help="Configure local Codex validation")
    review_setup.add_argument("--test-command", action="append", dest="test_commands", help="Trusted local test command; repeat for multiple commands")
    review_setup.add_argument("--codex-command")
    review_setup.add_argument("--api-key-env", help="Environment variable containing the separately billed Codex service credential")
    review_setup.add_argument("--timeout", type=int)
    test_policy = review_setup.add_mutually_exclusive_group()
    test_policy.add_argument("--require-tests", action="store_true", help="Require at least one configured local test command before APPROVE")
    test_policy.add_argument("--allow-no-tests", action="store_true", help="Allow APPROVE without configured local test commands")

    task = sub.add_parser("task", help="Task operations")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    create = task_sub.add_parser("create", help="Create a commit-pinned task for active implementation dispatch")
    create.add_argument("--title", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--assigned-to", default="chatgpt")
    create.add_argument("--reviewer", default="codex")
    create.add_argument("--created-by", default="codex")
    create.add_argument("--priority", default="normal", choices=["low", "normal", "high", "critical"])
    create.add_argument("--base-branch")
    create.add_argument("--target-branch")
    show = task_sub.add_parser("show", help="Show one task")
    show.add_argument("task_id")
    claim = task_sub.add_parser("claim", help="Claim a ready task")
    claim.add_argument("task_id")
    claim.add_argument("--agent", default="chatgpt")
    start = task_sub.add_parser("start", help="Move a claimed/changes-requested task to in_progress")
    start.add_argument("task_id")
    self_review = task_sub.add_parser("self-review", help="Record implementation first-pass self-review")
    self_review.add_argument("task_id")
    self_review.add_argument("--agent", default="chatgpt")
    finish = task_sub.add_parser("finish", help="Record implementation handoff to Codex")
    finish.add_argument("task_id")
    finish.add_argument("--commit", dest="implementation_commit", required=True)
    finish.add_argument("--branch", required=True)
    finish.add_argument("--pr", type=int)
    finish.add_argument("--summary", required=True)
    finish.add_argument("--agent", default="chatgpt")
    complete = task_sub.add_parser("complete", help="Mark an approved task done after human acceptance/merge")
    complete.add_argument("task_id")

    publish = sub.add_parser("publish", help="Publish task artifacts and actively dispatch implementation")
    publish_sub = publish.add_subparsers(dest="publish_command", required=True)
    publish_task_cmd = publish_sub.add_parser("task", help="Publish a Task PR and dispatch it without GitHub event triggers")
    publish_task_cmd.add_argument("task_id")

    dispatch = sub.add_parser("dispatch", help="Actively create/query implementation Chat sessions")
    dispatch_sub = dispatch.add_subparsers(dest="dispatch_command", required=True)
    dispatch_task_cmd = dispatch_sub.add_parser("task", help="Dispatch a task or exact-SHA revision")
    dispatch_task_cmd.add_argument("task_id")
    dispatch_task_cmd.add_argument("--phase", choices=["implement", "fix"], default="implement")
    dispatch_task_cmd.add_argument("--reviewed-head")
    dispatch_task_cmd.add_argument("--implementation-pr-url")
    dispatch_task_cmd.add_argument("--task-pr-url")
    dispatch_status_cmd = dispatch_sub.add_parser("status", help="Query persisted dispatch state")
    dispatch_status_cmd.add_argument("task_id", nargs="?")
    dispatch_status_cmd.add_argument("--refresh", action="store_true", help="Refresh API response status and trusted GitHub PR facts")

    drift = sub.add_parser("drift", help="Compare a task base commit with its base branch")
    drift.add_argument("task_id")
    review = sub.add_parser("review", help="Record a manual commit-pinned review")
    review.add_argument("task_id")
    review.add_argument("--result", required=True, choices=["approve", "request-changes"])
    review.add_argument("--commit", dest="reviewed_commit", required=True)
    review.add_argument("--summary", required=True)
    review.add_argument("--reviewer", default="codex")

    render = sub.add_parser("render", help="Render durable GitHub PR marker artifacts")
    render_sub = render.add_subparsers(dest="render_command", required=True)
    task_pr = render_sub.add_parser("task-pr", help="Render a Task PR body marker")
    task_pr.add_argument("task_id")
    impl_pr = render_sub.add_parser("implementation-pr", help="Render an Implementation PR body marker")
    impl_pr.add_argument("task_id")
    impl_pr.add_argument("--summary", default="")

    watcher = sub.add_parser("watch", help="Watch implementation PRs, review exact SHAs, and actively re-dispatch REVISE")
    watcher.add_argument("--once", action="store_true")
    watcher.add_argument("--interval", type=int)
    sub.add_parser("validate", help="Validate state/config and scan .ai for likely secrets")
    return parser


def _repo() -> Path:
    return repo_root(Path.cwd())


def _test_policy(args: argparse.Namespace) -> Optional[bool]:
    if getattr(args, "require_tests", False):
        return True
    if getattr(args, "allow_no_tests", False):
        return False
    return None


def _tri_state(confirm: bool, clear: bool) -> Optional[bool]:
    if confirm:
        return True
    if clear:
        return False
    return None


def cmd_status(repo: Path) -> int:
    state = load_state(repo)
    config = load_config(repo)
    writer = detect_writer(repo)
    print(f"Repository: {repo.name}")
    print(f"Branch: {current_branch(repo)}")
    print(f"HEAD: {head_sha(repo)}")
    print(f"Roles: dispatcher={config['workflow']['dispatcher']} developer={config['workflow']['developer']} reviewer={config['workflow']['reviewer']}")
    print(f"Writer: mode={writer['mode']} ready={writer['ready']} unattended_ready={writer['unattended_ready']}")
    print(f"Dispatch: provider={config['dispatch']['provider']} credential={config['dispatch']['credential_kind']} model={config['dispatch']['model']}")
    try:
        active_tasks = dispatch_status(repo).get("tasks", {})
    except DispatchError:
        active_tasks = {}
    print("\nTasks:")
    if not state["tasks"]:
        print("  (none)")
        return 0
    for task_id, task_value in sorted(state["tasks"].items()):
        runtime_status = active_tasks.get(task_id, {}).get("status") or "-"
        print(f"  {task_id}  {task_value['status']:<18} dispatch={runtime_status:<24} next={task_value.get('next_agent') or '-':<10} {task_value['title']}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
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
        if args.command == "capabilities":
            print(json.dumps({"writer": detect_writer(repo), "contract": writer_contract()}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "doctor":
            report = doctor_report(repo)
            if args.json_output:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(format_doctor_report(report))
            return 0 if report["zero_touch_ready"] else 1

        if args.command == "setup" and args.setup_command == "bootstrap":
            init_repo(repo)
            existing = load_config(repo)
            mode = args.mode or existing["github"]["mode"]
            repositories = args.repositories
            if repositories is None:
                repositories = list(existing["github"].get("repositories") or [])
                inferred = infer_github_repository(repo)
                if inferred and inferred["host"].lower() == "github.com" and inferred["repository"] not in repositories:
                    repositories.append(inferred["repository"])
            config = bootstrap_config(
                repo,
                mode=mode,
                connection_name=args.connection_name,
                mcp_server=args.mcp_server,
                write_confirmed=_tri_state(args.confirm_write, args.clear_write),
                unattended_confirmed=_tri_state(args.confirm_unattended, args.clear_unattended),
                repositories=repositories,
                test_commands=args.test_commands,
                codex_command=args.codex_command,
                codex_api_key_env=args.codex_api_key_env,
                timeout_seconds=args.timeout,
                require_tests_for_approval=_test_policy(args),
                dispatch_api_key_env=args.dispatch_api_key_env,
                dispatch_model=args.dispatch_model,
                dispatch_mcp_server_url=args.dispatch_mcp_server_url,
                dispatch_mcp_token_env=args.dispatch_mcp_token_env,
            )
            report = doctor_report(repo)
            print(json.dumps({"github": config["github"], "dispatch": config["dispatch"], "review": config["review"], "automation": config["automation"]}, ensure_ascii=False, indent=2))
            print("\n" + format_doctor_report(report))
            return 0
        if args.command == "setup" and args.setup_command == "writer":
            config = configure_writer(repo, mode=args.mode, connection_name=args.connection_name, mcp_server=args.mcp_server, write_confirmed=_tri_state(args.confirm_write, args.clear_write), unattended_confirmed=_tri_state(args.confirm_unattended, args.clear_unattended), repositories=args.repositories)
            print(json.dumps(config["github"], ensure_ascii=False, indent=2))
            return 0
        if args.command == "setup" and args.setup_command == "dispatch":
            config = configure_dispatch(repo, provider=args.provider, credential_kind=args.credential_kind, api_base=args.api_base, api_key_env=args.api_key_env, model=args.model, mcp_server_url=args.mcp_server_url, mcp_token_env=args.mcp_token_env, timeout_seconds=args.timeout)
            print(json.dumps(config["dispatch"], ensure_ascii=False, indent=2))
            return 0
        if args.command == "setup" and args.setup_command == "review":
            config = configure_review(repo, test_commands=args.test_commands, codex_command=args.codex_command, api_key_env=args.api_key_env, timeout_seconds=args.timeout, require_tests_for_approval=_test_policy(args))
            print(json.dumps(config["review"], ensure_ascii=False, indent=2))
            return 0

        if args.command == "task":
            if args.task_command == "create":
                task_id = create_task(repo, title=args.title, objective=args.objective, assigned_to=args.assigned_to, reviewer=args.reviewer, created_by=args.created_by, priority=args.priority, base_branch=args.base_branch, target_branch=args.target_branch)
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
            if args.task_command == "self-review":
                mark_self_reviewed(repo, args.task_id, agent=args.agent)
                print(f"{args.task_id}: self-review recorded by {args.agent}")
                return 0
            if args.task_command == "finish":
                path = finish_task(repo, args.task_id, implementation_commit=args.implementation_commit, branch=args.branch, pr=args.pr, summary=args.summary, agent=args.agent)
                print(path.relative_to(repo))
                return 0
            if args.task_command == "complete":
                complete_task(repo, args.task_id)
                print(f"{args.task_id}: done")
                return 0

        if args.command == "publish" and args.publish_command == "task":
            published = publish_task(repo, args.task_id)
            dispatched = dispatch_task(repo, args.task_id, task_pr_url=published["url"])
            print(json.dumps({"published": published, "dispatch": dispatched}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "dispatch":
            if args.dispatch_command == "task":
                result = dispatch_task(repo, args.task_id, phase=args.phase, reviewed_head=args.reviewed_head, implementation_pr_url=args.implementation_pr_url, task_pr_url=args.task_pr_url)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            if args.dispatch_command == "status":
                if args.refresh:
                    if not args.task_id:
                        raise RuntimeError("dispatch status --refresh requires a task id")
                    result = refresh_dispatch_status(repo, args.task_id)
                else:
                    result = dispatch_status(repo, args.task_id)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0

        if args.command == "drift":
            report = drift_report(repo, args.task_id)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2 if report["drift"] and not report.get("metadata_only") else 0
        if args.command == "review":
            path = review_task(repo, args.task_id, result=args.result, reviewed_commit=args.reviewed_commit, summary=args.summary, reviewer=args.reviewer)
            print(path.relative_to(repo))
            return 0
        if args.command == "render":
            if args.render_command == "task-pr":
                print(build_task_pr_body(repo, args.task_id))
            elif args.render_command == "implementation-pr":
                print(build_implementation_pr_body(repo, args.task_id, args.summary))
            return 0
        if args.command == "watch":
            if args.once:
                print(json.dumps(process_once(repo), ensure_ascii=False, indent=2))
            else:
                watch(repo, args.interval)
            return 0
        if args.command == "validate":
            errors = validate_state(repo)
            errors.extend(validate_ai_tree(repo))
            if errors:
                for error in errors:
                    print(f"ERROR: {error}")
                return 1
            print("OK: bridge state/config are valid and no obvious secrets were detected in .ai")
            return 0
    except (RuntimeError, GitError, DispatchError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
