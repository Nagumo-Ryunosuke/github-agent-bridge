from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from github_agent_bridge.config import bootstrap_config, configure_writer, load_config, save_config
from github_agent_bridge.doctor import doctor_report, parse_github_remote


NOW = datetime(2026, 9, 4, 8, 30, 0, tzinfo=timezone.utc)
ENV = {
    "AGENT_BRIDGE_OPENAI_API_KEY": "dispatch-service-key",
    "AGENT_BRIDGE_MCP_TOKEN": "mcp-service-token",
    "AGENT_BRIDGE_CODEX_API_KEY": "review-service-key",
}


class DoctorCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".ai/state").mkdir(parents=True)
        (self.repo / ".ai/state/tasks.json").write_text('{"schema_version": 1, "tasks": {}}\n', encoding="utf-8")
        self.write_heartbeat("2026-09-04T08:29:30+00:00")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_heartbeat(self, value: str) -> None:
        path = self.repo / ".git/agent-bridge/watcher.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "reviewed_heads": {}, "last_poll_at": value}) + "\n", encoding="utf-8")

    def fake_which(self, command: str):
        if command in {"gh", "codex"}:
            return f"/usr/bin/{command}"
        return None

    def fake_runner(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if cmd[:4] == ["git", "config", "--get", "remote.origin.url"]:
            return subprocess.CompletedProcess(cmd, 0, "git@github.com:owner/repo.git\n", "")
        if cmd[:4] == ["git", "rev-parse", "--git-path", "agent-bridge/watcher.json"]:
            return subprocess.CompletedProcess(cmd, 0, ".git/agent-bridge/watcher.json\n", "")
        if "auth" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "authenticated\n", "")
        if len(cmd) >= 3 and cmd[1:3] == ["repo", "view"]:
            return subprocess.CompletedProcess(cmd, 0, '{"nameWithOwner":"owner/repo"}\n', "")
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "codex 1.0\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def ready_config(self, **overrides) -> None:
        kwargs = {
            "mode": "readonly",
            "repositories": ["owner/repo"],
            "test_commands": ["python -m unittest"],
            "dispatch_mcp_server_url": "https://mcp.example.test/github",
        }
        kwargs.update(overrides)
        bootstrap_config(self.repo, **kwargs)

    def report(self, environ=None):
        return doctor_report(self.repo, runner=self.fake_runner, which=self.fake_which, now=NOW, environ=ENV if environ is None else environ)

    def test_parse_github_remote_variants(self) -> None:
        self.assertEqual({"host": "github.com", "repository": "owner/repo"}, parse_github_remote("https://github.com/owner/repo.git"))
        self.assertEqual({"host": "github.com", "repository": "owner/repo"}, parse_github_remote("https://github.com/owner/repo/"))
        self.assertEqual({"host": "github.com", "repository": "owner/repo"}, parse_github_remote("git@github.com:owner/repo.git"))
        self.assertIsNone(parse_github_remote("not-a-remote"))

    def test_zero_touch_ready_when_active_dispatch_and_service_credentials_are_ready(self) -> None:
        self.ready_config()
        report = self.report()
        self.assertTrue(report["zero_touch_ready"])
        self.assertNotIn("chatgpt_work_trigger", {item["name"] for item in report["checks"]})
        self.assertEqual("pass", next(item for item in report["checks"] if item["name"] == "active_dispatch")["status"])

    def test_missing_dispatch_configuration_blocks_zero_touch(self) -> None:
        self.ready_config()
        config = load_config(self.repo)
        config["dispatch"]["mcp_server_url"] = None
        save_config(self.repo, config)
        report = self.report()
        active = next(item for item in report["checks"] if item["name"] == "active_dispatch")
        self.assertEqual("fail", active["status"])
        self.assertFalse(report["zero_touch_ready"])

    def test_missing_dispatch_service_credential_blocks_zero_touch(self) -> None:
        self.ready_config()
        env = dict(ENV)
        env.pop("AGENT_BRIDGE_OPENAI_API_KEY")
        report = self.report(env)
        active = next(item for item in report["checks"] if item["name"] == "active_dispatch")
        self.assertEqual("fail", active["status"])
        self.assertNotIn("dispatch-service-key", json.dumps(report))
        self.assertFalse(report["zero_touch_ready"])

    def test_missing_codex_service_credential_blocks_zero_touch(self) -> None:
        self.ready_config()
        env = dict(ENV)
        env.pop("AGENT_BRIDGE_CODEX_API_KEY")
        report = self.report(env)
        auth = next(item for item in report["checks"] if item["name"] == "codex_service_credential")
        self.assertEqual("fail", auth["status"])
        self.assertFalse(report["zero_touch_ready"])

    def test_repository_allowlist_is_required(self) -> None:
        self.ready_config(repositories=[])
        report = self.report()
        allowlist = next(item for item in report["checks"] if item["name"] == "repository_allowlist")
        self.assertEqual("fail", allowlist["status"])
        self.assertFalse(report["zero_touch_ready"])

    def test_stale_watcher_blocks_zero_touch(self) -> None:
        self.ready_config()
        self.write_heartbeat("2026-09-04T08:20:00+00:00")
        report = self.report()
        watcher = next(item for item in report["checks"] if item["name"] == "codex_watcher")
        self.assertEqual("fail", watcher["status"])
        self.assertFalse(report["zero_touch_ready"])

    def test_far_future_watcher_heartbeat_blocks_zero_touch(self) -> None:
        self.ready_config()
        self.write_heartbeat("2026-09-04T08:40:00+00:00")
        report = self.report()
        watcher = next(item for item in report["checks"] if item["name"] == "codex_watcher")
        self.assertEqual("fail", watcher["status"])
        self.assertIn("future", watcher["message"])

    def test_small_clock_skew_is_tolerated(self) -> None:
        self.ready_config()
        self.write_heartbeat("2026-09-04T08:31:00+00:00")
        report = self.report()
        watcher = next(item for item in report["checks"] if item["name"] == "codex_watcher")
        self.assertEqual("pass", watcher["status"])

    def test_bootstrap_preserves_dispatch_and_review_config_when_omitted(self) -> None:
        self.ready_config()
        bootstrap_config(self.repo, mode="readonly", repositories=["owner/repo"], test_commands=None)
        config = load_config(self.repo)
        self.assertEqual("https://mcp.example.test/github", config["dispatch"]["mcp_server_url"])
        self.assertEqual("AGENT_BRIDGE_OPENAI_API_KEY", config["dispatch"]["api_key_env"])
        self.assertEqual("AGENT_BRIDGE_CODEX_API_KEY", config["review"]["api_key_env"])
        self.assertEqual(["python -m unittest"], config["review"]["test_commands"])

    def test_repository_scope_change_still_invalidates_writer_confirmation(self) -> None:
        self.ready_config()
        configure_writer(self.repo, mode="managed", connection_name="writer", repositories=["owner/repo"], write_confirmed=True, unattended_confirmed=True)
        configure_writer(self.repo, mode="managed", repositories=["owner/other"])
        config = load_config(self.repo)
        self.assertFalse(config["github"]["managed"]["write_confirmed"])
        self.assertFalse(config["github"]["managed"]["unattended_confirmed"])

    def test_legacy_work_trigger_configuration_is_rejected(self) -> None:
        config = load_config(self.repo)
        config["automation"]["work_trigger_confirmed"] = True
        save_config(self.repo, config)
        with self.assertRaisesRegex(RuntimeError, "obsolete ChatGPT Work trigger"):
            load_config(self.repo)

    def test_configure_writer_rejects_malformed_repository(self) -> None:
        save_config(self.repo, load_config(self.repo))
        with self.assertRaises(RuntimeError):
            configure_writer(self.repo, mode="readonly", repositories=["bad-repository"])


if __name__ == "__main__":
    unittest.main()
