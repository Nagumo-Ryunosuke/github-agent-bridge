from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

CONFIG_PATH = Path(".ai/config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "workflow": {
        "dispatcher": "codex",
        "developer": "chatgpt",
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
    "automation": {
        "work_trigger": "github-pr",
        "work_trigger_confirmed": False,
        "work_trigger_repositories": [],
        "watch_interval_seconds": 30,
        "implementation_marker": "agent-bridge:implementation",
        "implementation_branch_prefix": "ai/",
        "task_marker": "agent-bridge:task",
    },
    "review": {
        "test_commands": [],
        "codex_command": "codex",
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


def load_config(repo: Path) -> dict[str, Any]:
    path = repo / CONFIG_PATH
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version", 1) != 1:
        raise RuntimeError("unsupported .ai/config.json schema_version")
    return _deep_merge(DEFAULT_CONFIG, raw)


def save_config(repo: Path, config: dict[str, Any]) -> Path:
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
    if scope_changed:
        config["automation"]["work_trigger_confirmed"] = False
        config["automation"]["work_trigger_repositories"] = []

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


def configure_review(
    repo: Path,
    *,
    test_commands: Optional[list[str]] = None,
    codex_command: Optional[str] = None,
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
    if timeout_seconds is not None:
        if timeout_seconds < 1:
            raise RuntimeError("review timeout must be positive")
        review["timeout_seconds"] = timeout_seconds
    if require_tests_for_approval is not None:
        review["require_tests_for_approval"] = bool(require_tests_for_approval)
    save_config(repo, config)
    return config


def configure_work_trigger(repo: Path, *, confirmed: bool) -> dict[str, Any]:
    config = load_config(repo)
    config["automation"]["work_trigger_confirmed"] = bool(confirmed)
    config["automation"]["work_trigger_repositories"] = list(config["github"].get("repositories") or []) if confirmed else []
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
    work_trigger_confirmed: Optional[bool] = None,
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
    if work_trigger_confirmed is not None:
        configure_work_trigger(repo, confirmed=work_trigger_confirmed)
    return load_config(repo)
