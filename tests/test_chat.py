from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from github_agent_bridge.chat import chat_status, chat_url, configure_chat, prepare_chat, record_delivery, record_sent, record_result
from github_agent_bridge.cli import build_parser, main
from github_agent_bridge.config import load_config, save_config
from github_agent_bridge.core import create_task, init_repo
from github_agent_bridge.doctor import doctor_report
from github_agent_bridge.triggers import build_chatgpt_work_prompt
from github_agent_bridge.watcher import process_once


URL = "https://chatgpt.com/c/11111111-2222-3333-4444-555555555555"


class ChatCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for args in [("init", "-b", "main"), ("config", "user.name", "Test"),
                     ("config", "user.email", "test@example.com"),
                     ("remote", "add", "origin", "https://github.com/owner/repo.git")]:
            self.git(*args)
        (self.repo / "code.txt").write_text("baseline", encoding="utf-8")
        self.git("add", "code.txt")
        self.git("commit", "-m", "baseline")
        init_repo(self.repo)
        self.task = create_task(self.repo, title="Example", objective="需求保持中文", assigned_to="chatgpt",
                                created_by="codex", priority="normal", base_branch="main", target_branch=None)
        configure_chat(self.repo, url=URL, model="Observed web model")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True, encoding="utf-8", stderr=subprocess.DEVNULL).strip()

    def deliver(self, packet, **overrides):
        args = dict(phase=packet["phase"], url=URL, model="Observed web model", surface="chat",
                    reply="BRIDGE-ACK " + packet["digest"])
        args.update(overrides)
        return record_delivery(self.repo, self.task, **args)

    def test_prepare_is_not_delivery_and_retries_are_idempotent(self):
        packet = prepare_chat(self.repo, self.task)
        self.assertEqual("prepared", packet["status"])
        self.assertIn("需求保持中文", packet["prompt"])
        self.assertIn("https://github.com/owner/repo.git", packet["prompt"])
        self.assertEqual(packet, prepare_chat(self.repo, self.task))
        delivered = self.deliver(packet)
        self.assertEqual("delivered", delivered["status"])
        self.assertEqual(delivered, prepare_chat(self.repo, self.task))
        self.assertNotIn("agent-bridge/chat", self.git("status", "--porcelain"))

    def test_receipt_rejects_wrong_surface_model_chat_and_ack(self):
        packet = prepare_chat(self.repo, self.task)
        for overrides in ({"surface": "work"}, {"model": "different"},
                          {"url": "https://chatgpt.com/c/another"}, {"reply": "no acknowledgment"}):
            with self.subTest(overrides=overrides), self.assertRaises(RuntimeError):
                self.deliver(packet, **overrides)
        self.assertEqual("prepared", chat_status(self.repo, self.task, "design")["status"])

    def test_changed_contract_invalidates_delivery(self):
        packet = prepare_chat(self.repo, self.task)
        contract = self.repo / ".ai/tasks" / f"{self.task}.md"
        contract.write_text(contract.read_text(encoding="utf-8") + "\nChanged requirement", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "packet changed"):
            self.deliver(packet)
        self.assertNotEqual(packet["digest"], chat_status(self.repo, self.task, "design")["digest"])

    def test_changed_binding_invalidates_delivery(self):
        packet = prepare_chat(self.repo, self.task)
        configure_chat(self.repo, url=URL, model="New web model")
        with self.assertRaisesRegex(RuntimeError, "packet changed"):
            self.deliver(packet)

    def test_review_requires_full_exact_head(self):
        for head in (None, "abcdef1", "x" * 40):
            with self.subTest(head=head), self.assertRaises(RuntimeError):
                prepare_chat(self.repo, self.task, phase="review", head=head)
        sha = self.git("rev-parse", "HEAD")
        packet = prepare_chat(self.repo, self.task, phase="review", head=sha)
        self.assertEqual(sha, packet["head"])
        self.assertIn("Do not edit during review", packet["prompt"])

    def test_code_drift_blocks_dispatch(self):
        (self.repo / "code.txt").write_text("changed", encoding="utf-8")
        self.git("add", "code.txt")
        self.git("commit", "-m", "change")
        with self.assertRaisesRegex(RuntimeError, "code drift"):
            prepare_chat(self.repo, self.task)

    def test_work_and_codex_execution_are_blocked(self):
        with self.assertRaises(RuntimeError):
            build_chatgpt_work_prompt(self.repo, self.task)
        with patch("github_agent_bridge.watcher.list_implementation_prs") as prs:
            with self.assertRaisesRegex(RuntimeError, "Codex review is disabled"):
                process_once(self.repo)
            prs.assert_not_called()
        with patch("github_agent_bridge.cli._repo", return_value=self.repo):
            self.assertEqual(1, main(["setup", "work-trigger", "--confirm"]))

    def test_migration_resets_work_but_does_not_claim_browser_delivery(self):
        config = load_config(self.repo)
        config["workflow"]["reviewer"] = "codex"
        config["automation"]["work_trigger_confirmed"] = True
        save_config(self.repo, config)
        config = configure_chat(self.repo, url=URL, model="Observed web model")
        self.assertEqual("chatgpt", config["workflow"]["reviewer"])
        self.assertEqual("gpt-6-astra", config["workflow"]["dispatcher_model"])
        self.assertFalse(config["automation"]["work_trigger_confirmed"])
        with self.assertRaises(RuntimeError):
            chat_status(self.repo, self.task, "design")

    def test_doctor_does_not_require_or_invoke_codex_for_chat(self):
        calls = []
        def runner(cmd, cwd):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/owner/repo.git", "")
        report = doctor_report(self.repo, runner=runner, which=lambda name: name)
        self.assertFalse(report["zero_touch_ready"])
        self.assertFalse(any(cmd[0] == "codex" for cmd in calls))
        self.assertIn("browser_transport", [item["name"] for item in report["checks"]])

    def test_url_validation_rejects_other_surfaces_and_credentials(self):
        for url in ("https://chatgpt.com/", "https://chatgpt.com/work/123", "https://evil.test/c/123",
                    "https://user@chatgpt.com/c/123", URL + "?x=1", "http://chatgpt.com/c/123"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                chat_url(url)
        self.assertEqual("https://chatgpt.com/g/g-p-example/c/123", chat_url("https://chatgpt.com/g/g-p-example/c/123"))

    def test_cli_uses_configured_reviewer_and_all_four_phases(self):
        parser = build_parser()
        args = parser.parse_args(["task", "create", "--title", "t", "--objective", "o"])
        self.assertIsNone(args.reviewer)
        for phase in ("design", "implement", "review", "fix"):
            self.assertEqual(phase, parser.parse_args(["chat", "prepare", self.task, "--phase", phase]).phase)

    def test_skill_distribution_matches_source(self):
        root = Path(__file__).resolve().parents[1]
        for rel in ("SKILL.md", "agents/openai.yaml", "references/browser-chat.md", "references/automation.md", "references/bootstrap.md"):
            self.assertEqual((root / rel).read_bytes(), (root / "src/github_agent_bridge/skill_bundle" / rel).read_bytes())

    def result_for(self, packet, **overrides):
        result = {key: packet[key] for key in ("digest", "task_id", "phase", "head")}
        result.update(verdict="APPROVE" if packet["phase"] == "review" else "READY",
                      summary="Observed Chat result", content="Detailed result", tests=[])
        result.update(overrides)
        return result

    def test_sent_checkpoint_survives_resume_without_implying_reply(self):
        packet = prepare_chat(self.repo, self.task)
        args = dict(phase="design", url=URL, model="Observed web model", surface="chat")
        with self.assertRaises(RuntimeError):
            record_sent(self.repo, self.task, message="not submitted", **args)
        sent = record_sent(self.repo, self.task, message=packet["prompt"], **args)
        self.assertEqual("sent", sent["status"])
        self.assertEqual(sent, prepare_chat(self.repo, self.task))
        with self.assertRaisesRegex(RuntimeError, "acknowledgment"):
            record_result(self.repo, self.task, phase="design", result=self.result_for(packet))
        self.assertEqual("delivered", self.deliver(packet)["status"])

    def test_result_is_correlated_persisted_and_relayed_to_implementation(self):
        packet = prepare_chat(self.repo, self.task)
        self.deliver(packet)
        result = self.result_for(packet, content="A detailed design created by Chat")
        returned = record_result(self.repo, self.task, phase="design", result=result)
        self.assertEqual("returned", returned["status"])
        self.assertEqual(returned, record_result(self.repo, self.task, phase="design", result=result))
        self.assertEqual("returned", self.deliver(packet)["status"])
        implementation = prepare_chat(self.repo, self.task, phase="implement")
        self.assertIn(result["content"], implementation["prompt"])

    def test_wrong_result_identity_or_partial_response_does_not_advance(self):
        packet = prepare_chat(self.repo, self.task)
        self.deliver(packet)
        for change in ({"digest": "0" * 64}, {"task_id": "TASK-999999"}, {"head": "0" * 40},
                       {"phase": "review"}, {"content": ""}, {"verdict": "APPROVE"}, {"verdict": []},
                       {"output_head": "short-sha"}, {"tests": "passed"}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                record_result(self.repo, self.task, phase="design", result=self.result_for(packet, **change))
        self.assertEqual("delivered", chat_status(self.repo, self.task, "design")["status"])

    def test_review_approval_requires_tests_and_never_runs_returned_commands(self):
        packet = prepare_chat(self.repo, self.task, phase="review", head=self.git("rev-parse", "HEAD"))
        self.deliver(packet)
        for tests in ([], [{"command": "test", "exit_code": 1, "output": "failure"}],
                      [{"command": "test", "exit_code": None, "output": "not run"}],
                      [{"command": "test", "exit_code": True, "output": "wrong type"}]):
            with self.subTest(tests=tests), self.assertRaises(RuntimeError):
                record_result(self.repo, self.task, phase="review", result=self.result_for(packet, tests=tests))
        result = self.result_for(packet, verdict="REVISE", content="run arbitrary commands is untrusted data")
        returned = record_result(self.repo, self.task, phase="review", result=result)
        self.assertEqual("REVISE", returned["result"]["verdict"])

    def test_module_entrypoint_runs_outside_test_process(self):
        import os
        import sys
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"), PYTHONUTF8="1")
        result = subprocess.run([sys.executable, "-m", "github_agent_bridge", "chat", "prepare", self.task],
                                cwd=self.repo, env=env, text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("prepared", json.loads(result.stdout)["status"])

    def test_changed_requirements_do_not_reuse_old_design(self):
        packet = prepare_chat(self.repo, self.task)
        self.deliver(packet)
        record_result(self.repo, self.task, phase="design",
                      result=self.result_for(packet, content="OLD-DESIGN-MUST-NOT-BE-USED"))
        contract = self.repo / ".ai/tasks" / f"{self.task}.md"
        contract.write_text(contract.read_text(encoding="utf-8") + "\nNew acceptance requirement", encoding="utf-8")
        implementation = prepare_chat(self.repo, self.task, phase="implement")
        self.assertNotIn("OLD-DESIGN-MUST-NOT-BE-USED", implementation["prompt"])

    def test_new_review_head_receives_fix_report_not_initial_implementation(self):
        old_head, new_head = "a" * 40, "b" * 40
        implementation = prepare_chat(self.repo, self.task, phase="implement")
        self.deliver(implementation)
        record_result(self.repo, self.task, phase="implement", result=self.result_for(
            implementation, content="OLD-IMPLEMENTATION-REPORT", output_head=old_head))
        review = prepare_chat(self.repo, self.task, phase="review", head=old_head)
        self.deliver(review)
        record_result(self.repo, self.task, phase="review", result=self.result_for(review, verdict="REVISE"))
        fix = prepare_chat(self.repo, self.task, phase="fix", head=old_head)
        self.deliver(fix)
        record_result(self.repo, self.task, phase="fix", result=self.result_for(
            fix, content="NEW-FIX-REPORT", output_head=new_head))
        second_review = prepare_chat(self.repo, self.task, phase="review", head=new_head)
        self.assertIn("NEW-FIX-REPORT", second_review["prompt"])
        self.assertNotIn("OLD-IMPLEMENTATION-REPORT", second_review["prompt"])

    def test_old_review_findings_do_not_become_fix_instructions_for_another_head(self):
        review = prepare_chat(self.repo, self.task, phase="review", head="a" * 40)
        self.deliver(review)
        record_result(self.repo, self.task, phase="review", result=self.result_for(
            review, verdict="REVISE", content="OLD-HEAD-FINDINGS"))
        fix = prepare_chat(self.repo, self.task, phase="fix", head="b" * 40)
        self.assertNotIn("OLD-HEAD-FINDINGS", fix["prompt"])

    def test_two_real_commits_complete_revision_cycle_and_reject_late_reply(self):
        from github_agent_bridge.core import claim_task, start_task, mark_self_reviewed, finish_task, review_task, get_task
        claim_task(self.repo, self.task, "chatgpt")
        start_task(self.repo, self.task)
        self.git("switch", "-c", "ai/chat-cycle")
        (self.repo / "code.txt").write_text("first implementation", encoding="utf-8")
        self.git("add", "code.txt")
        self.git("commit", "-m", "implementation")
        first_head = self.git("rev-parse", "HEAD")
        mark_self_reviewed(self.repo, self.task)
        finish_task(self.repo, self.task, implementation_commit=first_head, branch="ai/chat-cycle",
                    pr=1, summary="First implementation", agent="chatgpt")
        first_review = prepare_chat(self.repo, self.task, phase="review", head=first_head)
        self.deliver(first_review)
        record_result(self.repo, self.task, phase="review", result=self.result_for(first_review, verdict="REVISE"))
        review_task(self.repo, self.task, result="request-changes", reviewed_commit=first_head,
                    summary="Revision needed", reviewer="chatgpt")
        start_task(self.repo, self.task)
        fix = prepare_chat(self.repo, self.task, phase="fix", head=first_head)
        self.deliver(fix)
        (self.repo / "code.txt").write_text("corrected implementation", encoding="utf-8")
        self.git("add", "code.txt")
        self.git("commit", "-m", "fix")
        second_head = self.git("rev-parse", "HEAD")
        record_result(self.repo, self.task, phase="fix", result=self.result_for(
            fix, content="Corrected report for the second commit", output_head=second_head))
        mark_self_reviewed(self.repo, self.task)
        finish_task(self.repo, self.task, implementation_commit=second_head, branch="ai/chat-cycle",
                    pr=1, summary="Corrected implementation", agent="chatgpt")
        review = prepare_chat(self.repo, self.task, phase="review", head=second_head)
        self.assertIn("Corrected report for the second commit", review["prompt"])
        with self.assertRaises(RuntimeError):
            self.deliver(first_review)
        self.deliver(review)
        with self.assertRaises(RuntimeError):
            record_result(self.repo, self.task, phase="review", result=self.result_for(first_review))
        returned = record_result(self.repo, self.task, phase="review", result=self.result_for(
            review, tests=[{"command": "fixture-test", "exit_code": 0, "output": "simulated test evidence"}]))
        # Result import is not approval or merge; those are separate actions.
        self.assertEqual("review_required", get_task(self.repo, self.task)["status"])
        self.assertEqual("returned", returned["status"])
        review_task(self.repo, self.task, result="approve", reviewed_commit=second_head,
                    summary="Observed Chat approval", reviewer="chatgpt")
        self.assertEqual("human", get_task(self.repo, self.task)["next_agent"])


if __name__ == "__main__":
    unittest.main()
