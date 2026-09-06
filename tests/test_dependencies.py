from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from github_agent_bridge.dependencies import build_install_plan, detect_environment


class DependenciesCase(unittest.TestCase):
    def test_windows_plan_installs_git_gh_and_codex(self) -> None:
        available = {"winget": "C:/winget.exe", "powershell": "C:/powershell.exe"}
        status = {
            "platform": "Windows",
            "git": {"available": False},
            "gh": {"available": False},
            "codex": {"available": False},
        }
        plan = build_install_plan(status, which=available.get)
        self.assertEqual(["git", "gh", "codex"], [step.name for step in plan])
        self.assertIn("Git.Git", plan[0].command)
        self.assertIn("GitHub.cli", plan[1].command)
        self.assertIn("chatgpt.com/codex/install.ps1", plan[2].command[-1])

    def test_linux_apt_plan_installs_gh_curl_and_codex(self) -> None:
        available = {"apt-get": "/usr/bin/apt-get", "sh": "/bin/sh"}
        status = {
            "platform": "Linux",
            "git": {"available": True},
            "gh": {"available": False},
            "codex": {"available": False},
        }
        with mock.patch("github_agent_bridge.dependencies._sudo_prefix", return_value=[]):
            plan = build_install_plan(status, which=available.get)
        self.assertEqual(["packages-update", "packages", "codex"], [step.name for step in plan])
        self.assertIn("gh", plan[1].command)
        self.assertIn("curl", plan[1].command)
        self.assertIn("chatgpt.com/codex/install.sh", plan[2].command[-1])

    def test_detect_environment_separates_desktop_dispatch_from_unattended_review(self) -> None:
        paths = {"git": "/usr/bin/git", "gh": "/usr/bin/gh"}

        def runner(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
            if "auth" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "authenticated\n", "")
            return subprocess.CompletedProcess(cmd, 0, "1.0\n", "")

        status = detect_environment(which=paths.get, runner=runner, platform_name="Linux")
        self.assertTrue(status["dispatch_ready"])
        self.assertFalse(status["unattended_review_ready"])
        self.assertFalse(status["codex"]["available"])

    def test_codex_login_status_is_checked(self) -> None:
        paths = {"git": "/git", "gh": "/gh", "codex": "/codex"}
        calls: list[list[str]] = []

        def runner(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if cmd[0] == "/gh" and "auth" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "authenticated", "")
            if cmd[:3] == ["/codex", "login", "status"]:
                return subprocess.CompletedProcess(cmd, 1, "", "not logged in")
            return subprocess.CompletedProcess(cmd, 0, "1.0", "")

        status = detect_environment(which=paths.get, runner=runner, platform_name="Linux")
        self.assertFalse(status["codex"]["authenticated"])
        self.assertIn(["/codex", "login", "status"], calls)

    def test_skip_codex_makes_dispatch_readiness_authoritative(self) -> None:
        paths = {"git": "/git", "gh": "/gh"}

        def runner(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        status = detect_environment(include_codex=False, which=paths.get, runner=runner, platform_name="Windows")
        self.assertTrue(status["dispatch_ready"])
        self.assertFalse(status["unattended_review_ready"])
        self.assertFalse(status["codex"]["required"])


if __name__ == "__main__":
    unittest.main()
