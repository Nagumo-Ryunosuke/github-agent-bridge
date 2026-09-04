from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from github_agent_bridge.config import configure_writer
from github_agent_bridge.core import create_task, init_repo
from github_agent_bridge.publisher import PublishError, _create_or_reuse_task_pr
from github_agent_bridge.reviewer import ReviewExecutionError, ReviewResult, ensure_base_is_ancestor
from github_agent_bridge.security import scan_text, validate_ai_tree
from github_agent_bridge.triggers import (
    build_chatgpt_work_prompt,
    codex_review_marker,
    implementation_marker,
    parse_codex_review_marker,
    parse_implementation_marker,
    parse_task_marker,
    task_marker,
)
from github_agent_bridge.watcher import process_once, review_to_markdown
from github_agent_bridge.writers import writer_contract


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


class AutomationCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.repo = Path(self.tmp.name)
        subprocess.check_call(["git", "init", "-b", "main"], cwd=self.repo, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "test@example.com"], cwd=self.repo)
        subprocess.check_call(["git", "config", "user.name", "Test"], cwd=self.repo)
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "README.md"], cwd=self.repo); subprocess.check_call(["git", "commit", "-m", "init"], cwd=self.repo, stdout=subprocess.DEVNULL)
        init_repo(self.repo)
        self.task_id = create_task(self.repo, title="T", objective="O", assigned_to="chatgpt", reviewer="codex", created_by="codex", priority="normal", base_branch="main", target_branch=None)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_markers_round_trip(self) -> None:
        self.assertEqual(self.task_id, parse_task_marker(task_marker(self.task_id)))
        self.assertEqual(self.task_id, parse_implementation_marker(implementation_marker(self.task_id)))
        marker = codex_review_marker(self.task_id, "REVISE", "abcdef1")
        self.assertEqual({"task_id": self.task_id, "verdict": "REVISE", "head_sha": "abcdef1"}, parse_codex_review_marker(marker))

    def test_bad_review_verdict_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            codex_review_marker(self.task_id, "MAYBE", "abcdef1")

    def test_work_prompt_reports_readonly_gap(self) -> None:
        text = build_chatgpt_work_prompt(self.repo, self.task_id)
        self.assertIn("not write-ready", text)
        self.assertIn("Do not pretend to push", text)

    def test_work_prompt_reports_managed_writer(self) -> None:
        configure_writer(self.repo, mode="managed", connection_name="writer", write_confirmed=True, unattended_confirmed=True)
        text = build_chatgpt_work_prompt(self.repo, self.task_id)
        self.assertIn("write-ready", text)
        self.assertIn("Unattended writes are confirmed", text)

    def test_writer_contract_forbids_merge(self) -> None:
        contract = writer_contract()
        self.assertIn("commit_files", contract["required_actions"])
        self.assertIn("merge_pull_request", contract["forbidden_by_default"])

    def test_secret_scan(self) -> None:
        self.assertIn("private-key", scan_text("-----BEGIN PRIVATE KEY-----\nabc"))
        self.assertEqual([], scan_text("ordinary content"))

    def test_ai_tree_rejects_env(self) -> None:
        (self.repo / ".ai/.env").write_text("X=1\n", encoding="utf-8")
        self.assertTrue(any("sensitive filename" in x for x in validate_ai_tree(self.repo)))

    def test_review_result_validation(self) -> None:
        ReviewResult("APPROVE", "ok", [], []).validate()
        with self.assertRaises(ReviewExecutionError):
            ReviewResult("MAYBE", "ok", [], []).validate()
        with self.assertRaises(ReviewExecutionError):
            ReviewResult("REVISE", "ok", [{"severity": "bad", "title": "x", "detail": "y"}], []).validate()

    def test_review_markdown_contains_machine_marker(self) -> None:
        result = ReviewResult("REVISE", "fix", [{"severity": "major", "title": "Bug", "detail": "bad"}], [{"command": "pytest", "exit_code": 1}])
        text = review_to_markdown(self.task_id, "abcdef1", result)
        self.assertIn("agent-bridge:codex-review", text)
        self.assertIn("verdict=REVISE", text)
        self.assertIn("pytest", text)

    def test_pinned_base_must_be_ancestor_of_review_head(self) -> None:
        base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "later.txt").write_text("later\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "later.txt"], cwd=self.repo)
        subprocess.check_call(["git", "commit", "-m", "later"], cwd=self.repo, stdout=subprocess.DEVNULL)
        ensure_base_is_ancestor(self.repo, base, "HEAD")

        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        unrelated = subprocess.check_output(
            ["git", "commit-tree", tree, "-m", "unrelated-root"],
            cwd=self.repo,
            text=True,
        ).strip()
        with self.assertRaises(ReviewExecutionError):
            ensure_base_is_ancestor(self.repo, base, unrelated)

    def test_closed_task_pr_is_not_silently_reused(self) -> None:
        task = {"base": {"branch": "main"}, "title": "T"}
        with patch("github_agent_bridge.publisher._view_task_pr", return_value={"number": 12, "url": "u", "state": "CLOSED"}):
            with self.assertRaises(PublishError):
                _create_or_reuse_task_pr(self.repo, self.task_id, "agent-bridge/task-000001", task, "abcdef1")

    def test_open_task_pr_can_be_reused(self) -> None:
        task = {"base": {"branch": "main"}, "title": "T"}
        with patch("github_agent_bridge.publisher._view_task_pr", return_value={"number": 12, "url": "u", "state": "OPEN"}):
            result = _create_or_reuse_task_pr(self.repo, self.task_id, "agent-bridge/task-000001", task, "abcdef1")
        self.assertTrue(result["reused"])
        self.assertEqual(12, result["pr"])

    def test_watcher_deduplicates_same_head(self) -> None:
        pr = {"number": 7, "title": "x", "body": implementation_marker(self.task_id), "headRefOid": "abcdef1", "headRefName": "ai/task-000001", "baseRefName": "main", "url": "u", "isCrossRepository": False}
        calls = []
        def reviewer(*args, **kwargs):
            calls.append(kwargs["head_sha"])
            return ReviewResult("APPROVE", "ok", [], [{"command": "t", "exit_code": 0}])
        posted = []
        def poster(repo, num, body): posted.append((num, body))
        first = process_once(self.repo, prs=[pr], reviewer=reviewer, poster=poster)
        second = process_once(self.repo, prs=[pr], reviewer=reviewer, poster=poster)
        self.assertEqual(1, len(first)); self.assertEqual([], second); self.assertEqual(["abcdef1"], calls); self.assertEqual(1, len(posted))

    def test_watcher_skips_cross_repo(self) -> None:
        pr = {"number": 8, "title": "x", "body": implementation_marker(self.task_id), "headRefOid": "abcdef2", "headRefName": "ai/task-000001", "baseRefName": "main", "url": "u", "isCrossRepository": True}
        events = process_once(self.repo, prs=[pr], reviewer=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not review")), poster=lambda *a: None)
        self.assertEqual("skipped", events[0]["status"])

    def test_watcher_skips_untrusted_branch(self) -> None:
        pr = {"number": 9, "title": "x", "body": implementation_marker(self.task_id), "headRefOid": "abcdef3", "headRefName": "feature/x", "baseRefName": "main", "url": "u", "isCrossRepository": False}
        events = process_once(self.repo, prs=[pr], reviewer=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not review")), poster=lambda *a: None)
        self.assertEqual("skipped", events[0]["status"])
        self.assertIn("ai/", events[0]["reason"])


if __name__ == "__main__":
    unittest.main()
