from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

CONFIG_PATH = Path(".ai/config.json")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "workflow": {
        "dispatcher": "codex",
        "developer": "chatgpt",
        "developer_surface": "codex-harness",
        "reviewer": "codex",
        "human_merge_required": True,
        "chatgpt_self_review": True,
    },
    "github": {
        "mode": "readonly",
        "repositories": [],
        "managed": {
            "connection_name": None,
            "write_confirmed": False,
            "unattended_confirmed": False,
        },
        "custom_mcp": {
            "server_name": None,
            "write_confirmed": False,
            "unattended_confirmed": False,
        },
    },
    "implementation": {
        "backend": None,
        "command": "codex",
        "model": None,
        "sandbox": "workspace-write",
        "tool_mode": "full",
        "timeout_seconds": 3600,
        "credential_env": None,
        "zero_personal_plus": True,
    },
    "automation": {
        "watch_interval_seconds": 30,
        "implementation_marker": "agent-bridge:implementation",
        "implementation_branch_prefix": "ai/",
        "task_marker": "agent-bridge:task",
    },
    "review": {
        "test_commands": [],
        "codex_command": "codex",
        "model": None,
        "credential_env": None,
        "zero_personal_plus": True,
        "timeout_seconds": 1800,
        "require_tests_for_approval": True,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _reject_legacy_work_config(raw: dict[str, Any]) -> None:
    automation = raw.get("automation")
    if not isinstance(automation, dict):
        return
    legacy = {"work", "work_trigger", "work_trigger_confirmed", "work_trigger_repositories"}
    present = sorted(legacy.intersection(automation))
    if present:
        raise RuntimeError(
            "legacy ChatGPT Work event configuration is unsupported; remove automation."
            + ", automation.".join(present)
        )


def load_config(repo: Path) -> dict[str, Any]:
    path = repo / CONFIG_PATH
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version", 1) != 1:
        raise RuntimeError("unsupported .ai/config.json schema_version")
    _reject_legacy_work_config(raw)
    return _deep_merge(DEFAULT_CONFIG, raw)


def save_config(repo: Path, config: dict[str, Any]) -> Path:
    _reject_legacy_work_config(config)
    path = repo / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _normalize_repositories(repositories: list[str]) -> list[str]:
    normalized: list[str] = []
    for repository in repositories:
        value = repository.strip()
        if not value or value.count("/") != 1:
            raise RuntimeError(f"repository must be owner/name: {repository}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _validate_env_name(value: Optional[str], *, field: str) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value or not _ENV_NAME_RE.fullmatch(value):
        raise RuntimeError(f"{field} must be an environment variable name, never a credential value")
    return value


def configure_writer(
    repo: Path,
    *,
    mode: str,
    connection_name: Optional[str] = None,
    mcp_server: Optional[str] = None,
    write_confirmed: Optional[bool] = None,
    unattended_confirmed: Optional[bool] = None,
    repositories: Optional[list[str]] = None,
) -> dict[str, Any]:
    if mode not in {"managed", "custom-mcp", "readonly"}:
        raise RuntimeError("writer mode must be managed, custom-mcp, or readonly")
    config = load_config(repo)
    github = config["github"]
    previous_mode = github["mode"]
    previous_repositories = list(github.get("repositories") or [])
    github["mode"] = mode

    scope_changed = False
    if repositories is not None:
        normalized = _normalize_repositories(repositories)
        scope_changed = normalized != previous_repositories
        github["repositories"] = normalized

    mode_changed = mode != previous_mode
    if mode == "managed":
        managed = github["managed"]
        previous_connection = managed.get("connection_name")
        if connection_name is not None:
            managed["connection_name"] = connection_name or "github-agent-bridge-writer"
        elif not managed.get("connection_name"):
            managed["connection_name"] = "github-agent-bridge-writer"
        backend_changed = managed.get("connection_name") != previous_connection
        if mode_changed or scope_changed or backend_changed:
            managed["write_confirmed"] = False
            managed["unattended_confirmed"] = False
        if write_confirmed is not None:
            managed["write_confirmed"] = bool(write_confirmed)
        if unattended_confirmed is not None:
            managed["unattended_confirmed"] = bool(unattended_confirmed)
    elif mode == "custom-mcp":
        mcp = github["custom_mcp"]
        previous_server = mcp.get("server_name")
        if mcp_server is not None:
            if not mcp_server:
                raise RuntimeError("custom-mcp mode requires --mcp-server")
            mcp["server_name"] = mcp_server
        elif not mcp.get("server_name"):
            raise RuntimeError("custom-mcp mode requires --mcp-server")
        backend_changed = mcp.get("server_name") != previous_server
        if mode_changed or scope_changed or backend_changed:
            mcp["write_confirmed"] = False
            mcp["unattended_confirmed"] = False
        if write_confirmed is not None:
            mcp["write_confirmed"] = bool(write_confirmed)
        if unattended_confirmed is not None:
            mcp["unattended_confirmed"] = bool(unattended_confirmed)
    save_config(repo, config)
    return config


def configure_implementation(
    repo: Path,
    *,
    backend: Optional[str] = None,
    command: Optional[str] = None,
    model: Optional[str] = None,
    sandbox: Optional[str] = None,
    tool_mode: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    credential_env: Optional[str] = None,
    zero_personal_plus: Optional[bool] = None,
) -> dict[str, Any]:
    config = load_config(repo)
    implementation = config["implementation"]
    if backend is not None:
        if backend not in {"chatgpt-web", "service-account"}:
            raise RuntimeError("implementation backend must be chatgpt-web or service-account")
        implementation["backend"] = backend
    if command is not None:
        if not command.strip():
            raise RuntimeError("implementation command must not be empty")
        implementation["command"] = command.strip()
    if model is not None:
        if not model.strip():
            raise RuntimeError("implementation model must not be empty")
        implementation["model"] = model.strip()
    if sandbox is not None:
        if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
            raise RuntimeError("implementation sandbox is invalid")
        implementation["sandbox"] = sandbox
    if tool_mode is not None:
        if tool_mode not in {"browser-only", "full"}:
            raise RuntimeError("implementation tool mode must be browser-only or full")
        implementation["tool_mode"] = tool_mode
    if timeout_seconds is not None:
        if timeout_seconds < 1:
            raise RuntimeError("implementation timeout must be positive")
        implementation["timeout_seconds"] = timeout_seconds
    if credential_env is not None:
        implementation["credential_env"] = _validate_env_name(
            credential_env or None, field="implementation credential_env"
        )
    if zero_personal_plus is not None:
        implementation["zero_personal_plus"] = bool(zero_personal_plus)
    if implementation.get("backend") == "service-account" and not implementation.get("credential_env"):
        raise RuntimeError("service-account implementation backend requires credential_env")
    save_config(repo, config)
    return config


def configure_review(
    repo: Path,
    *,
    test_commands: Optional[list[str]] = None,
    codex_command: Optional[str] = None,
    model: Optional[str] = None,
    credential_env: Optional[str] = None,
    zero_personal_plus: Optional[bool] = None,
    timeout_seconds: Optional[int] = None,
    require_tests_for_approval: Optional[bool] = None,
) -> dict[str, Any]:
    config = load_config(repo)
    review = config["review"]
    if test_commands is not None:
        review["test_commands"] = [command.strip() for command in test_commands if command.strip()]
    if codex_command is not None:
        if not codex_command.strip():
            raise RuntimeError("codex command must not be empty")
        review["codex_command"] = codex_command.strip()
    if model is not None:
        if not model.strip():
            raise RuntimeError("review model must not be empty")
        review["model"] = model.strip()
    if credential_env is not None:
        review["credential_env"] = _validate_env_name(
            credential_env or None, field="review credential_env"
        )
    if zero_personal_plus is not None:
        review["zero_personal_plus"] = bool(zero_personal_plus)
    if timeout_seconds is not None:
        if timeout_seconds < 1:
            raise RuntimeError("review timeout must be positive")
        review["timeout_seconds"] = timeout_seconds
    if require_tests_for_approval is not None:
        review["require_tests_for_approval"] = bool(require_tests_for_approval)
    save_config(repo, config)
    return config


def bootstrap_config(
    repo: Path,
    *,
    mode: str,
    repositories: Optional[list[str]] = None,
    connection_name: Optional[str] = None,
    mcp_server: Optional[str] = None,
    write_confirmed: Optional[bool] = None,
    unattended_confirmed: Optional[bool] = None,
    test_commands: Optional[list[str]] = None,
    codex_command: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    require_tests_for_approval: Optional[bool] = None,
) -> dict[str, Any]:
    configure_writer(
        repo,
        mode=mode,
        connection_name=connection_name,
        mcp_server=mcp_server,
        write_confirmed=write_confirmed,
        unattended_confirmed=unattended_confirmed,
        repositories=repositories,
    )
    configure_review(
        repo,
        test_commands=test_commands,
        codex_command=codex_command,
        timeout_seconds=timeout_seconds,
        require_tests_for_approval=require_tests_for_approval,
    )
    return load_config(repo)
