from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from .config import CONFIG_PATH, load_config
from .writers import detect_writer


CheckRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]
Which = Callable[[str], Optional[str]]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def parse_github_remote(url: str) -> Optional[dict[str, str]]:
    value = (url or "").strip()
    patterns = [
        r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        r"^ssh://git@(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        r"^git@(?P<host>[^:]+):(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            data = match.groupdict()
            return {
                "host": data["host"],
                "repository": f"{data['owner']}/{data['repo']}",
            }
    return None


def infer_github_repository(repo: Path, runner: CheckRunner = _run) -> Optional[dict[str, str]]:
    proc = runner(["git", "config", "--get", "remote.origin.url"], repo)
    if proc.returncode != 0:
        return None
    return parse_github_remote(proc.stdout.strip())


def _check(name: str, status: str, message: str, remediation: str = "", critical: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "critical": critical,
        "message": message,
        "remediation": remediation,
    }


def doctor_report(
    repo: Path,
    *,
    runner: CheckRunner = _run,
    which: Which = shutil.which,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    config = load_config(repo)

    initialized = (repo / ".ai/state/tasks.json").exists() and (repo / CONFIG_PATH).exists()
    checks.append(_check(
        "bridge_initialized",
        "pass" if initialized else "fail",
        "bridge state and config are initialized" if initialized else "bridge state/config are not fully initialized",
        "run `agent-bridge init` or `agent-bridge setup bootstrap`",
    ))

    origin = infer_github_repository(repo, runner=runner)
    if not origin:
        checks.append(_check(
            "github_origin",
            "fail",
            "origin is missing or is not a recognized GitHub remote",
            "configure remote `origin` using a github.com repository URL",
        ))
        repository = None
        host = None
    else:
        repository = origin["repository"]
        host = origin["host"]
        supported_host = host.lower() == "github.com"
        checks.append(_check(
            "github_origin",
            "pass" if supported_host else "fail",
            f"origin resolves to {host}/{repository}",
            "GitHub-triggered ChatGPT Work tasks currently require github.com; use github.com or keep this deployment manual/custom",
        ))

    gh_path = which("gh")
    if gh_path:
        gh_auth = runner([gh_path, "auth", "status", "-h", "github.com"], repo)
        checks.append(_check(
            "github_cli",
            "pass" if gh_auth.returncode == 0 else "fail",
            "GitHub CLI is installed and authenticated" if gh_auth.returncode == 0 else "GitHub CLI is installed but not authenticated for github.com",
            "run `gh auth login` on the Codex/reviewer machine",
        ))
    else:
        checks.append(_check("github_cli", "fail", "GitHub CLI (`gh`) was not found", "install GitHub CLI and authenticate it"))

    codex_command = str(config["review"].get("codex_command") or "codex")
    codex_path = which(codex_command)
    if not codex_path and ("/" in codex_command or "\\" in codex_command):
        candidate = Path(codex_command).expanduser()
        codex_path = str(candidate) if candidate.exists() else None
    if codex_path:
        codex_version = runner([codex_path, "--version"], repo)
        checks.append(_check(
            "codex_cli",
            "pass" if codex_version.returncode == 0 else "fail",
            "Codex CLI is available" if codex_version.returncode == 0 else "Codex CLI command exists but failed to run",
            "verify the configured review.codex_command and Codex installation",
        ))
    else:
        checks.append(_check("codex_cli", "fail", f"Codex CLI was not found: {codex_command}", "install Codex CLI or configure `agent-bridge setup review --codex-command ...`"))

    writer = detect_writer(repo)
    checks.append(_check(
        "writer_ready",
        "pass" if writer["ready"] else "fail",
        writer["reason"],
        "configure a write-capable managed connection or custom MCP and explicitly confirm write capability",
    ))
    checks.append(_check(
        "writer_unattended",
        "pass" if writer["unattended_ready"] else "fail",
        "writer is confirmed for unattended actions" if writer["unattended_ready"] else "unattended writer actions are not confirmed",
        "confirm workspace/app approval policy, then rerun setup with `--confirm-unattended`",
    ))

    repositories = list(config["github"].get("repositories") or [])
    allowlisted = bool(repository and repository in repositories)
    checks.append(_check(
        "repository_allowlist",
        "pass" if allowlisted else "fail",
        f"current repository {repository} is allowlisted" if allowlisted else f"current repository {repository or '(unknown)'} is not in github.repositories",
        "rerun bootstrap with `--repository owner/name` (or let bootstrap infer origin)",
    ))

    work_trigger_confirmed = bool(config["automation"].get("work_trigger_confirmed"))
    checks.append(_check(
        "chatgpt_work_trigger",
        "pass" if work_trigger_confirmed else "fail",
        "ChatGPT Work GitHub event triggers are confirmed" if work_trigger_confirmed else "ChatGPT Work GitHub event triggers have not been confirmed",
        "create the two one-time Work triggers on ChatGPT Web/iOS/Android, then run `agent-bridge setup work-trigger --confirm`",
    ))

    test_commands = list(config["review"].get("test_commands") or [])
    require_tests = bool(config["review"].get("require_tests_for_approval", True))
    tests_ready = bool(test_commands) or not require_tests
    checks.append(_check(
        "review_test_policy",
        "pass" if tests_ready else "fail",
        f"{len(test_commands)} authoritative local test command(s) configured" if test_commands else "no local test commands configured",
        "configure at least one trusted command with `agent-bridge setup review --test-command ...` or explicitly allow no-tests",
    ))

    prefix = str(config["automation"].get("implementation_branch_prefix") or "")
    prefix_safe = bool(prefix and prefix.endswith("/") and re.fullmatch(r"[A-Za-z0-9._/-]+", prefix))
    checks.append(_check(
        "implementation_branch_policy",
        "pass" if prefix_safe else "fail",
        f"implementation branches are restricted to `{prefix}*`" if prefix_safe else "implementation branch prefix is missing or unsafe",
        "set automation.implementation_branch_prefix to a dedicated prefix such as `ai/`",
    ))

    human_merge = bool(config["workflow"].get("human_merge_required", True))
    checks.append(_check(
        "human_merge_gate",
        "pass" if human_merge else "warn",
        "final merge remains human-controlled" if human_merge else "automatic merge is enabled outside the recommended safety boundary",
        "set workflow.human_merge_required=true unless you intentionally accept automated merge risk",
        critical=False,
    ))

    zero_touch_ready = all(item["status"] == "pass" for item in checks if item["critical"])
    return {
        "schema_version": 1,
        "zero_touch_ready": zero_touch_ready,
        "repository": repository,
        "host": host,
        "writer": writer,
        "checks": checks,
    }


def format_doctor_report(report: dict[str, Any]) -> str:
    labels = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [f"Zero-touch ready: {'YES' if report['zero_touch_ready'] else 'NO'}", ""]
    for item in report["checks"]:
        lines.append(f"[{labels[item['status']]}] {item['name']}: {item['message']}")
        if item["status"] != "pass" and item.get("remediation"):
            lines.append(f"       fix: {item['remediation']}")
    return "\n".join(lines)
