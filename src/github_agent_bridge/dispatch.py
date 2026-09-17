from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .config import load_config
from .core import TASKS_DIR, get_task, now_iso
from .triggers import parse_implementation_marker, parse_task_marker


DISPATCH_STATE_VERSION = 1
RETRYABLE_RESPONSE_STATUSES = {"failed", "cancelled", "incomplete"}
MCP_ALLOWED_TOOLS = [
    "get_repository",
    "read_file",
    "list_pull_request_comments",
    "create_branch",
    "write_file",
    "commit_files",
    "create_pull_request",
    "update_pull_request",
    "comment_pull_request",
]

ApiRequester = Callable[
    [str, str, Optional[dict[str, Any]], str, Optional[str], int],
    dict[str, Any],
]


class DispatchError(RuntimeError):
    pass


def dispatch_state_path(repo: Path) -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--git-path", "agent-bridge/dispatch.json"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise DispatchError("cannot resolve Git-private dispatch state")
    path = Path(proc.stdout.strip())
    return path if path.is_absolute() else (repo / path).resolve()


def load_dispatch_state(repo: Path) -> dict[str, Any]:
    path = dispatch_state_path(repo)
    if not path.exists():
        return {"schema_version": DISPATCH_STATE_VERSION, "tasks": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DispatchError(f"invalid Git-private dispatch state: {exc}") from exc
    if state.get("schema_version") != DISPATCH_STATE_VERSION or not isinstance(state.get("tasks"), dict):
        raise DispatchError("unsupported Git-private dispatch state")
    return state


def save_dispatch_state(repo: Path, state: dict[str, Any]) -> None:
    path = dispatch_state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _api_request(
    method: str,
    url: str,
    payload: Optional[dict[str, Any]],
    bearer_token: str,
    idempotency_key: Optional[str],
    timeout: int,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise DispatchError(f"OpenAI API request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DispatchError(f"OpenAI API request failed: {exc.reason}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DispatchError("OpenAI API returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise DispatchError("OpenAI API returned an unexpected response")
    return value


def _env_secret(environ: Mapping[str, str], env_name: str, label: str) -> str:
    value = environ.get(env_name, "").strip()
    if not value:
        raise DispatchError(f"{label} is missing; set environment variable {env_name}")
    return value


def _safe_error(exc: Exception, secrets: list[str]) -> str:
    text = str(exc)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[:500]


def _idempotency_key(*parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"agent-bridge-{digest}"


def _origin_url(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise DispatchError("origin remote URL is required for active dispatch")
    return proc.stdout.strip()


def _resolve_task_pr_url(repo: Path, task_id: str) -> str:
    branch = f"agent-bridge/{task_id.lower()}"
    proc = subprocess.run(
        ["gh", "pr", "view", branch, "--json", "url,state,body"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise DispatchError(f"cannot resolve open Task PR for {task_id}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise DispatchError(f"invalid GitHub Task PR response for {task_id}") from exc
    if str(data.get("state") or "").upper() != "OPEN":
        raise DispatchError(f"Task PR for {task_id} is not open")
    if parse_task_marker(data.get("body") or "") != task_id:
        raise DispatchError(f"Task PR marker does not match {task_id}")
    url = str(data.get("url") or "").strip()
    if not url:
        raise DispatchError(f"Task PR URL is missing for {task_id}")
    return url


def build_dispatch_prompt(
    repo: Path,
    task_id: str,
    *,
    task_pr_url: str,
    phase: str,
    reviewed_head: Optional[str] = None,
    implementation_pr_url: Optional[str] = None,
) -> str:
    if phase not in {"implement", "fix"}:
        raise DispatchError("dispatch phase must be implement or fix")
    if phase == "fix" and not reviewed_head:
        raise DispatchError("fix dispatch requires the exact reviewed head SHA")
    task = get_task(repo, task_id)
    task_path = repo / TASKS_DIR / f"{task_id}.md"
    if not task_path.exists():
        raise DispatchError(f"task contract is missing: {task_path}")
    task_body = task_path.read_text(encoding="utf-8")
    repository_url = _origin_url(repo)

    fix_context = ""
    if phase == "fix":
        fix_context = f"""
Revision context:
- Implementation PR: {implementation_pr_url or "resolve from GitHub using the task marker"}
- Codex reviewed head: {reviewed_head}

Only act on a REVISE marker whose task id is `{task_id}` and whose exact `head=` SHA is `{reviewed_head}`.
If the PR head has already changed, stop and report the stale review instead of applying it to a different commit.
"""

    return f"""You are the implementation agent for github-agent-bridge.

Dispatch payload:
- Repository URL: {repository_url}
- Task ID: {task_id}
- Task PR URL: {task_pr_url}
- Pinned base commit SHA: {task['base']['commit']}
- Pinned base branch: {task['base']['branch']}
- Target branch: {task['target_branch']}
- Phase: {phase}

Task contract:
--- begin task contract ---
{task_body.rstrip()}
--- end task contract ---
{fix_context}
Required behavior:
1. Read the Task PR, repository instructions, `.ai/context/*`, and current GitHub state.
2. Work from the exact pinned base commit. Do not silently rebase onto a newer base.
3. Implement only on `{task['target_branch']}` and create or update one same-repository Implementation PR.
4. The Implementation PR body must contain `<!-- agent-bridge:implementation task={task_id} -->`.
5. Run appropriate tests and self-review the exact diff before handoff.
6. Never merge the Implementation PR.
7. Do not write credentials to the repository, logs, PR text, or bridge state.
8. A completed chat is not proof of implementation completion. GitHub PR/branch facts are authoritative.
"""


def _dispatch_config(repo: Path) -> dict[str, Any]:
    config = load_config(repo)
    dispatch = config.get("dispatch")
    if not isinstance(dispatch, dict):
        raise DispatchError("dispatch configuration is missing")
    if dispatch.get("provider") != "openai":
        raise DispatchError("dispatch.provider must be openai")
    if dispatch.get("credential_kind") not in {"service-account", "workspace-agent"}:
        raise DispatchError("dispatch.credential_kind must be service-account or workspace-agent")
    if not str(dispatch.get("mcp_server_url") or "").startswith("https://"):
        raise DispatchError("dispatch.mcp_server_url must be an https:// URL")
    return dispatch


def _mcp_tool(dispatch: dict[str, Any], mcp_token: str) -> dict[str, Any]:
    authorization = mcp_token if mcp_token.lower().startswith("bearer ") else f"Bearer {mcp_token}"
    return {
        "type": "mcp",
        "server_label": "github_writer",
        "server_url": dispatch["mcp_server_url"],
        "authorization": authorization,
        "require_approval": "never",
        "allowed_tools": list(MCP_ALLOWED_TOOLS),
    }


def dispatch_task(
    repo: Path,
    task_id: str,
    *,
    phase: str = "implement",
    reviewed_head: Optional[str] = None,
    implementation_pr_url: Optional[str] = None,
    task_pr_url: Optional[str] = None,
    requester: ApiRequester = _api_request,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    dispatch = _dispatch_config(repo)
    env = os.environ if environ is None else environ
    api_key_env = str(dispatch.get("api_key_env") or "")
    mcp_token_env = str(dispatch.get("mcp_token_env") or "")
    api_key = _env_secret(env, api_key_env, "dispatch service credential")
    mcp_token = _env_secret(env, mcp_token_env, "GitHub writer MCP credential")
    secrets = [api_key, mcp_token]
    task = get_task(repo, task_id)
    repository_url = _origin_url(repo)
    task_pr = task_pr_url or _resolve_task_pr_url(repo, task_id)
    key = "implement"
    if phase == "fix":
        if not reviewed_head or not re.fullmatch(r"[0-9a-fA-F]{7,40}", reviewed_head):
            raise DispatchError("fix dispatch requires a valid exact reviewed head SHA")
        key = f"fix:{reviewed_head.lower()}"
    elif phase != "implement":
        raise DispatchError("dispatch phase must be implement or fix")

    state = load_dispatch_state(repo)
    task_state = state["tasks"].setdefault(
        task_id,
        {
            "repository_url": repository_url,
            "task_pr_url": task_pr,
            "base_commit": task["base"]["commit"],
            "target_branch": task["target_branch"],
            "conversation_id": None,
            "attempts": {},
            "implementation": None,
            "implementation_complete": False,
            "status": "pending",
        },
    )
    task_state.update(
        {
            "repository_url": repository_url,
            "task_pr_url": task_pr,
            "base_commit": task["base"]["commit"],
            "target_branch": task["target_branch"],
        }
    )
    attempts = task_state.setdefault("attempts", {})
    existing = attempts.get(key)
    if isinstance(existing, dict) and existing.get("response_id") and existing.get("status") not in RETRYABLE_RESPONSE_STATUSES:
        result = dict(task_state)
        result.update({"task_id": task_id, "dispatch_key": key, "reused": True})
        return result

    timeout = int(dispatch.get("timeout_seconds") or 60)
    api_base = str(dispatch.get("api_base") or "https://api.openai.com/v1").rstrip("/")
    conversation_id = task_state.get("conversation_id")
    try:
        if not conversation_id:
            conversation = requester(
                "POST",
                f"{api_base}/conversations",
                {"metadata": {"agent_bridge_task": task_id}},
                api_key,
                _idempotency_key(repository_url, task_id, "conversation"),
                timeout,
            )
            conversation_id = str(conversation.get("id") or "")
            if not conversation_id:
                raise DispatchError("conversation creation returned no id")
            task_state["conversation_id"] = conversation_id
            task_state["updated_at"] = now_iso()
            save_dispatch_state(repo, state)

        prompt = build_dispatch_prompt(
            repo,
            task_id,
            task_pr_url=task_pr,
            phase=phase,
            reviewed_head=reviewed_head,
            implementation_pr_url=implementation_pr_url,
        )
        payload = {
            "model": dispatch["model"],
            "conversation": conversation_id,
            "background": True,
            "store": True,
            "metadata": {
                "agent_bridge_task": task_id,
                "agent_bridge_phase": phase,
                "agent_bridge_dispatch_key": key,
            },
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "tools": [_mcp_tool(dispatch, mcp_token)],
        }
        response = requester(
            "POST",
            f"{api_base}/responses",
            payload,
            api_key,
            _idempotency_key(repository_url, task_id, key),
            timeout,
        )
        response_id = str(response.get("id") or "")
        if not response_id:
            raise DispatchError("response creation returned no id")
        attempts[key] = {
            "phase": phase,
            "reviewed_head": reviewed_head,
            "implementation_pr_url": implementation_pr_url,
            "response_id": response_id,
            "status": str(response.get("status") or "queued"),
            "dispatched_at": now_iso(),
            "error": None,
        }
        task_state["status"] = "dispatched"
        task_state["updated_at"] = now_iso()
        save_dispatch_state(repo, state)
    except Exception as exc:
        error = _safe_error(exc, secrets)
        attempts[key] = {
            "phase": phase,
            "reviewed_head": reviewed_head,
            "implementation_pr_url": implementation_pr_url,
            "response_id": None,
            "status": "failed",
            "dispatched_at": now_iso(),
            "error": error,
        }
        task_state["status"] = "dispatch_failed"
        task_state["updated_at"] = now_iso()
        save_dispatch_state(repo, state)
        if isinstance(exc, DispatchError):
            raise DispatchError(error) from exc
        raise DispatchError(error) from exc

    result = dict(task_state)
    result.update({"task_id": task_id, "dispatch_key": key, "reused": False})
    return result


def list_implementation_prs(repo: Path) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--json",
            "number,body,headRefOid,headRefName,baseRefName,url,isCrossRepository",
        ],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise DispatchError("cannot query Implementation PRs from GitHub")
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise DispatchError("GitHub returned invalid Implementation PR data") from exc
    return [item for item in data if isinstance(item, dict)]


def verify_implementation_pr(
    repo: Path,
    task_id: str,
    *,
    prs: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    task = get_task(repo, task_id)
    expected_branch = str(task.get("target_branch") or "")
    expected_base = str((task.get("base") or {}).get("branch") or "")
    recorded = task.get("implementation") or {}
    trusted: list[dict[str, Any]] = []

    for pr in prs if prs is not None else list_implementation_prs(repo):
        if pr.get("isCrossRepository"):
            continue
        if parse_implementation_marker(pr.get("body") or "") != task_id:
            continue
        if str(pr.get("headRefName") or "") != expected_branch:
            continue
        if str(pr.get("baseRefName") or "") != expected_base:
            continue
        head_sha = str(pr.get("headRefOid") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
            continue
        if recorded.get("pr") is not None and int(pr.get("number") or 0) != int(recorded["pr"]):
            continue
        if recorded.get("commit") and head_sha.lower() != str(recorded["commit"]).lower():
            continue
        trusted.append(
            {
                "pr": int(pr["number"]),
                "url": str(pr.get("url") or ""),
                "branch": expected_branch,
                "head_sha": head_sha.lower(),
                "marker_task_id": task_id,
                "verified_at": now_iso(),
            }
        )

    if len(trusted) > 1:
        raise DispatchError(f"multiple trusted Implementation PRs found for {task_id}")
    return trusted[0] if trusted else None


def refresh_dispatch_status(
    repo: Path,
    task_id: str,
    *,
    requester: ApiRequester = _api_request,
    environ: Optional[Mapping[str, str]] = None,
    prs: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    dispatch = _dispatch_config(repo)
    env = os.environ if environ is None else environ
    api_key_env = str(dispatch.get("api_key_env") or "")
    api_key = _env_secret(env, api_key_env, "dispatch service credential")
    timeout = int(dispatch.get("timeout_seconds") or 60)
    api_base = str(dispatch.get("api_base") or "https://api.openai.com/v1").rstrip("/")

    state = load_dispatch_state(repo)
    task_state = state["tasks"].get(task_id)
    if not isinstance(task_state, dict):
        raise DispatchError(f"no dispatch state for {task_id}")

    for attempt in task_state.get("attempts", {}).values():
        if not isinstance(attempt, dict) or not attempt.get("response_id"):
            continue
        response = requester(
            "GET",
            f"{api_base}/responses/{attempt['response_id']}",
            None,
            api_key,
            None,
            timeout,
        )
        attempt["status"] = str(response.get("status") or attempt.get("status") or "unknown")

    implementation = verify_implementation_pr(repo, task_id, prs=prs)
    task_state["implementation"] = implementation
    task_state["implementation_complete"] = bool(implementation)
    statuses = [
        str(item.get("status") or "")
        for item in task_state.get("attempts", {}).values()
        if isinstance(item, dict)
    ]
    if implementation:
        task_state["status"] = "implementation_ready"
    elif any(status == "completed" for status in statuses):
        task_state["status"] = "awaiting_implementation_pr"
    elif statuses and all(status in RETRYABLE_RESPONSE_STATUSES for status in statuses):
        task_state["status"] = "dispatch_failed"
    else:
        task_state["status"] = "dispatched"
    task_state["updated_at"] = now_iso()
    save_dispatch_state(repo, state)

    result = dict(task_state)
    result["task_id"] = task_id
    return result


def dispatch_status(repo: Path, task_id: Optional[str] = None) -> dict[str, Any]:
    state = load_dispatch_state(repo)
    if task_id is None:
        return state
    task_state = state["tasks"].get(task_id)
    if not isinstance(task_state, dict):
        raise DispatchError(f"no dispatch state for {task_id}")
    result = dict(task_state)
    result["task_id"] = task_id
    return result
