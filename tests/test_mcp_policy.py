from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from github_agent_bridge import mcp_server


class MCPPolicyTests(unittest.TestCase):
    def test_allowlist_is_mandatory(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                mcp_server._assert_repo_allowed("o/r")

    def test_allowlist_blocks_other_repo(self) -> None:
        with patch.dict(os.environ, {"AGENT_BRIDGE_ALLOWED_REPOS": "o/r"}, clear=True):
            mcp_server._assert_repo_allowed("o/r")
            with self.assertRaises(RuntimeError):
                mcp_server._assert_repo_allowed("x/y")

    def test_branch_prefix_is_enforced(self) -> None:
        with patch.dict(os.environ, {"AGENT_BRIDGE_BRANCH_PREFIX": "ai/"}, clear=True):
            mcp_server._assert_write_branch("ai/task")
            with self.assertRaises(RuntimeError):
                mcp_server._assert_write_branch("main")

    def test_safe_path_rejects_parent_escape(self) -> None:
        with self.assertRaises(ValueError):
            mcp_server._safe_path("../secret")
        self.assertEqual("src/x.py", mcp_server._safe_path("src/x.py"))

    def test_write_content_secret_guard(self) -> None:
        with self.assertRaises(RuntimeError):
            mcp_server._assert_safe_content("api_key=abcdefghijklmnopqrstuv")
        mcp_server._assert_safe_content("print('ok')")

    def test_create_branch_requires_exactly_one_base(self) -> None:
        with patch.dict(os.environ, {"AGENT_BRIDGE_ALLOWED_REPOS": "o/r", "AGENT_BRIDGE_BRANCH_PREFIX": "ai/"}, clear=True):
            with self.assertRaises(ValueError):
                mcp_server.create_branch("o/r", "ai/x")
            with self.assertRaises(ValueError):
                mcp_server.create_branch("o/r", "ai/x", base_sha="abc", base_ref="main")


if __name__ == "__main__":
    unittest.main()
