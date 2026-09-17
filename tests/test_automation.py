from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from github_agent_bridge.core import create_task, init_repo
from github_agent_bridge.dispatch import build_dispatch_prompt
from github_agent_bridge.publisher import PublishError, _create_or_reuse_task_pr
from github_agent_bridge.reviewer import ReviewExecutionError, ReviewResult, ensure_base_is_ancestor
from github_agent_bridge.security import scan_text, validate_ai_tree
from github_agent_bridge.triggers import codex_review_marker, implementation_marker, parse_codex_review_marker, parse_implementation_marker, parse_task_marker, task_marker
from github_agent_bridge.watcher import process_once, review_to_markdown
from github_agent_bridge.writers import writer_contract


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


class AutomationCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.check_call(["git", "init", "-b", "main"], cwd=self.repo, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "test@example.com"], cwd=self.repo)
        subprocess.check_call(["git", "config", "user.name", "Test"], cwd=self.repo)
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "README.md"], cwd=self.repo)
        subprocess.check_call(["git", "commit", "-m", "init"], cwd=self.repo, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "remote", "add", "origin", "https://github.com/owner/repo.git"], cwd=self.repo)
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

    def test_dispatch_prompt_carries_pinned_contract_and_never_merges(self) -> None:
        text = build_dispatch_prompt(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", phase="implement")
        self.assertIn("Repository URL: https://github.com/owner/repo.git", text)
        self.assertIn(f"Task ID: {self.task_id}", text)
        self.assertIn("Pinned base commit SHA:", text)
        self.assertIn("Target branch: ai/task-000001", text)
        self.assertIn("Never merge", text)

    def test_fix_prompt_binds_exact_reviewed_head(self) -> None:
        text = build_dispatch_prompt(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", phase="fix", reviewed_head="a" * 40, implementation_pr_url="https://github.com/owner/repo/pull/2")
        self.assertIn("a" * 40, text)
        self.assertIn("stale review", text)

    def test_writer_contract_forbids_merge(self) -> None:
        contract = writer_contract()
        self.assertIn("commit_files", contract["required_actions"])
        self.assertIn("merge_pull_request", contract["forbidden_by_default"])

    def test_secret_scan(self) -> None:
        self.assertIn("private-key", scan_text("-----BEGIN PRIVATE KEY-----\nabc"))
        self.assertEqual([], scan_text("ordinary content"))

    def test_ai_tree_rejects_env(self) -> None:
        (self.repo / ".ai/.env").write_text("X=1\n", encoding="utf-8")
        self.assertTrue(any("sensitive filename" in item for item in validate_ai_tree(self.repo)))

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
        unrelated = subprocess.check_output(["git", "commit-tree", tree, "-m", "unrelated-root"], cwd=self.repo, text=True).strip()
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

    def pr(self, number: int, sha: str, branch: str = "ai/task-000001"):
        return {"number": number, "title": "x", "body": implementation_marker(self.task_id), "headRefOid": sha, "headRefName": branch, "baseRefName": "main", "url": f"https://github.com/owner/repo/pull/{number}", "isCrossRepository": False}

    def test_watcher_deduplicates_same_head(self) -> None:
        pr = self.pr(7, "a" * 40)
        calls = []
        def reviewer(*args, **kwargs):
            calls.append(kwargs["head_sha"])
            return ReviewResult("APPROVE", "ok", [], [{"command": "t", "exit_code": 0}])
        posted = []
        first = process_once(self.repo, prs=[pr], reviewer=reviewer, poster=lambda repo, num, body: posted.append((num, body)))
        second = process_once(self.repo, prs=[pr], reviewer=reviewer, poster=lambda repo, num, body: posted.append((num, body)))
        self.assertEqual(1, len(first))
        self.assertEqual([], second)
        self.assertEqual(["a" * 40], calls)
        self.assertEqual(1, len(posted))

    def test_revise_is_actively_redispatched_with_exact_head(self) -> None:
        pr = self.pr(10, "b" * 40)
        dispatched = []
        def dispatcher(repo, task_id, **kwargs):
            dispatched.append((task_id, kwargs))
            return {"dispatch_key": f"fix:{kwargs['reviewed_head']}", "reused": False}
        events = process_once(self.repo, prs=[pr], reviewer=lambda *args, **kwargs: ReviewResult("REVISE", "fix", [{"severity": "major", "title": "Bug", "detail": "bad"}], [{"command": "t", "exit_code": 1}]), poster=lambda *args: None, dispatcher=dispatcher)
        self.assertEqual("REVISE", events[0]["verdict"])
        self.assertEqual(self.task_id, dispatched[0][0])
        self.assertEqual("b" * 40, dispatched[0][1]["reviewed_head"])
        self.assertEqual(pr["url"], dispatched[0][1]["implementation_pr_url"])

    def test_watcher_skips_cross_repo(self) -> None:
        pr = self.pr(8, "c" * 40)
        pr["isCrossRepository"] = True
        events = process_once(self.repo, prs=[pr], reviewer=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not review")), poster=lambda *args: None)
        self.assertEqual("skipped", events[0]["status"])

    def test_watcher_skips_untrusted_branch(self) -> None:
        pr = self.pr(9, "d" * 40, branch="feature/x")
        events = process_once(self.repo, prs=[pr], reviewer=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not review")), poster=lambda *args: None)
        self.assertEqual("skipped", events[0]["status"])
        self.assertIn("ai/", events[0]["reason"])

    def test_watcher_skips_wrong_ai_branch_even_with_marker(self) -> None:
        pr = self.pr(11, "e" * 40, branch="ai/other")
        events = process_once(self.repo, prs=[pr], reviewer=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not review")), poster=lambda *args: None)
        self.assertEqual("skipped", events[0]["status"])
        self.assertIn("exactly match", events[0]["reason"])


if __name__ == "__main__":
    unittest.main()
