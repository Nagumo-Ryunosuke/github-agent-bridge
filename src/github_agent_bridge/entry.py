from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .cli import main as legacy_main
from .git import GitError, repo_root
from .service import ServiceError, install_service, restart_service, service_status, uninstall_service
from .skill_install import SkillInstallError, install_skill, skill_status, uninstall_skill


def _repo() -> Path:
    return repo_root(Path.cwd())


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
    install.add_argument("--force", action="store_true")
    install.add_argument("--json", action="store_true", dest="json_output")

    status = sub.add_parser("status", help="Show installed Skill state")
    status.add_argument("--scope", choices=["user", "repo"], default="user")
    status.add_argument("--json", action="store_true", dest="json_output")

    uninstall = sub.add_parser("uninstall", help="Remove the installed Skill copy")
    uninstall.add_argument("--scope", choices=["user", "repo"], default="user")
    uninstall.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _print_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for key in ("backend", "scope", "installed", "active", "up_to_date", "detail", "path", "definition", "state_dir"):
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
        result = uninstall_skill(scope=args.scope, repo=repo)
    _print_result(result, json_output=args.json_output)
    if args.action == "uninstall":
        return 0
    return 0 if result.get("installed") and result.get("up_to_date") else 1


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args and args[0] == "service":
            return _service_main(args[1:])
        if args and args[0] == "skill":
            return _skill_main(args[1:])
        return legacy_main(args)
    except (RuntimeError, GitError, ServiceError, SkillInstallError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
