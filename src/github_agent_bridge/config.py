from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

CONFIG_PATH = Path(".ai/config.json")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LEGACY_WORK_TRIGGER_KEYS = {
    "work_trigger",
    "work_trigger_confirmed",
    "work_trigger_repositories",
}

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
    "dispatch": {
        "provider": "openai",
        "credential_kind": "service-account",
        "api_base": "https://api.openai.com/v1",
        "api_key_env": "AGENT_BRIDGE_OPENAI_API_KEY",
        "model": "gpt-5.6",
        "mcp_server_url": None,
        "mcp_token_env": "AGENT_BRIDGE_MCP_TOKEN",
        "timeout_seconds": 60,
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
        "api_key_env": "AGENT_BRIDGE_CODEX_API_KEY",
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


def _validate_env_name(value: str, label: str) -> str:
    name = value.strip()
    if not _ENV_NAME_RE.fullmatch(name):
        raise RuntimeError(f"{label} must be a valid environment variable name")
    return name


def load_config(repo: Path) -> dict[str, Any]:
    path = repo / CONFIG_PATH
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version", 1) != 1:
        raise RuntimeError("unsupported .ai/config.json schema_version")
    automation = raw.get("automation")
    if isinstance(automation, dict):
        legacy = sorted(_LEGACY_WORK_TRIGGER_KEYS.intersection(automation))
        if legacy:
            raise RuntimeError(
                "obsolete ChatGPT Work trigger configuration is not supported: "
                + ", ".join(legacy)
            )
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


def configure_dispatch(
    repo: Path,
    *,
    provider: Optional[str] = None,
    credential_kind: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key_env: Optional[str] = None,
    model: Optional[str] = None,
    mcp_server_url: Optional[str] = None,
    mcp_token_env: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> dict[str, Any]:
    config = load_config(repo)
    dispatch = config["dispatch"]

    if provider is not None:
        if provider != "openai":
            raise RuntimeError("dispatch provider must be openai")
        dispatch["provider"] = provider
    if credential_kind is not None:
        if credential_kind not in {"service-account", "workspace-agent"}:
            raise RuntimeError("credential kind must be service-account or workspace-agent")
        dispatch["credential_kind"] = credential_kind
    if api_base is not None:
        value = api_base.strip().rstrip("/")
        if not value.startswith("https://"):
            raise RuntimeError("dispatch API base must use https://")
        dispatch["api_base"] = value
    if api_key_env is not None:
        dispatch["api_key_env"] = _validate_env_name(api_key_env, "dispatch API key env")
    if model is not None:
        value = model.strip()
        if not value:
            raise RuntimeError("dispatch model must not be empty")
        dispatch["model"] = value
    if mcp_server_url is not None:
        value = mcp_server_url.strip()
        if not value.startswith("https://"):
            raise RuntimeError("dispatch MCP server URL must use https://")
        dispatch["mcp_server_url"] = value
    if mcp_token_env is not None:
        dispatch["mcp_token_env"] = _validate_env_name(mcp_token_env, "dispatch MCP token env")
    if timeout_seconds is not None:
        if timeout_seconds < 1:
            raise RuntimeError("dispatch timeout must be positive")
        dispatch["timeout_seconds"] = timeout_seconds

    save_config(repo, config)
    return config


def configure_review(
    repo: Path,
    *,
    test_commands: Optional[list[str]] = None,
    codex_command: Optional[str] = None,
    api_key_env: Optional[str] = None,
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
    if api_key_env is not None:
        review["api_key_env"] = _validate_env_name(api_key_env, "Codex API key env")
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
    codex_api_key_env: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    require_tests_for_approval: Optional[bool] = None,
    dispatch_api_key_env: Optional[str] = None,
    dispatch_model: Optional[str] = None,
    dispatch_mcp_server_url: Optional[str] = None,
    dispatch_mcp_token_env: Optional[str] = None,
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
    configure_dispatch(
        repo,
        api_key_env=dispatch_api_key_env,
        model=dispatch_model,
        mcp_server_url=dispatch_mcp_server_url,
        mcp_token_env=dispatch_mcp_token_env,
    )
    configure_review(
        repo,
        test_commands=test_commands,
        codex_command=codex_command,
        api_key_env=codex_api_key_env,
        timeout_seconds=timeout_seconds,
        require_tests_for_approval=require_tests_for_approval,
    )
    return load_config(repo)
