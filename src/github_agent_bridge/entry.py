from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .cli import build_parser as legacy_build_parser
from .cli import main as legacy_main
from .dependencies import (
    DependencyInstallError,
    apply_install_plan,
    build_install_plan,
    detect_environment,
    format_environment_status,
    format_install_plan,
    login_environment,
)
from .git import GitError, repo_root
from .connect import check_destination, destination_for, normalize_remote, prepare_repository
from .service import ServiceError, install_service, restart_service, service_status, uninstall_service
from .skill_install import SkillInstallError, install_skill, skill_status, uninstall_skill


def _repo() -> Path:
    return repo_root(Path.cwd())


def _root_help() -> str:
    legacy = legacy_build_parser().format_help().rstrip()
    return (
        legacy
        + "\n\nCross-platform Codex commands:\n"
        + "  connect   Prepare a repository from a GitHub remote URL and resume setup\n"
        + "  env       Check/install Git, GitHub CLI and Codex CLI prerequisites\n"
        + "  skill     Install/status/uninstall the Skill for Codex App, CLI and IDE\n"
        + "  service   Install/status/restart/uninstall the persistent local reviewer\n\n"
        + "Examples:\n"
        + "  agent-bridge connect https://github.com/OWNER/REPO.git\n"
        + "  agent-bridge env status\n"
        + "  agent-bridge env install\n"
        + "  agent-bridge skill install --scope user\n"
        + "  agent-bridge service install\n"
        + "  agent-bridge doctor\n"
    )


def _service_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-bridge service", description="Manage the persistent Codex reviewer watcher")
    sub = parser.add_subparsers(dest="action", required=True)

    install = sub.add_parser("install", help="Install a per-user watcher service for this repository")
    install.add_argument("--backend", default="auto", choices=["auto", "systemd", "launchd", "windows-task"])
    install.add_argument("--no-start", action="store_true", help="Install but do not start immediately")
    install.add_argument("--json", action="store_true", dest="json_output")

    status = sub.add_parser("status", help="Show watcher service installation/runtime status")
    status.add_argument("--backend", default="auto", choices=["auto", "systemd", "launchd", "windows-task"])
    status.add_argument("--json", action="store_true", dest="json_output")

    restart = sub.add_parser("restart", help="Restart the installed watcher service")
    restart.add_argument("--backend", default="auto", choices=["auto", "systemd", "launchd", "windows-task"])
    restart.add_argument("--json", action="store_true", dest="json_output")

    uninstall = sub.add_parser("uninstall", help="Remove the watcher service for this repository")
    uninstall.add_argument("--backend", default="auto", choices=["auto", "systemd", "launchd", "windows-task"])
    uninstall.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _skill_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-bridge skill", description="Install the GitHub Agent Bridge Skill for Codex App/CLI/IDE")
    sub = parser.add_subparsers(dest="action", required=True)

    install = sub.add_parser("install", help="Install/update the bundled Skill using real files")
    install.add_argument("--scope", choices=["user", "repo"], default="user")
    install.add_argument("--force", action="store_true", help="Replace an unmanaged or locally modified destination intentionally")
    install.add_argument("--json", action="store_true", dest="json_output")

    status = sub.add_parser("status", help="Show installed Skill state")
    status.add_argument("--scope", choices=["user", "repo"], default="user")
    status.add_argument("--json", action="store_true", dest="json_output")

    uninstall = sub.add_parser("uninstall", help="Remove the installed Skill copy")
    uninstall.add_argument("--scope", choices=["user", "repo"], default="user")
    uninstall.add_argument("--force", action="store_true", help="Delete an unmanaged or locally modified destination intentionally")
    uninstall.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _env_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-bridge env",
        description="Check and install cross-platform prerequisites for Codex App/CLI bridge operation",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    status = sub.add_parser("status", help="Show Git/GitHub CLI/Codex CLI and authentication readiness")
    status.add_argument("--skip-codex", action="store_true", help="Check dispatch-only desktop mode; do not require Codex CLI")
    status.add_argument("--json", action="store_true", dest="json_output")

    install = sub.add_parser("install", help="Install missing prerequisites after an explicit confirmation")
    install.add_argument("--yes", action="store_true", help="Confirm the displayed machine changes non-interactively")
    install.add_argument("--skip-codex", action="store_true", help="Install only dispatch prerequisites; skip Codex CLI")
    install.add_argument("--skip-login", action="store_true", help="Install binaries but do not start interactive GitHub/Codex login")
    install.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _print_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for key in (
        "backend", "scope", "installed", "managed", "modified", "active", "up_to_date",
        "detail", "path", "definition", "state_dir",
    ):
        if key in result:
            print(f"{key}: {result[key]}")


def _skill_repo(scope: str) -> Optional[Path]:
    return _repo() if scope == "repo" else None


def _service_main(argv: list[str]) -> int:
    args = _service_parser().parse_args(argv)
    repo = _repo()
    if args.action == "install":
        result = install_service(repo, backend=args.backend, start=not args.no_start)
    elif args.action == "status":
        result = service_status(repo, backend=args.backend)
    elif args.action == "restart":
        result = restart_service(repo, backend=args.backend)
    else:
        result = uninstall_service(repo, backend=args.backend)
    _print_result(result, json_output=args.json_output)
    return 0 if result.get("installed", False) or args.action == "uninstall" else 1


def _skill_main(argv: list[str]) -> int:
    args = _skill_parser().parse_args(argv)
    repo = _skill_repo(args.scope)
    if args.action == "install":
        result = install_skill(scope=args.scope, repo=repo, force=args.force)
    elif args.action == "status":
        result = skill_status(scope=args.scope, repo=repo)
    else:
        result = uninstall_skill(scope=args.scope, repo=repo, force=args.force)
    _print_result(result, json_output=args.json_output)
    if args.action == "uninstall":
        return 0
    return 0 if result.get("installed") and result.get("up_to_date") else 1


def _env_main(argv: list[str]) -> int:
    args = _env_parser().parse_args(argv)
    include_codex = not args.skip_codex
    status = detect_environment(include_codex=include_codex)

    if args.action == "status":
        if args.json_output:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            print(format_environment_status(status))
        ready_key = "unattended_review_ready" if include_codex else "dispatch_ready"
        return 0 if status[ready_key] else 1

    steps = build_install_plan(status, include_codex=include_codex)
    needs_login = (not args.skip_login) and (
        not status["gh"].get("authenticated")
        or (include_codex and not status["codex"].get("authenticated"))
    )
    requires_confirmation = bool(steps or needs_login)

    if args.json_output and requires_confirmation and not args.yes:
        print(json.dumps({
            "status": status,
            "install_plan": [step.as_dict() for step in steps],
            "login_required": needs_login,
            "confirmation_required": True,
        }, ensure_ascii=False, indent=2))
        return 2

    if requires_confirmation and not args.yes:
        print(format_install_plan(steps, status, include_codex=include_codex))
        answer = input("Proceed with these machine changes? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No changes made.")
            return 2
    elif not args.json_output:
        print(format_install_plan(steps, status, include_codex=include_codex))

    if steps:
        apply_install_plan(steps)
    if not args.skip_login:
        final = login_environment(include_codex=include_codex)
    else:
        final = detect_environment(include_codex=include_codex)

    if args.json_output:
        print(json.dumps({
            "status": final,
            "install_plan": [step.as_dict() for step in steps],
            "login_started": bool(needs_login and not args.skip_login),
            "confirmation_required": False,
        }, ensure_ascii=False, indent=2))
    else:
        print("\n" + format_environment_status(final))

    binaries_ready = bool(final["git"].get("available") and final["gh"].get("available"))
    if include_codex:
        binaries_ready = binaries_ready and bool(final["codex"].get("available"))
    ready = binaries_ready if args.skip_login else final["unattended_review_ready" if include_codex else "dispatch_ready"]
    return 0 if ready else 1


def _connect_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="agent-bridge connect", description="Prepare or resume a GitHub repository using only its remote URL")
    parser.add_argument("remote")
    parser.add_argument("--directory", help="Use this checkout instead of the managed per-user location")
    parser.add_argument("--yes", action="store_true", help="Authorize dependency installation, local checkout and bridge configuration")
    parser.add_argument("--skip-install", action="store_true", help="Use existing tools without installing dependencies")
    parser.add_argument("--skip-login", action="store_true", help="Do not open interactive login flows")
    parser.add_argument("--no-service", action="store_true", help="Do not install a watcher even if cloud prerequisites are confirmed")
    parser.add_argument("--test-command", action="append", dest="test_commands")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    slug, _ = normalize_remote(args.remote)
    destination = destination_for(slug, args.directory)
    check_destination(destination, slug)
    if not args.yes:
        plan = {"repository": slug, "directory": str(destination), "confirmation_required": True}
        if args.json_output:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 2
        print(f"Prepare {slug} at {destination}; install missing tools, request login, and configure the local bridge. Cloud write permissions are verified separately.")
        if not sys.stdin.isatty():
            print("No interactive terminal. Rerun with --yes after authorizing this setup.", file=sys.stderr)
            return 2
        if input("Proceed? [y/N] ").strip().lower() not in {"y", "yes"}:
            return 2
    if not args.skip_install:
        env_args = ["install", "--yes"]
        if args.skip_login:
            env_args.append("--skip-login")
        # Keep machine-readable connect output free of dependency status text.
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            if _env_main(env_args) != 0:
                return 2
    elif not args.skip_login:
        login_environment()
    environment = detect_environment()
    if not environment["dispatch_ready"]:
        print("Git and authenticated GitHub CLI are required. Run agent-bridge env install, then repeat this connect command.", file=sys.stderr)
        return 2
    result = prepare_repository(args.remote, directory=str(destination), test_commands=args.test_commands)
    pending = result["pending"]
    if not args.no_service and pending and all(c["name"] == "codex_watcher" for c in pending):
        result["service"] = install_service(destination)
        # Heartbeat may arrive after the command returns. Do not claim immediate readiness.
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Repository prepared: {result['directory']}")
        print(f"Full unattended loop ready: {'YES' if result['zero_touch_ready'] else 'NO'}")
        print("Open this directory in Codex and use $github-agent-bridge with your requirement.")
        for check in pending:
            print(f"Pending {check['name']}: {check['remediation']}")
        print("Repeat the same connect command after authorization to resume; existing work is preserved.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args or args in (["--help"], ["-h"]):
            print(_root_help())
            return 0
        if args[0] == "env":
            return _env_main(args[1:])
        if args[0] == "connect":
            return _connect_main(args[1:])
        if args[0] == "service":
            return _service_main(args[1:])
        if args[0] == "skill":
            return _skill_main(args[1:])
        return legacy_main(args)
    except (RuntimeError, GitError, ServiceError, SkillInstallError, DependencyInstallError, ValueError, OSError, EOFError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
