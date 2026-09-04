from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import load_config
from .git import run_git

CODEX_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "summary", "findings"],
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVE", "REVISE"]},
        "summary": {"type": "string"},
        "findings": {"type": "array"},
        "tests": {"type": "array"},
    },
}


class ReviewExecutionError(RuntimeError):
    pass


@dataclass
class ReviewResult:
    verdict: str
    summary: str
    findings: list[dict[str, Any]]
    tests: list[dict[str, Any]]

    def validate(self) -> None:
        if self.verdict not in {"APPROVE", "REVISE"}:
            raise ReviewExecutionError("review verdict must be APPROVE or REVISE")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ReviewExecutionError("review summary must be non-empty")
        if not isinstance(self.findings, list) or not isinstance(self.tests, list):
            raise ReviewExecutionError("review findings/tests must be arrays")
        for finding in self.findings:
            if finding.get("severity") not in {"critical", "major", "minor"}:
                raise ReviewExecutionError("finding severity must be critical/major/minor")
            if not finding.get("title") or not finding.get("detail"):
                raise ReviewExecutionError("finding requires title and detail")


def _run(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def ensure_base_is_ancestor(repo: Path, base_commit: str, head_ref: str) -> None:
    """Reject implementation heads that are not descendants of the pinned task base.

    The local reviewer executes PR code, so the branch-prefix and same-repository
    checks in the watcher are not sufficient by themselves. The implementation
    must also preserve the exact task ancestry contract before any PR test command
    or Codex tool is executed.
    """
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, head_ref],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise ReviewExecutionError(
            f"implementation head {head_ref} is not a descendant of pinned base {base_commit}{suffix}"
        )


def run_test_commands(worktree: Path, commands: list[str], timeout: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in commands:
        try:
            proc = subprocess.run(command, cwd=worktree, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
            results.append({"command": command, "exit_code": proc.returncode, "output": proc.stdout[-8000:]})
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            results.append({"command": command, "exit_code": 124, "output": (output + "\nTIMEOUT")[-8000:]})
    return results


def build_review_prompt(task_id: str, base_commit: str, test_results: list[dict[str, Any]]) -> str:
    test_text = json.dumps(test_results, ensure_ascii=False, indent=2)
    return f"""Review implementation for {task_id} at the current HEAD against base commit {base_commit}.

You are the second-stage reviewer. ChatGPT already planned, implemented, and self-reviewed. Your job is adversarial verification on a real local checkout.

Inspect the exact diff `{base_commit}...HEAD`, relevant surrounding code, and tests. Focus on correctness, regressions, security, data integrity, concurrency, compatibility, error handling, and missing tests. Do not modify files.

Local test execution evidence gathered before your review:
{test_text}

Return only JSON matching the provided output schema. Use APPROVE only when there are no critical/major findings and local validation is acceptable. Use REVISE when code changes are required.
"""


def _parse_last_message(path: Path, test_results: list[dict[str, Any]]) -> ReviewResult:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewExecutionError(f"Codex did not produce valid structured JSON: {exc}") from exc
    result = ReviewResult(
        verdict=raw.get("verdict", ""),
        summary=raw.get("summary", ""),
        findings=raw.get("findings", []),
        tests=test_results,
    )
    result.validate()
    return result


def review_pr_head(
    repo: Path,
    *,
    task_id: str,
    pr_number: int,
    head_sha: str,
    base_commit: str,
    command_runner: Callable[[list[str], Path, int], subprocess.CompletedProcess[str]] = _run,
) -> ReviewResult:
    config = load_config(repo)
    timeout = int(config["review"]["timeout_seconds"])
    ref = f"refs/agent-bridge/pr-{pr_number}"
    run_git(repo, "fetch", "origin", f"+pull/{pr_number}/head:{ref}")
    resolved = run_git(repo, "rev-parse", ref)
    if resolved != head_sha:
        raise ReviewExecutionError(f"PR head changed during fetch: expected {head_sha}, got {resolved}")
    ensure_base_is_ancestor(repo, base_commit, ref)

    with tempfile.TemporaryDirectory(prefix="agent-bridge-review-") as tmp:
        worktree = Path(tmp) / "worktree"
        run_git(repo, "worktree", "add", "--detach", str(worktree), ref)
        try:
            tests = run_test_commands(worktree, list(config["review"]["test_commands"]), timeout)
            schema = Path(tmp) / "codex-review.schema.json"
            schema.write_text(json.dumps(CODEX_REVIEW_SCHEMA, indent=2) + "\n", encoding="utf-8")
            last_message = Path(tmp) / "codex-review.json"
            prompt = build_review_prompt(task_id, base_commit, tests)
            cmd = [
                str(config["review"]["codex_command"]), "exec", "--ephemeral",
                "--output-schema", str(schema), "--output-last-message", str(last_message), prompt,
            ]
            proc = command_runner(cmd, worktree, timeout)
            if proc.returncode != 0:
                raise ReviewExecutionError(f"codex exec failed ({proc.returncode}): {proc.stderr[-4000:]}")
            result = _parse_last_message(last_message, tests)
            # Local execution is authoritative. Missing required tests or any test failure prevents approval.
            if not tests and bool(config["review"].get("require_tests_for_approval", True)) and result.verdict == "APPROVE":
                result.verdict = "REVISE"
                result.findings.append({
                    "severity": "major",
                    "title": "No local test commands configured",
                    "detail": "Configure `.ai/config.json` review.test_commands before unattended approval, or explicitly disable require_tests_for_approval.",
                })
            if any(item["exit_code"] != 0 for item in tests) and result.verdict == "APPROVE":
                result.verdict = "REVISE"
                result.findings.append({
                    "severity": "major",
                    "title": "Local validation failed",
                    "detail": "At least one configured local test command failed; the implementation cannot be approved.",
                })
            return result
        finally:
            run_git(repo, "worktree", "remove", "--force", str(worktree), check=False)
