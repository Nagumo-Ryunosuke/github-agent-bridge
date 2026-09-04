"""Optional GitHub Writer MCP adapter.

Install with `pip install github-agent-bridge[mcp]` and expose this server through a
supported remote MCP deployment/tunnel. It deliberately does not expose merge,
secret, or repository-admin tools.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from typing import Any, Optional

from .security import scan_text


def _allowed_repositories() -> set[str]:
    raw = os.environ.get("AGENT_BRIDGE_ALLOWED_REPOS", "").strip()
    if not raw:
        raise RuntimeError(
            "AGENT_BRIDGE_ALLOWED_REPOS must be set for the MCP writer "
            "(comma-separated owner/repo values, or * for an explicit unrestricted deployment)"
        )
    return {item.strip() for item in raw.split(",") if item.strip()}


def _assert_repo_allowed(repo: str) -> None:
    allowed = _allowed_repositories()
    if "*" not in allowed and repo not in allowed:
        raise RuntimeError(f"repository is not allowed by MCP writer policy: {repo}")


def _safe_path(path: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError("path must be a safe repository-relative path")
    return path


def _assert_write_branch(branch: str) -> None:
    prefix = os.environ.get("AGENT_BRIDGE_BRANCH_PREFIX", "ai/")
    if not branch or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise ValueError("branch contains unsupported characters")
    if prefix and not branch.startswith(prefix):
        raise RuntimeError(f"writer branch must start with configured prefix {prefix}")


def _assert_safe_content(content: str) -> None:
    findings = scan_text(content)
    if findings:
        raise RuntimeError("refusing to write content with possible secrets: " + ", ".join(findings))


def _gh(*args: str, input_text: Optional[str] = None) -> str:
    proc = subprocess.run(
        ["gh", *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"gh {' '.join(args)} failed")
    return proc.stdout.strip()


def _repo_path(repo: str, suffix: str) -> str:
    if repo.count("/") != 1 or repo.startswith("/") or repo.endswith("/"):
        raise ValueError("repo must be owner/name")
    base = f"repos/{repo}"
    cleaned = suffix.lstrip("/")
    return f"{base}/{cleaned}" if cleaned else base


def get_repository(repo: str) -> dict[str, Any]:
    _assert_repo_allowed(repo)
    return json.loads(_gh("api", _repo_path(repo, "")))


def list_pull_request_comments(repo: str, number: int) -> list[dict[str, Any]]:
    _assert_repo_allowed(repo)
    # `gh api --paginate` prints one JSON document per page. `--slurp` wraps
    # those pages in an outer array so we can flatten them deterministically.
    pages = json.loads(_gh(
        "api",
        _repo_path(repo, f"issues/{number}/comments"),
        "--paginate",
        "--slurp",
    ))
    if not isinstance(pages, list):
        raise RuntimeError("unexpected GitHub comments response")
    flattened: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, list):
            raise RuntimeError("unexpected paginated GitHub comments response")
        flattened.extend(item for item in page if isinstance(item, dict))
    return flattened


def read_file(repo: str, path: str, ref: Optional[str] = None) -> dict[str, Any]:
    _assert_repo_allowed(repo)
    path = _safe_path(path)
    args = ["api", _repo_path(repo, f"contents/{path}"), "-H", "Accept: application/vnd.github+json"]
    if ref:
        args += ["-f", f"ref={ref}", "--method", "GET"]
    data = json.loads(_gh(*args))
    content = base64.b64decode(data["content"]).decode("utf-8")
    return {"path": path, "sha": data["sha"], "content": content}


def create_branch(repo: str, branch: str, base_sha: Optional[str] = None, base_ref: Optional[str] = None) -> dict[str, Any]:
    """Create a branch from an exact commit SHA (preferred) or a named base ref."""
    _assert_repo_allowed(repo)
    _assert_write_branch(branch)
    if bool(base_sha) == bool(base_ref):
        raise ValueError("provide exactly one of base_sha or base_ref")
    sha = base_sha
    if base_ref:
        base = json.loads(_gh("api", _repo_path(repo, f"git/ref/heads/{base_ref}")))
        sha = base["object"]["sha"]
    payload = json.dumps({"ref": f"refs/heads/{branch}", "sha": sha})
    out = _gh("api", _repo_path(repo, "git/refs"), "--method", "POST", "--input", "-", input_text=payload)
    return json.loads(out)


def write_file(repo: str, branch: str, path: str, content: str, message: str, current_sha: Optional[str] = None) -> dict[str, Any]:
    _assert_repo_allowed(repo)
    _assert_write_branch(branch)
    path = _safe_path(path)
    _assert_safe_content(content)
    payload: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if current_sha:
        payload["sha"] = current_sha
    out = _gh("api", _repo_path(repo, f"contents/{path}"), "--method", "PUT", "--input", "-", input_text=json.dumps(payload))
    return json.loads(out)


def commit_files(repo: str, branch: str, files: list[dict[str, Any]], message: str) -> dict[str, Any]:
    """Create one atomic commit containing multiple UTF-8 file writes/deletes."""
    _assert_repo_allowed(repo)
    _assert_write_branch(branch)
    ref = json.loads(_gh("api", _repo_path(repo, f"git/ref/heads/{branch}")))
    parent_sha = ref["object"]["sha"]
    parent = json.loads(_gh("api", _repo_path(repo, f"git/commits/{parent_sha}")))
    existing_tree = json.loads(_gh("api", _repo_path(repo, f"git/trees/{parent['tree']['sha']}?recursive=1")))
    existing_modes = {entry.get("path"): entry.get("mode") for entry in existing_tree.get("tree", []) if entry.get("type") == "blob"}
    tree_entries: list[dict[str, Any]] = []
    for item in files:
        path = item.get("path")
        path = _safe_path(path)
        if item.get("delete"):
            tree_entries.append({"path": path, "mode": existing_modes.get(path, "100644"), "type": "blob", "sha": None})
            continue
        content = item.get("content")
        if not isinstance(content, str):
            raise ValueError("file content must be UTF-8 text")
        _assert_safe_content(content)
        blob = json.loads(_gh(
            "api", _repo_path(repo, "git/blobs"), "--method", "POST", "--input", "-",
            input_text=json.dumps({"content": content, "encoding": "utf-8"}),
        ))
        mode = item.get("mode") or existing_modes.get(path) or "100644"
        if mode not in {"100644", "100755"}:
            raise ValueError("file mode must be 100644 or 100755")
        tree_entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob["sha"]})
    tree = json.loads(_gh(
        "api", _repo_path(repo, "git/trees"), "--method", "POST", "--input", "-",
        input_text=json.dumps({"base_tree": parent["tree"]["sha"], "tree": tree_entries}),
    ))
    commit = json.loads(_gh(
        "api", _repo_path(repo, "git/commits"), "--method", "POST", "--input", "-",
        input_text=json.dumps({"message": message, "tree": tree["sha"], "parents": [parent_sha]}),
    ))
    _gh(
        "api", _repo_path(repo, f"git/refs/heads/{branch}"), "--method", "PATCH", "--input", "-",
        input_text=json.dumps({"sha": commit["sha"], "force": False}),
    )
    return {"commit_sha": commit["sha"], "tree_sha": tree["sha"]}


def create_pull_request(repo: str, title: str, body: str, head: str, base: str, draft: bool = True) -> dict[str, Any]:
    _assert_repo_allowed(repo)
    _assert_write_branch(head)
    _assert_safe_content(title)
    _assert_safe_content(body)
    payload = json.dumps({"title": title, "body": body, "head": head, "base": base, "draft": draft})
    return json.loads(_gh("api", _repo_path(repo, "pulls"), "--method", "POST", "--input", "-", input_text=payload))


def update_pull_request(repo: str, number: int, body: Optional[str] = None, title: Optional[str] = None) -> dict[str, Any]:
    _assert_repo_allowed(repo)
    payload: dict[str, Any] = {}
    if body is not None:
        _assert_safe_content(body)
        payload["body"] = body
    if title is not None:
        _assert_safe_content(title)
        payload["title"] = title
    return json.loads(_gh("api", _repo_path(repo, f"pulls/{number}"), "--method", "PATCH", "--input", "-", input_text=json.dumps(payload)))


def comment_pull_request(repo: str, number: int, body: str) -> dict[str, Any]:
    _assert_repo_allowed(repo)
    _assert_safe_content(body)
    payload = json.dumps({"body": body})
    return json.loads(_gh("api", _repo_path(repo, f"issues/{number}/comments"), "--method", "POST", "--input", "-", input_text=payload))


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("MCP support is optional; install `github-agent-bridge[mcp]`") from exc

    mcp = FastMCP("github-agent-bridge-writer")
    mcp.tool()(get_repository)
    mcp.tool()(read_file)
    mcp.tool()(list_pull_request_comments)
    mcp.tool()(create_branch)
    mcp.tool()(write_file)
    mcp.tool()(commit_files)
    mcp.tool()(create_pull_request)
    mcp.tool()(update_pull_request)
    mcp.tool()(comment_pull_request)
    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
