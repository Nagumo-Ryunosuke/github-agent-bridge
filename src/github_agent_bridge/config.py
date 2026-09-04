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


def configure_writer(
    repo: Path,
    *,
    mode: str,
    connection_name: Optional[str] = None,
    mcp_server: Optional[str] = None,
    write_confirmed: bool = False,
    unattended_confirmed: bool = False,
    repositories: Optional[list[str]] = None,
) -> dict[str, Any]:
    if mode not in {"managed", "custom-mcp", "readonly"}:
        raise RuntimeError("writer mode must be managed, custom-mcp, or readonly")
    config = load_config(repo)
    config["github"]["mode"] = mode
    if repositories is not None:
        normalized = []
        for repository in repositories:
            value = repository.strip()
            if not value or value.count("/") != 1:
                raise RuntimeError(f"repository must be owner/name: {repository}")
            if value not in normalized:
                normalized.append(value)
        config["github"]["repositories"] = normalized
    if mode == "managed":
        config["github"]["managed"]["connection_name"] = connection_name or "github-agent-bridge-writer"
        config["github"]["managed"]["write_confirmed"] = bool(write_confirmed)
        config["github"]["managed"]["unattended_confirmed"] = bool(unattended_confirmed)
    elif mode == "custom-mcp":
        if not mcp_server:
            raise RuntimeError("custom-mcp mode requires --mcp-server")
        config["github"]["custom_mcp"]["server_name"] = mcp_server
        config["github"]["custom_mcp"]["write_confirmed"] = bool(write_confirmed)
        config["github"]["custom_mcp"]["unattended_confirmed"] = bool(unattended_confirmed)
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
    save_config(repo, config)
    return config


def bootstrap_config(
    repo: Path,
    *,
    mode: str,
    repositories: Optional[list[str]] = None,
    connection_name: Optional[str] = None,
    mcp_server: Optional[str] = None,
    write_confirmed: bool = False,
    unattended_confirmed: bool = False,
    test_commands: Optional[list[str]] = None,
    codex_command: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    require_tests_for_approval: Optional[bool] = None,
    work_trigger_confirmed: bool = False,
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
    configure_work_trigger(repo, confirmed=work_trigger_confirmed)
    return load_config(repo)
