from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from github_agent_bridge.config import configure_review, configure_writer, load_config
from github_agent_bridge.core import (
    claim_task,
    complete_task,
    create_task,
    drift_report,
    finish_task,
    get_task,
    init_repo,
    mark_self_reviewed,
    review_task,
    start_task,
    validate_state,
)
from github_agent_bridge.writers import detect_writer


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.check_call(["git", "init", "-b", "main"], cwd=self.repo, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "test@example.com"], cwd=self.repo)
        subprocess.check_call(["git", "config", "user.name", "Test"], cwd=self.repo)
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "README.md"], cwd=self.repo)
        subprocess.check_call(["git", "commit", "-m", "init"], cwd=self.repo, stdout=subprocess.DEVNULL)
        init_repo(self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def task(self) -> str:
        return create_task(
            self.repo,
            title="Refactor sync",
            objective="Unify synchronization.",
            assigned_to="chatgpt",
            reviewer="codex",
            created_by="codex",
            priority="high",
            base_branch="main",
            target_branch=None,
        )


class CoreTests(RepoCase):
    def test_init_creates_config_and_state(self) -> None:
        self.assertTrue((self.repo / ".ai/config.json").exists())
        self.assertTrue((self.repo / ".ai/state/tasks.json").exists())
        cfg = load_config(self.repo)
        self.assertEqual("chatgpt", cfg["workflow"]["developer"])
        self.assertEqual("codex", cfg["workflow"]["reviewer"])

    def test_task_defaults_to_chatgpt_and_codex(self) -> None:
        tid = self.task()
        task = get_task(self.repo, tid)
        self.assertEqual("chatgpt", task["developer"])
        self.assertEqual("codex", task["reviewer"])
        self.assertEqual("chatgpt", task["next_agent"])
        self.assertEqual("ai/task-000001", task["target_branch"])

    def test_task_is_pinned_to_exact_base(self) -> None:
        tid = self.task()
        self.assertEqual(git(self.repo, "rev-parse", "main"), get_task(self.repo, tid)["base"]["commit"])

    def test_chatgpt_handoff_requires_self_review(self) -> None:
        tid = self.task()
        claim_task(self.repo, tid, "chatgpt")
        start_task(self.repo, tid)
        with self.assertRaises(RuntimeError):
            finish_task(self.repo, tid, implementation_commit=git(self.repo, "rev-parse", "HEAD"), branch="ai/task-000001", pr=1, summary="done", agent="chatgpt")

    def test_self_review_allows_handoff_to_codex(self) -> None:
        tid = self.task()
        claim_task(self.repo, tid, "chatgpt")
        start_task(self.repo, tid)
        mark_self_reviewed(self.repo, tid)
        finish_task(self.repo, tid, implementation_commit=git(self.repo, "rev-parse", "HEAD"), branch="ai/task-000001", pr=1, summary="done", agent="chatgpt")
        task = get_task(self.repo, tid)
        self.assertEqual("review_required", task["status"])
        self.assertEqual("codex", task["next_agent"])

    def test_revise_routes_back_to_chatgpt_and_resets_self_review(self) -> None:
        tid = self.task(); claim_task(self.repo, tid, "chatgpt"); start_task(self.repo, tid); mark_self_reviewed(self.repo, tid)
        sha = git(self.repo, "rev-parse", "HEAD")
        finish_task(self.repo, tid, implementation_commit=sha, branch="ai/task-000001", pr=1, summary="done", agent="chatgpt")
        review_task(self.repo, tid, result="request-changes", reviewed_commit=sha, summary="fix", reviewer="codex")
        task = get_task(self.repo, tid)
        self.assertEqual("changes_requested", task["status"])
        self.assertEqual("chatgpt", task["next_agent"])
        self.assertFalse(task["self_reviewed"])

    def test_approve_routes_to_human_and_can_complete(self) -> None:
        tid = self.task(); claim_task(self.repo, tid, "chatgpt"); start_task(self.repo, tid); mark_self_reviewed(self.repo, tid)
        sha = git(self.repo, "rev-parse", "HEAD")
        finish_task(self.repo, tid, implementation_commit=sha, branch="ai/task-000001", pr=1, summary="done", agent="chatgpt")
        review_task(self.repo, tid, result="approve", reviewed_commit=sha, summary="ok", reviewer="codex")
        self.assertEqual("human", get_task(self.repo, tid)["next_agent"])
        complete_task(self.repo, tid)
        self.assertEqual("done", get_task(self.repo, tid)["status"])

    def test_review_rejects_wrong_commit(self) -> None:
        tid = self.task(); claim_task(self.repo, tid, "chatgpt"); start_task(self.repo, tid); mark_self_reviewed(self.repo, tid)
        sha = git(self.repo, "rev-parse", "HEAD")
        finish_task(self.repo, tid, implementation_commit=sha, branch="ai/task-000001", pr=1, summary="done", agent="chatgpt")
        with self.assertRaises(RuntimeError):
            review_task(self.repo, tid, result="approve", reviewed_commit="deadbeef", summary="no", reviewer="codex")

    def test_code_drift_is_not_metadata_only(self) -> None:
        tid = self.task()
        (self.repo / "code.py").write_text("x=1\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "code.py"], cwd=self.repo); subprocess.check_call(["git", "commit", "-m", "advance"], cwd=self.repo, stdout=subprocess.DEVNULL)
        report = drift_report(self.repo, tid)
        self.assertTrue(report["drift"]); self.assertFalse(report["metadata_only"])

    def test_metadata_only_drift(self) -> None:
        tid = self.task()
        subprocess.check_call(["git", "add", ".ai"], cwd=self.repo); subprocess.check_call(["git", "commit", "-m", "ai metadata"], cwd=self.repo, stdout=subprocess.DEVNULL)
        report = drift_report(self.repo, tid)
        self.assertTrue(report["drift"]); self.assertTrue(report["metadata_only"])

    def test_validate_state_accepts_normal_task(self) -> None:
        self.task()
        self.assertEqual([], validate_state(self.repo))


class ConfigWriterTests(RepoCase):
    def test_default_writer_is_readonly(self) -> None:
        status = detect_writer(self.repo)
        self.assertEqual("readonly", status["mode"])
        self.assertFalse(status["ready"])

    def test_managed_requires_write_confirmation(self) -> None:
        configure_writer(self.repo, mode="managed", connection_name="writer", write_confirmed=False)
        self.assertFalse(detect_writer(self.repo)["ready"])

    def test_managed_can_be_unattended_confirmed(self) -> None:
        configure_writer(self.repo, mode="managed", connection_name="writer", write_confirmed=True, unattended_confirmed=True, repositories=["o/r"])
        status = detect_writer(self.repo)
        self.assertTrue(status["ready"]); self.assertTrue(status["unattended_ready"])
        self.assertFalse(status["capabilities"]["merge"])

    def test_custom_mcp_requires_server_name(self) -> None:
        with self.assertRaises(RuntimeError):
            configure_writer(self.repo, mode="custom-mcp", write_confirmed=True)

    def test_review_configuration_is_persisted(self) -> None:
        configure_review(self.repo, test_commands=["python -m unittest"], codex_command="codex-x", timeout_seconds=42, require_tests_for_approval=False)
        cfg = load_config(self.repo)["review"]
        self.assertEqual(["python -m unittest"], cfg["test_commands"])
        self.assertEqual("codex-x", cfg["codex_command"])
        self.assertEqual(42, cfg["timeout_seconds"])
        self.assertFalse(cfg["require_tests_for_approval"])

    def test_review_timeout_must_be_positive(self) -> None:
        with self.assertRaises(RuntimeError):
            configure_review(self.repo, timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
