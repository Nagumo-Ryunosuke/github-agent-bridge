from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from github_agent_bridge.config import configure_dispatch
from github_agent_bridge.core import create_task, init_repo
from github_agent_bridge.dispatch import DispatchError, dispatch_status, dispatch_task, refresh_dispatch_status, verify_implementation_pr
from github_agent_bridge.triggers import implementation_marker


API_SECRET = "api-secret-value"
MCP_SECRET = "mcp-secret-value"
ENV = {
    "AGENT_BRIDGE_OPENAI_API_KEY": API_SECRET,
    "AGENT_BRIDGE_MCP_TOKEN": MCP_SECRET,
}


class DispatchCase(unittest.TestCase):
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
        self.task_id = create_task(
            self.repo,
            title="T",
            objective="Implement active dispatch.",
            assigned_to="chatgpt",
            reviewer="codex",
            created_by="codex",
            priority="normal",
            base_branch="main",
            target_branch=None,
        )
        configure_dispatch(self.repo, mcp_server_url="https://mcp.example.test/github")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def fake_request(self, calls):
        def request(method, url, payload, bearer_token, idempotency_key, timeout):
            calls.append({"method": method, "url": url, "payload": payload, "token": bearer_token, "idempotency_key": idempotency_key})
            if url.endswith("/conversations"):
                return {"id": "conv_1"}
            if method == "POST" and url.endswith("/responses"):
                return {"id": "resp_1", "status": "queued"}
            if method == "GET" and "/responses/" in url:
                return {"id": "resp_1", "status": "completed"}
            raise AssertionError(url)
        return request

    def test_missing_dispatch_configuration_fails(self) -> None:
        config_path = self.repo / ".ai/config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["dispatch"]["mcp_server_url"] = None
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaises(DispatchError):
            dispatch_task(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", requester=self.fake_request([]), environ=ENV)

    def test_active_dispatch_contains_required_context_and_persists_safe_state(self) -> None:
        calls = []
        result = dispatch_task(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", requester=self.fake_request(calls), environ=ENV)
        self.assertFalse(result["reused"])
        self.assertEqual("conv_1", result["conversation_id"])
        response_call = next(item for item in calls if item["url"].endswith("/responses"))
        prompt = response_call["payload"]["input"][0]["content"][0]["text"]
        self.assertIn("https://github.com/owner/repo.git", prompt)
        self.assertIn(self.task_id, prompt)
        self.assertIn("https://github.com/owner/repo/pull/1", prompt)
        self.assertIn("Pinned base commit SHA:", prompt)
        self.assertIn("Target branch: ai/task-000001", prompt)
        self.assertIn("Implement active dispatch.", prompt)
        raw_state = json.dumps(dispatch_status(self.repo), ensure_ascii=False)
        self.assertNotIn(API_SECRET, raw_state)
        self.assertNotIn(MCP_SECRET, raw_state)

    def test_dispatch_is_idempotent_for_same_task(self) -> None:
        calls = []
        requester = self.fake_request(calls)
        first = dispatch_task(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", requester=requester, environ=ENV)
        second = dispatch_task(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", requester=requester, environ=ENV)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(1, sum(1 for item in calls if item["url"].endswith("/responses")))

    def test_dispatch_state_recovers_from_disk(self) -> None:
        dispatch_task(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", requester=self.fake_request([]), environ=ENV)
        recovered = dispatch_status(self.repo, self.task_id)
        self.assertEqual("conv_1", recovered["conversation_id"])
        self.assertEqual("resp_1", recovered["attempts"]["implement"]["response_id"])

    def test_failed_dispatch_redacts_credentials(self) -> None:
        def failing_request(method, url, payload, bearer_token, idempotency_key, timeout):
            if url.endswith("/conversations"):
                return {"id": "conv_1"}
            raise RuntimeError(f"upstream rejected {API_SECRET} and {MCP_SECRET}")

        with self.assertRaises(DispatchError) as raised:
            dispatch_task(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", requester=failing_request, environ=ENV)
        self.assertNotIn(API_SECRET, str(raised.exception))
        self.assertNotIn(MCP_SECRET, str(raised.exception))
        raw_state = json.dumps(dispatch_status(self.repo), ensure_ascii=False)
        self.assertNotIn(API_SECRET, raw_state)
        self.assertNotIn(MCP_SECRET, raw_state)

    def test_chat_completion_does_not_complete_without_trusted_pr(self) -> None:
        requester = self.fake_request([])
        dispatch_task(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", requester=requester, environ=ENV)
        result = refresh_dispatch_status(self.repo, self.task_id, requester=requester, environ=ENV, prs=[])
        self.assertEqual("awaiting_implementation_pr", result["status"])
        self.assertFalse(result["implementation_complete"])

    def test_pr_marker_branch_and_exact_sha_are_required(self) -> None:
        good_sha = "a" * 40
        good = {
            "number": 7,
            "body": implementation_marker(self.task_id),
            "headRefOid": good_sha,
            "headRefName": "ai/task-000001",
            "baseRefName": "main",
            "url": "https://github.com/owner/repo/pull/7",
            "isCrossRepository": False,
        }
        verified = verify_implementation_pr(self.repo, self.task_id, prs=[good])
        self.assertEqual(good_sha, verified["head_sha"])
        wrong_marker = dict(good, body="<!-- agent-bridge:implementation task=TASK-999999 -->")
        self.assertIsNone(verify_implementation_pr(self.repo, self.task_id, prs=[wrong_marker]))
        short_sha = dict(good, headRefOid="abcdef1")
        self.assertIsNone(verify_implementation_pr(self.repo, self.task_id, prs=[short_sha]))
        wrong_branch = dict(good, headRefName="ai/other")
        self.assertIsNone(verify_implementation_pr(self.repo, self.task_id, prs=[wrong_branch]))

    def test_trusted_pr_completes_implementation_fact(self) -> None:
        requester = self.fake_request([])
        dispatch_task(self.repo, self.task_id, task_pr_url="https://github.com/owner/repo/pull/1", requester=requester, environ=ENV)
        pr = {
            "number": 7,
            "body": implementation_marker(self.task_id),
            "headRefOid": "b" * 40,
            "headRefName": "ai/task-000001",
            "baseRefName": "main",
            "url": "https://github.com/owner/repo/pull/7",
            "isCrossRepository": False,
        }
        result = refresh_dispatch_status(self.repo, self.task_id, requester=requester, environ=ENV, prs=[pr])
        self.assertEqual("implementation_ready", result["status"])
        self.assertTrue(result["implementation_complete"])
        self.assertEqual("b" * 40, result["implementation"]["head_sha"])


if __name__ == "__main__":
    unittest.main()
