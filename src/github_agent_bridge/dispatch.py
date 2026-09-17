from __future__ import annotations

import hashlib, json, os, re, signal, subprocess, uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from .config import load_config
from .core import claim_task, finish_task, get_task, mark_self_reviewed, now_iso, start_task
from .git import run_git
from .security import scan_text
from .triggers import parse_implementation_marker

SHA = re.compile(r"^[0-9a-f]{40}$")


class DispatchError(RuntimeError):
    pass


def _private(repo: Path, name: str) -> Path:
    p = Path(run_git(repo, "rev-parse", "--git-path", f"agent-bridge/{name}"))
    return p if p.is_absolute() else (repo / p).resolve()


def _contract(repo: Path, task_id: str) -> str:
    p = repo / ".ai/tasks" / f"{task_id}.md"
    if not p.exists():
        raise DispatchError(f"missing task contract: {p}")
    return p.read_text(encoding="utf-8")


def _phase(phase: str, head: Optional[str]) -> None:
    if phase not in {"implement", "fix"}:
        raise DispatchError("phase must be implement or fix")
    if phase == "fix" and (not head or not SHA.fullmatch(head)):
        raise DispatchError("fix requires an exact 40-character head SHA")
    if phase == "implement" and head is not None:
        raise DispatchError("--head is only valid for fix")


def dispatch_key(repo: Path, task_id: str, phase: str, head: Optional[str]) -> str:
    _phase(phase, head)
    task = get_task(repo, task_id)
    identity = {
        "namespace": "github-agent-bridge/dispatch/v1",
        "repo": run_git(repo, "config", "--get", "remote.origin.url"),
        "task": task_id,
        "base": task["base"]["commit"],
        "phase": phase,
        "head": head,
        "target": task["target_branch"],
        "contract": hashlib.sha256(_contract(repo, task_id).encode()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _path(repo: Path, key: str) -> Path:
    return _private(repo, "runs") / f"{key}.json"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex)
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    lock = path.with_suffix(".lock")
    try:
        lock.mkdir(parents=True)
    except FileExistsError as exc:
        raise DispatchError("dispatch is owned by another process") from exc
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def _backend(repo: Path) -> dict[str, Any]:
    cfg = dict(load_config(repo).get("implementation") or {})
    if cfg.get("backend") not in {"chatgpt-web", "service-account"}:
        raise DispatchError("implementation backend is not configured")
    if not str(cfg.get("command") or "").strip() or not str(cfg.get("model") or "").strip():
        raise DispatchError("implementation command/model must be explicit")
    if cfg.get("tool_mode") != "full":
        raise DispatchError("browser-only has no coding tools; full/tunnel mode is required")
    if cfg.get("sandbox") == "read-only":
        raise DispatchError("implementation sandbox must permit writes")
    if cfg.get("zero_personal_plus") and cfg["backend"] == "chatgpt-web":
        raise DispatchError("zero_personal_plus=true forbids the logged-in chatgpt-web backend")
    env_name = cfg.get("credential_env")
    if cfg["backend"] == "service-account" and (
        not isinstance(env_name, str) or not env_name or not os.environ.get(env_name)
    ):
        raise DispatchError("service-account credential environment variable is missing")
    if int(cfg.get("timeout_seconds") or 0) < 1:
        raise DispatchError("implementation timeout must be positive")
    return cfg


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def resolve_task_pr(repo: Path, task_id: str,
                    runner: Callable[[list[str], Path], subprocess.CompletedProcess[str]] = _run
                    ) -> dict[str, Any]:
    branch = f"agent-bridge/{task_id.lower()}"
    p = runner(["gh", "pr", "view", branch, "--json", "number,url,state,headRefName"], repo)
    if p.returncode:
        raise DispatchError("Task PR is required before dispatch")
    value = json.loads(p.stdout)
    if str(value.get("state") or "").upper() != "OPEN" or value.get("headRefName") != branch:
        raise DispatchError("Task PR is not open on the deterministic task branch")
    return value


def prepare_dispatch(repo: Path, task_id: str, *, phase: str = "implement",
                     head: Optional[str] = None, retry: bool = False,
                     task_pr_resolver: Callable[..., dict[str, Any]] = resolve_task_pr
                     ) -> dict[str, Any]:
    key = dispatch_key(repo, task_id, phase, head)
    task, backend = get_task(repo, task_id), _backend(repo)
    if task.get("reviewer") != "codex":
        raise DispatchError("implementation dispatch requires reviewer=codex")
    task_pr, path = task_pr_resolver(repo, task_id), _path(repo, key)
    with _lock(path):
        old = _read(path) if path.exists() else None
        if old and not retry:
            return old
        if old and old["status"] == "running":
            raise DispatchError("running dispatch cannot be retried")
        history = list(old.get("history") or []) if old else []
        if old:
            history.append({k: old.get(k) for k in ("turn_id", "attempt", "status", "pr_url", "output_sha")})
        state = {
            "schema_version": 1, "idempotency_key": key, "conversation_key": key,
            "turn_id": "turn_" + uuid.uuid4().hex, "attempt": int(old.get("attempt", 0)) + 1 if old else 1,
            "task_id": task_id, "phase": phase, "status": "prepared",
            "repository": run_git(repo, "config", "--get", "remote.origin.url"),
            "task_pr_url": task_pr["url"], "task_pr_number": task_pr["number"],
            "base_sha": task["base"]["commit"], "base_branch": task["base"]["branch"],
            "input_head": head, "target_branch": task["target_branch"],
            "backend": backend["backend"], "model": backend["model"], "sandbox": backend["sandbox"],
            "tool_mode": backend["tool_mode"], "credential_env": backend.get("credential_env"),
            "zero_personal_plus": bool(backend.get("zero_personal_plus")),
            "prepared_at": now_iso(), "started_at": None, "finished_at": None, "pid": None,
            "worktree": None, "pr_url": None, "pr_number": None, "output_sha": None,
            "output_summary": None, "error": None, "history": history,
        }
        _write(path, state)
        return state


def dispatch_status(repo: Path, task_id: str, *, phase: str = "implement",
                    head: Optional[str] = None) -> dict[str, Any]:
    path = _path(repo, dispatch_key(repo, task_id, phase, head))
    if not path.exists():
        raise DispatchError("no dispatch state for this task/phase/context")
    return _read(path)


def _advance(repo: Path, task_id: str) -> None:
    status = get_task(repo, task_id)["status"]
    if status == "ready":
        claim_task(repo, task_id, "chatgpt"); start_task(repo, task_id)
    elif status in {"claimed", "changes_requested", "blocked"}:
        start_task(repo, task_id)
    elif status != "in_progress":
        raise DispatchError(f"task status {status} cannot dispatch")


def _worktree(repo: Path, state: dict[str, Any]) -> Path:
    root = _private(repo, "worktrees") / state["idempotency_key"][:16]
    root.mkdir(parents=True, exist_ok=True)
    path = root / state["turn_id"]
    run_git(repo, "worktree", "add", "--detach", str(path), state["input_head"] or state["base_sha"])
    run_git(path, "switch", "-c", f"agent-bridge-run/{state['turn_id'][5:17]}")
    return path


def _prompt(repo: Path, state: dict[str, Any]) -> str:
    marker = (f"<!-- agent-bridge:implementation task={state['task_id']} "
              f"base={state['base_sha']} head=<FINAL_40_HEX_SHA> -->")
    text = f"""You are the implementation worker.
Repository: {state['repository']}
Task ID: {state['task_id']}
Task PR: {state['task_pr_url']}
Pinned base: {state['base_branch']}@{state['base_sha']}
Phase: {state['phase']}
Input head: {state['input_head'] or 'none'}
Target branch: {state['target_branch']}
Required Implementation PR marker: {marker}
Turn ID: {state['turn_id']}
Conversation key: {state['conversation_key']}

Use only this isolated worktree. Implement, test, self-review, commit, push HEAD to the exact target
branch, and create/update one same-repository Implementation PR against the pinned base. Put the
required marker with the final exact HEAD SHA in its body. Never merge. Do not use Work/PR/comment
events for dispatch. Never put credentials in prompts, files, logs, state, commits or PR text.
If tools or GitHub writes cannot be verified, fail instead of claiming completion.

Task contract:
{_contract(repo, state['task_id'])}
"""
    if scan_text(text):
        raise DispatchError("prompt contains possible secrets")
    return text


def verify_implementation_pr(repo: Path, *, task_id: str, target_branch: str,
                             base_branch: str, base_sha: str,
                             runner: Callable[[list[str], Path], subprocess.CompletedProcess[str]] = _run
                             ) -> dict[str, Any]:
    p = runner(["gh", "pr", "list", "--state", "open", "--head", target_branch, "--json",
                "number,url,body,headRefOid,headRefName,baseRefName,isCrossRepository"], repo)
    if p.returncode:
        raise DispatchError("cannot query Implementation PR")
    matches = [x for x in json.loads(p.stdout or "[]")
               if not x.get("isCrossRepository") and x.get("headRefName") == target_branch
               and x.get("baseRefName") == base_branch]
    if len(matches) != 1:
        raise DispatchError("expected exactly one open same-repository Implementation PR")
    pr, head = matches[0], str(matches[0].get("headRefOid") or "")
    expected = {"task_id": task_id, "base_sha": base_sha, "head_sha": head}
    if not SHA.fullmatch(head) or parse_implementation_marker(pr.get("body") or "") != expected:
        raise DispatchError("Implementation PR marker/task/base/head mismatch")
    remote = runner(["git", "ls-remote", "--heads", "origin", target_branch], repo)
    if remote.returncode or not remote.stdout.strip() or remote.stdout.split()[0] != head:
        raise DispatchError("remote branch/PR head mismatch")
    return {"pr_number": int(pr["number"]), "pr_url": pr["url"], "output_sha": head}


def _cleanup(repo: Path, state: dict[str, Any]) -> None:
    if state.get("worktree"):
        run_git(repo, "worktree", "remove", "--force", state["worktree"], check=False)


def dispatch_task(repo: Path, task_id: str, *, phase: str = "implement",
                  head: Optional[str] = None, retry: bool = False,
                  process_factory: Callable[..., Any] = subprocess.Popen,
                  verifier: Callable[..., dict[str, Any]] = verify_implementation_pr,
                  task_pr_resolver: Callable[..., dict[str, Any]] = resolve_task_pr
                  ) -> dict[str, Any]:
    state = prepare_dispatch(repo, task_id, phase=phase, head=head, retry=retry,
                             task_pr_resolver=task_pr_resolver)
    if state["status"] != "prepared":
        return state
    path, backend = _path(repo, state["idempotency_key"]), _backend(repo)
    _advance(repo, task_id)
    with _lock(path):
        state = _read(path)
        worktree = _worktree(repo, state)
        output = path.with_name(state["turn_id"] + ".txt")
        cmd = [str(backend["command"]), "exec", "--model", str(backend["model"]),
               "--sandbox", str(backend["sandbox"]), "--output-last-message", str(output), _prompt(repo, state)]
        proc = process_factory(cmd, cwd=worktree, text=True, encoding="utf-8", errors="replace",
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        state.update(status="running", pid=int(proc.pid), started_at=now_iso(), worktree=str(worktree))
        _write(path, state)
    try:
        stdout, stderr = proc.communicate(timeout=int(backend["timeout_seconds"]))
    except subprocess.TimeoutExpired:
        proc.kill(); proc.communicate()
        state = _read(path)
        if state["status"] != "cancelled":
            state.update(status="failed", finished_at=now_iso(), error="implementation backend timed out")
            _write(path, state)
        _cleanup(repo, state)
        return _read(path)
    state = _read(path)
    if state["status"] == "cancelled":
        _cleanup(repo, state); return state
    if proc.returncode:
        detail = (stderr or stdout or "").strip()[-2000:]
        state.update(status="failed", finished_at=now_iso(),
                     error="[redacted]" if scan_text(detail) else f"backend exited {proc.returncode}: {detail}")
        _write(path, state); _cleanup(repo, state); return state
    try:
        final = output.read_text(encoding="utf-8")
    except OSError:
        final = ""
    try:
        output.unlink()
    except OSError:
        pass
    state["output_summary"] = "[redacted]" if scan_text(final) else (final.strip()[-4000:] or "completed")
    try:
        verified = verifier(repo, task_id=task_id, target_branch=state["target_branch"],
                            base_branch=state["base_branch"], base_sha=state["base_sha"])
        state.update(status="implemented", finished_at=now_iso(), error=None, **verified)
        _write(path, state)
        mark_self_reviewed(repo, task_id, agent="chatgpt")
        finish_task(repo, task_id, implementation_commit=verified["output_sha"],
                    branch=state["target_branch"], pr=verified["pr_number"],
                    summary=state["output_summary"], agent="chatgpt")
    except Exception as exc:
        detail = str(exc)
        state.update(status="failed", finished_at=now_iso(),
                     error="[redacted]" if scan_text(detail) else detail)
        _write(path, state)
    finally:
        _cleanup(repo, state)
    return _read(path)


def cancel_dispatch(repo: Path, task_id: str, *, phase: str, head: Optional[str],
                    turn_id: str) -> dict[str, Any]:
    state = dispatch_status(repo, task_id, phase=phase, head=head)
    path = _path(repo, state["idempotency_key"])
    with _lock(path):
        state = _read(path)
        if state["turn_id"] != turn_id:
            raise DispatchError("turn id does not match active dispatch")
        if state["status"] == "cancelled":
            return state
        if state["status"] != "running":
            raise DispatchError(f"cannot cancel state {state['status']}")
        pid = state.get("pid")
        if not isinstance(pid, int) or pid < 1:
            raise DispatchError("running dispatch has no valid pid")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        state.update(status="cancelled", finished_at=now_iso(), error="cancelled by exact turn id")
        _write(path, state)
        return state
