from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .config import CONFIG_PATH, load_config
from .writers import detect_writer

CheckRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]
Which = Callable[[str], Optional[str]]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def parse_github_remote(url: str) -> Optional[dict[str, str]]:
    value = (url or "").strip().rstrip("/")
    patterns = [
        r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        r"^ssh://git@(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        r"^git@(?P<host>[^:]+):(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            data = match.groupdict()
            return {"host": data["host"], "repository": f"{data['owner']}/{data['repo']}"}
    return None


def infer_github_repository(repo: Path, runner: CheckRunner = _run) -> Optional[dict[str, str]]:
    proc = runner(["git", "config", "--get", "remote.origin.url"], repo)
    if proc.returncode != 0:
        return None
    return parse_github_remote(proc.stdout.strip())


def _check(name: str, status: str, message: str, remediation: str = "", critical: bool = True) -> dict[str, Any]:
    return {"name": name, "status": status, "critical": critical, "message": message, "remediation": remediation}


def _resolve_command(command: str, which: Which) -> Optional[str]:
    path = which(command)
    if path:
        return path
    if "/" in command or "\\" in command:
        candidate = Path(command).expanduser()
        if candidate.exists():
            return str(candidate)
    return None


def _watcher_heartbeat_check(repo: Path, config: dict[str, Any], runner: CheckRunner, current_time: datetime) -> dict[str, Any]:
    proc = runner(["git", "rev-parse", "--git-path", "agent-bridge/watcher.json"], repo)
    if proc.returncode != 0 or not proc.stdout.strip():
        return _check("codex_watcher", "fail", "cannot resolve Git-private watcher state", "start `agent-bridge watch` under a persistent user service")
    path = Path(proc.stdout.strip())
    if not path.is_absolute():
        path = (repo / path).resolve()
    if not path.exists():
        return _check("codex_watcher", "fail", "no long-running Codex watcher heartbeat has been recorded", "start `agent-bridge watch` under a persistent user service")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        raw = state.get("last_poll_at")
        heartbeat = datetime.fromisoformat(raw) if isinstance(raw, str) and raw else None
        if heartbeat and heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        heartbeat = None
    if heartbeat is None:
        return _check("codex_watcher", "fail", "watcher state has no valid heartbeat", "restart `agent-bridge watch`")
    threshold = max(int(config["automation"].get("watch_interval_seconds", 30)) * 3, 120)
    delta_seconds = int((current_time - heartbeat.astimezone(timezone.utc)).total_seconds())
    if delta_seconds < -threshold:
        return _check("codex_watcher", "fail", f"Codex watcher heartbeat is implausibly in the future ({-delta_seconds}s)", "synchronize the reviewer machine clock and restart the watcher")
    healthy = delta_seconds <= threshold
    age_seconds = max(0, delta_seconds)
    return _check(
        "codex_watcher",
        "pass" if healthy else "fail",
        f"Codex watcher heartbeat is {age_seconds}s old" if healthy else f"Codex watcher heartbeat is stale ({age_seconds}s old; threshold {threshold}s)",
        "restart `agent-bridge watch` under a persistent user service",
    )


def _implementation_checks(repo: Path, config: dict[str, Any], *, runner: CheckRunner, which: Which) -> list[dict[str, Any]]:
    value = config["implementation"]
    backend = value.get("backend")
    command = str(value.get("command") or "").strip()
    model = str(value.get("model") or "").strip()
    checks: list[dict[str, Any]] = []

    configured = backend in {"chatgpt-web", "service-account"} and bool(command and model)
    checks.append(_check(
        "implementation_backend", "pass" if configured else "fail",
        f"implementation backend={backend} model={model}" if configured else "implementation backend/model is not fully configured",
        "run `agent-bridge setup implementation --backend ... --model ...`",
    ))

    executable = _resolve_command(command, which) if command else None
    runnable = False
    if executable:
        proc = runner([executable, "--version"], repo)
        runnable = proc.returncode == 0
    checks.append(_check(
        "implementation_command", "pass" if runnable else "fail",
        f"implementation command is runnable: {command}" if runnable else f"implementation command is unavailable: {command or '(empty)'}",
        "install/configure the Codex harness command",
    ))

    route_ok = bool(model)
    if backend == "chatgpt-web":
        route_ok = bool(re.fullmatch(r"chatgpt-web/[A-Za-z0-9._-]+", model))
    if runnable and route_ok:
        probe = runner([executable or command, "exec", "--model", model, "--sandbox", "read-only", "--help"], repo)
        route_ok = probe.returncode == 0
    checks.append(_check(
        "implementation_model_route", "pass" if route_ok and runnable else "fail",
        f"configured model route is accepted by the harness: {model}" if route_ok and runnable else f"model route is missing or invalid for backend {backend}",
        "configure a real installed model route, e.g. chatgpt-web/high only when that route exists locally",
    ))

    full = value.get("tool_mode") == "full"
    checks.append(_check(
        "implementation_tools", "pass" if full else "fail",
        "full/tunnel tool mode is configured" if full else "browser-only exposes model output but no coding/GitHub tools",
        "configure implementation.tool_mode=full; browser-only is never implementation-ready",
    ))

    writable = value.get("sandbox") in {"workspace-write", "danger-full-access"}
    checks.append(_check(
        "implementation_sandbox", "pass" if writable else "fail",
        f"implementation sandbox permits writes: {value.get('sandbox')}" if writable else "implementation sandbox is read-only",
        "configure workspace-write (preferred) or an explicitly authorized stronger sandbox",
    ))

    zero_personal = bool(value.get("zero_personal_plus"))
    credential_env = value.get("credential_env")
    if backend == "chatgpt-web":
        billing_ok = not zero_personal
        billing_message = "chatgpt-web personal-Web-account billing was explicitly allowed" if billing_ok else "chatgpt-web uses the currently logged-in Web account and is forbidden by zero_personal_plus"
    else:
        billing_ok = bool(zero_personal and isinstance(credential_env, str) and credential_env and os.environ.get(credential_env))
        billing_message = f"independent service-account credential is present via {credential_env}" if billing_ok else "service-account backend requires zero_personal_plus and a present credential environment variable"
    checks.append(_check(
        "implementation_billing", "pass" if billing_ok else "fail", billing_message,
        "for zero personal Plus usage select service-account and configure only the credential environment-variable name",
    ))
    return checks


def _review_checks(repo: Path, config: dict[str, Any], *, runner: CheckRunner, which: Which) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    reviewer_ok = config["workflow"].get("reviewer") == "codex"
    checks.append(_check(
        "reviewer_role", "pass" if reviewer_ok else "fail",
        "local Codex remains the exact-head reviewer" if reviewer_ok else "reviewer is not Codex",
        "set workflow.reviewer=codex",
    ))

    review = config["review"]
    command = str(review.get("codex_command") or "codex")
    executable = _resolve_command(command, which)
    runnable = False
    if executable:
        proc = runner([executable, "--version"], repo)
        runnable = proc.returncode == 0
    checks.append(_check(
        "codex_cli", "pass" if runnable else "fail",
        "Codex CLI is available for exact-head review" if runnable else f"Codex CLI is unavailable: {command}",
        "install Codex CLI or configure review.codex_command",
    ))

    zero_personal = bool(review.get("zero_personal_plus"))
    credential_env = review.get("credential_env")
    if zero_personal:
        auth_ok = bool(isinstance(credential_env, str) and credential_env and os.environ.get(credential_env) and str(review.get("model") or "").strip())
        message = f"review uses an environment-backed independently billed credential: {credential_env}" if auth_ok else "zero-personal review requires review.model plus a present credential environment variable"
    else:
        auth_ok = False
        if runnable:
            login = runner([executable or command, "login", "status"], repo)
            auth_ok = login.returncode == 0
        message = "Codex reviewer authentication is available; personal subscription use is explicitly allowed" if auth_ok else "Codex reviewer authentication is unavailable"
    checks.append(_check(
        "codex_auth", "pass" if auth_ok else "fail", message,
        "configure review credential_env/model for independent billing, or explicitly allow personal subscription usage",
    ))
    return checks


def doctor_report(repo: Path, *, runner: CheckRunner = _run, which: Which = shutil.which, now: Optional[datetime] = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    config = load_config(repo)
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    initialized = (repo / ".ai/state/tasks.json").exists() and (repo / CONFIG_PATH).exists()
    checks.append(_check("bridge_initialized", "pass" if initialized else "fail", "bridge state and config are initialized" if initialized else "bridge state/config are not fully initialized", "run `agent-bridge init` or `agent-bridge setup bootstrap`"))

    origin = infer_github_repository(repo, runner=runner)
    if not origin:
        repository, host = None, None
        checks.append(_check("github_origin", "fail", "origin is missing or is not a recognized GitHub remote", "configure remote origin using a github.com repository URL"))
    else:
        repository, host = origin["repository"], origin["host"]
        supported = host.lower() == "github.com"
        checks.append(_check("github_origin", "pass" if supported else "fail", f"origin resolves to {host}/{repository}", "use github.com for the built-in GitHub transport"))

    gh_path = which("gh")
    gh_authenticated = False
    if gh_path:
        auth = runner([gh_path, "auth", "status", "-h", "github.com"], repo)
        gh_authenticated = auth.returncode == 0
    checks.append(_check("github_cli", "pass" if gh_path and gh_authenticated else "fail", "GitHub CLI is installed and authenticated" if gh_path and gh_authenticated else "GitHub CLI authentication is unavailable", "install gh and authenticate it for github.com"))

    repo_access = False
    if gh_path and gh_authenticated and repository and host and host.lower() == "github.com":
        access = runner([gh_path, "repo", "view", repository, "--json", "nameWithOwner"], repo)
        repo_access = access.returncode == 0
    checks.append(_check("github_repo_access", "pass" if repo_access else "fail", f"GitHub CLI can access {repository}" if repo_access else f"GitHub CLI cannot verify {repository or '(unknown repository)'}", "grant the authenticated identity repository access"))

    checks.extend(_implementation_checks(repo, config, runner=runner, which=which))
    checks.extend(_review_checks(repo, config, runner=runner, which=which))

    writer = detect_writer(repo)
    if config["implementation"].get("tool_mode") == "browser-only":
        writer_status = False
        writer_message = "browser-only cannot become implementation-ready merely because a writer is configured"
    else:
        writer_status = True
        writer_message = "full/tunnel implementation owns coding/GitHub tool execution; host writer is optional"
    checks.append(_check("implementation_writer_boundary", "pass" if writer_status else "fail", writer_message, "use full/tunnel mode; a host writer may assist but cannot turn browser-only into a coding backend"))

    repositories = list(config["github"].get("repositories") or [])
    allowlisted = bool(repository and repository in repositories)
    checks.append(_check("repository_allowlist", "pass" if allowlisted else "fail", f"current repository {repository} is allowlisted" if allowlisted else f"current repository {repository or '(unknown)'} is not allowlisted", "rerun bootstrap with --repository owner/name"))

    commands = list(config["review"].get("test_commands") or [])
    require_tests = bool(config["review"].get("require_tests_for_approval", True))
    tests_ready = bool(commands) or not require_tests
    checks.append(_check("review_test_policy", "pass" if tests_ready else "fail", f"{len(commands)} authoritative local test command(s) configured" if commands else "no local test commands configured", "configure trusted local test commands or explicitly allow no-tests"))

    prefix = str(config["automation"].get("implementation_branch_prefix") or "")
    prefix_safe = bool(prefix and prefix.endswith("/") and re.fullmatch(r"[A-Za-z0-9._/-]+", prefix))
    checks.append(_check("implementation_branch_policy", "pass" if prefix_safe else "fail", f"implementation branches are restricted to `{prefix}*`" if prefix_safe else "implementation branch prefix is missing or unsafe", "set automation.implementation_branch_prefix to a dedicated prefix such as ai/"))

    checks.append(_watcher_heartbeat_check(repo, config, runner, current_time))

    human_merge = bool(config["workflow"].get("human_merge_required", True))
    checks.append(_check("human_merge_gate", "pass" if human_merge else "warn", "final merge remains human-controlled" if human_merge else "automatic merge is enabled", "set workflow.human_merge_required=true", critical=False))

    zero_touch_ready = all(item["status"] == "pass" for item in checks if item["critical"])
    return {"schema_version": 1, "zero_touch_ready": zero_touch_ready, "repository": repository, "host": host, "writer": writer, "checks": checks}


def format_doctor_report(report: dict[str, Any]) -> str:
    labels = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [f"Zero-touch ready: {'YES' if report['zero_touch_ready'] else 'NO'}", ""]
    for item in report["checks"]:
        lines.append(f"[{labels[item['status']]}] {item['name']}: {item['message']}")
        if item["status"] != "pass" and item.get("remediation"):
            lines.append(f"       fix: {item['remediation']}")
    return "\n".join(lines)
