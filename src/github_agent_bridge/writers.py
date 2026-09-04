from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import load_config


@dataclass(frozen=True)
class WriterCapabilities:
    repository_read: bool
    contents_write: bool
    branch_write: bool
    pull_request_write: bool
    review_comment_write: bool
    merge: bool
    confirmation_may_be_required: bool

    @property
    def can_implement(self) -> bool:
        return self.contents_write and self.branch_write and self.pull_request_write


READONLY_CAPABILITIES = WriterCapabilities(
    repository_read=True,
    contents_write=False,
    branch_write=False,
    pull_request_write=False,
    review_comment_write=False,
    merge=False,
    confirmation_may_be_required=False,
)
WRITER_CAPABILITIES = WriterCapabilities(
    repository_read=True,
    contents_write=True,
    branch_write=True,
    pull_request_write=True,
    review_comment_write=True,
    merge=False,
    confirmation_may_be_required=True,
)


def detect_writer(repo: Path) -> dict[str, Any]:
    config = load_config(repo)
    github = config["github"]
    mode = github["mode"]
    reason = ""
    ready = False
    caps = READONLY_CAPABILITIES

    unattended = False
    if mode == "readonly":
        reason = "read-only mode intentionally disables GitHub writes"
    elif mode == "managed":
        managed = github["managed"]
        ready = bool(managed.get("connection_name") and managed.get("write_confirmed"))
        unattended = bool(ready and managed.get("unattended_confirmed"))
        caps = WRITER_CAPABILITIES if ready else READONLY_CAPABILITIES
        reason = (
            "managed writer connection is configured and write capability was confirmed"
            if ready
            else "managed mode requires a pre-connected write-capable GitHub app and explicit capability confirmation"
        )
    elif mode == "custom-mcp":
        mcp = github["custom_mcp"]
        ready = bool(mcp.get("server_name") and mcp.get("write_confirmed"))
        unattended = bool(ready and mcp.get("unattended_confirmed"))
        caps = WRITER_CAPABILITIES if ready else READONLY_CAPABILITIES
        reason = (
            "custom MCP writer is configured and write capability was confirmed"
            if ready
            else "custom-mcp mode requires a configured MCP server and explicit write-capability confirmation"
        )
    else:
        raise RuntimeError(f"unsupported github writer mode: {mode}")

    return {
        "mode": mode,
        "ready": ready,
        "reason": reason,
        "unattended_ready": unattended,
        "capabilities": asdict(caps),
    }


def require_implementation_writer(repo: Path) -> dict[str, Any]:
    status = detect_writer(repo)
    if not status["capabilities"]["contents_write"]:
        raise RuntimeError(
            f"GitHub writer is not ready ({status['mode']}): {status['reason']}. "
            "Configure `agent-bridge setup writer` before unattended ChatGPT implementation."
        )
    return status


def writer_contract() -> dict[str, Any]:
    """Stable semantic tool contract shared by managed and MCP backends."""
    return {
        "required_actions": [
            "get_repository",
            "read_file",
            "list_pull_request_comments",
            "create_branch",
            "commit_files",
            "create_pull_request",
            "update_pull_request",
            "comment_pull_request",
        ],
        "forbidden_by_default": [
            "merge_pull_request",
            "delete_repository",
            "modify_secrets",
            "modify_repository_admin_settings",
        ],
        "recommended_github_permissions": {
            "metadata": "read",
            "contents": "write",
            "pull_requests": "write",
            "issues": "write",
            "actions": "read",
        },
    }
