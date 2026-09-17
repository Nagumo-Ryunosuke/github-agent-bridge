from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .dispatch import cancel_dispatch, dispatch_status, dispatch_task
from .config import (
    bootstrap_config,
    configure_implementation,
    configure_review,
    configure_writer,
    load_config,
)
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
from .doctor import doctor_report, format_doctor_report, infer_github_repository
from .git import GitError, current_branch, head_sha, repo_root
from .publisher import publish_task
from .security import validate_ai_tree
from .triggers import build_implementation_pr_body, build_task_pr_body
from .watcher import process_once, watch
from .writers import detect_writer, writer_contract


def _add_writer_confirmation_flags(parser: argparse.ArgumentParser) -> None:
    write_group = parser.add_mutually_exclusive_group()
    write_group.add_argument("--confirm-write", action="store_true")
    write_group.add_argument("--clear-write", action="store_true")
    unattended_group = parser.add_mutually_exclusive_group()
    unattended_group.add_argument("--confirm-unattended", action="store_true")
    unattended_group.add_argument("--clear-unattended", action="store_true")


def _add_billing_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--zero-personal-plus",
        action="store_true",
        help="Require an independently billed service-account backend",
    )
    group.add_argument(
        "--allow-personal-plus",
        action="store_true",
        help="Explicitly allow chatgpt-web to use the currently logged-in Web account",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-bridge",
        description="Active ChatGPT implementation dispatch with exact-head local Codex review",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("status")
    sub.add_parser("capabilities")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true", dest="json_output")

    setup = sub.add_parser("setup")
    setup_sub = setup.add_subparsers(dest="setup_command", required=True)

    bootstrap = setup_sub.add_parser("bootstrap")
    bootstrap.add_argument("--mode", choices=["managed", "custom-mcp", "readonly"])
    bootstrap.add_argument("--connection-name")
    bootstrap.add_argument("--mcp-server")
    _add_writer_confirmation_flags(bootstrap)
    bootstrap.add_argument("--repository", action="append", dest="repositories")
    bootstrap.add_argument("--test-command", action="append", dest="test_commands")
    bootstrap.add_argument("--codex-command")
    bootstrap.add_argument("--timeout", type=int)
    bootstrap_tests = bootstrap.add_mutually_exclusive_group()
    bootstrap_tests.add_argument("--require-tests", action="store_true")
    bootstrap_tests.add_argument("--allow-no-tests", action="store_true")

    writer = setup_sub.add_parser("writer")
    writer.add_argument("--mode", required=True, choices=["managed", "custom-mcp", "readonly"])
    writer.add_argument("--connection-name")
    writer.add_argument("--mcp-server")
    _add_writer_confirmation_flags(writer)
    writer.add_argument("--repository", action="append", dest="repositories")

    implementation = setup_sub.add_parser("implementation")
    implementation.add_argument("--backend", choices=["chatgpt-web", "service-account"])
    implementation.add_argument("--command")
    implementation.add_argument("--model")
    implementation.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
    )
    implementation.add_argument("--tool-mode", choices=["browser-only", "full"])
    implementation.add_argument("--timeout", type=int)
    implementation.add_argument(
        "--credential-env",
        help="Environment variable name only; never pass a credential value",
    )
    _add_billing_flags(implementation)

    review_setup = setup_sub.add_parser("review")
    review_setup.add_argument("--test-command", action="append", dest="test_commands")
    review_setup.add_argument("--codex-command")
    review_setup.add_argument("--model")
    review_setup.add_argument("--credential-env")
    review_setup.add_argument("--timeout", type=int)
    _add_billing_flags(review_setup)
    test_policy = review_setup.add_mutually_exclusive_group()
    test_policy.add_argument("--require-tests", action="store_true")
    test_policy.add_argument("--allow-no-tests", action="store_true")

    task = sub.add_parser("task")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    create = task_sub.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--assigned-to", default="chatgpt")
    create.add_argument("--reviewer")
    create.add_argument("--created-by", default="codex")
    create.add_argument("--priority", default="normal", choices=["low", "normal", "high", "critical"])
    create.add_argument("--base-branch")
    create.add_argument("--target-branch")
    show = task_sub.add_parser("show")
    show.add_argument("task_id")
    claim = task_sub.add_parser("claim")
    claim.add_argument("task_id")
    claim.add_argument("--agent", default="chatgpt")
    start = task_sub.add_parser("start")
    start.add_argument("task_id")
    self_review = task_sub.add_parser("self-review")
    self_review.add_argument("task_id")
    self_review.add_argument("--agent", default="chatgpt")
    finish = task_sub.add_parser("finish")
    finish.add_argument("task_id")
    finish.add_argument("--commit", dest="implementation_commit", required=True)
    finish.add_argument("--branch", required=True)
    finish.add_argument("--pr", type=int)
    finish.add_argument("--summary", required=True)
    finish.add_argument("--agent", default="chatgpt")
    complete = task_sub.add_parser("complete")
    complete.add_argument("task_id")

    publish = sub.add_parser("publish")
    publish_sub = publish.add_subparsers(dest="publish_command", required=True)
    publish_task_cmd = publish_sub.add_parser("task")
    publish_task_cmd.add_argument("task_id")

    dispatch = sub.add_parser("dispatch")
    dispatch_sub = dispatch.add_subparsers(dest="dispatch_command", required=True)
    for operation in ("run", "status", "cancel"):
        command = dispatch_sub.add_parser(operation)
        command.add_argument("task_id")
        command.add_argument("--phase", choices=["implement", "fix"], default="implement")
        command.add_argument("--head", help="Exact reviewed 40-character head; required for fix")
        if operation == "run":
            command.add_argument("--retry", action="store_true")
        if operation == "cancel":
            command.add_argument("--turn-id", required=True)

    drift = sub.add_parser("drift")
    drift.add_argument("task_id")

    review = sub.add_parser("review")
    review.add_argument("task_id")
    review.add_argument("--result", required=True, choices=["approve", "request-changes"])
    review.add_argument("--commit", dest="reviewed_commit", required=True)
    review.add_argument("--summary", required=True)
    review.add_argument("--reviewer")

    trigger = sub.add_parser("trigger")
    trigger_sub = trigger.add_subparsers(dest="trigger_command", required=True)
    task_pr = trigger_sub.add_parser("task-pr")
    task_pr.add_argument("task_id")
    impl_pr = trigger_sub.add_parser("implementation-pr")
    impl_pr.add_argument("task_id")
    impl_pr.add_argument("--head", required=True)
    impl_pr.add_argument("--summary", default="")

    watcher = sub.add_parser("watch")
    watcher.add_argument("--once", action="store_true")
    watcher.add_argument("--interval", type=int)

    sub.add_parser("validate")
    return parser


def _repo() -> Path:
    return repo_root(Path.cwd())


def _test_policy(args: argparse.Namespace) -> Optional[bool]:
    if getattr(args, "require_tests", False):
        return True
    if getattr(args, "allow_no_tests", False):
        return False
    return None


def _billing_policy(args: argparse.Namespace) -> Optional[bool]:
    if getattr(args, "zero_personal_plus", False):
        return True
    if getattr(args, "allow_personal_plus", False):
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
    implementation = config["implementation"]
    print(f"Repository: {repo.name}")
    print(f"Branch: {current_branch(repo)}")
    print(f"HEAD: {head_sha(repo)}")
    print(
        "Roles: "
        f"dispatcher={config['workflow']['dispatcher']} "
        f"developer={config['workflow']['developer']} "
        f"reviewer={config['workflow']['reviewer']}"
    )
    print(
        "Implementation: "
        f"backend={implementation.get('backend')} model={implementation.get('model')} "
        f"tool_mode={implementation.get('tool_mode')} sandbox={implementation.get('sandbox')} "
        f"zero_personal_plus={implementation.get('zero_personal_plus')}"
    )
    print(
        f"Writer: mode={writer['mode']} ready={writer['ready']} "
        f"unattended_ready={writer['unattended_ready']}"
    )
    print("\nTasks:")
    if not state["tasks"]:
        print("  (none)")
        return 0
    for task_id, task in sorted(state["tasks"].items()):
        print(
            f"  {task_id}  {task['status']:<18} "
            f"next={task.get('next_agent') or '-':<10} {task['title']}"
        )
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
            print(json.dumps(report, ensure_ascii=False, indent=2) if args.json_output else format_doctor_report(report))
            return 0 if report["zero_touch_ready"] else 1

        if args.command == "setup" and args.setup_command == "bootstrap":
            init_repo(repo)
            existing = load_config(repo)
            mode = args.mode or (
                existing["github"]["mode"]
                if existing["github"]["mode"] != "readonly"
                else "managed"
            )
            repositories = args.repositories
            if repositories is None:
                repositories = list(existing["github"].get("repositories") or [])
                inferred = infer_github_repository(repo)
                if (
                    inferred
                    and inferred["host"].lower() == "github.com"
                    and inferred["repository"] not in repositories
                ):
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
                timeout_seconds=args.timeout,
                require_tests_for_approval=_test_policy(args),
            )
            print(json.dumps({
                "github": config["github"],
                "implementation": config["implementation"],
                "review": config["review"],
            }, ensure_ascii=False, indent=2))
            print("\n" + format_doctor_report(doctor_report(repo)))
            return 0

        if args.command == "setup" and args.setup_command == "writer":
            config = configure_writer(
                repo,
                mode=args.mode,
                connection_name=args.connection_name,
                mcp_server=args.mcp_server,
                write_confirmed=_tri_state(args.confirm_write, args.clear_write),
                unattended_confirmed=_tri_state(args.confirm_unattended, args.clear_unattended),
                repositories=args.repositories,
            )
            print(json.dumps(config["github"], ensure_ascii=False, indent=2))
            return 0

        if args.command == "setup" and args.setup_command == "implementation":
            config = configure_implementation(
                repo,
                backend=args.backend,
                command=args.command,
                model=args.model,
                sandbox=args.sandbox,
                tool_mode=args.tool_mode,
                timeout_seconds=args.timeout,
                credential_env=args.credential_env,
                zero_personal_plus=_billing_policy(args),
            )
            print(json.dumps(config["implementation"], ensure_ascii=False, indent=2))
            return 0

        if args.command == "setup" and args.setup_command == "review":
            config = configure_review(
                repo,
                test_commands=args.test_commands,
                codex_command=args.codex_command,
                model=args.model,
                credential_env=args.credential_env,
                zero_personal_plus=_billing_policy(args),
                timeout_seconds=args.timeout,
                require_tests_for_approval=_test_policy(args),
            )
            print(json.dumps(config["review"], ensure_ascii=False, indent=2))
            return 0

        if args.command == "task":
            if args.task_command == "create":
                print(create_task(
                    repo,
                    title=args.title,
                    objective=args.objective,
                    assigned_to=args.assigned_to,
                    reviewer=args.reviewer,
                    created_by=args.created_by,
                    priority=args.priority,
                    base_branch=args.base_branch,
                    target_branch=args.target_branch,
                ))
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

        if args.command == "publish" and args.publish_command == "task":
            print(json.dumps(publish_task(repo, args.task_id), ensure_ascii=False, indent=2))
            return 0

        if args.command == "dispatch":
            if args.dispatch_command == "run":
                result = dispatch_task(
                    repo,
                    args.task_id,
                    phase=args.phase,
                    head=args.head,
                    retry=args.retry,
                )
            elif args.dispatch_command == "status":
                result = dispatch_status(repo, args.task_id, phase=args.phase, head=args.head)
            else:
                result = cancel_dispatch(
                    repo,
                    args.task_id,
                    phase=args.phase,
                    head=args.head,
                    turn_id=args.turn_id,
                )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] not in {"failed", "cancelled"} else 1

        if args.command == "drift":
            report = drift_report(repo, args.task_id)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2 if report["drift"] and not report.get("metadata_only") else 0

        if args.command == "review":
            assigned = get_task(repo, args.task_id).get("reviewer") or "codex"
            path = review_task(
                repo,
                args.task_id,
                result=args.result,
                reviewed_commit=args.reviewed_commit,
                summary=args.summary,
                reviewer=args.reviewer or assigned,
            )
            print(path.relative_to(repo))
            return 0

        if args.command == "trigger":
            if args.trigger_command == "task-pr":
                print(build_task_pr_body(repo, args.task_id))
            else:
                print(build_implementation_pr_body(repo, args.task_id, args.head, args.summary))
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
            writer = detect_writer(repo)
            if writer["mode"] != "readonly" and not writer["ready"]:
                errors.append(
                    f"writer mode {writer['mode']} is selected but not write-ready: {writer['reason']}"
                )
            if errors:
                for error in errors:
                    print(f"ERROR: {error}")
                return 1
            print("OK: bridge state/config are valid and no obvious secrets were detected in .ai")
            return 0
    except (RuntimeError, GitError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
