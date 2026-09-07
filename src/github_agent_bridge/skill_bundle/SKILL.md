---
name: github-agent-bridge
description: Coordinate GitHub-mediated development where Codex analyzes and dispatches locally, ChatGPT Web/Work designs and implements, and Codex reviews each implementation PR with real local tests. Use for automated ChatGPT/Codex handoff, Task PR dispatch, exact-SHA review loops, zero-touch setup, or cross-platform Codex App/CLI deployment.
---

# GitHub Agent Bridge

Use this role split unless the user explicitly overrides it:

- **GitHub**: durable task/context/event transport and exact SHA identity.
- **ChatGPT Web/Work**: architecture, high-quality reasoning, primary implementation, tests, first self-review.
- **Codex**: local requirement reconnaissance, task dispatch, second review, real test execution, debugging and verification.
- **Human**: final merge/acceptance by default.

## Self-bootstrap contract

This Skill is designed for Codex App/Desktop, Codex CLI and Codex IDE surfaces on Windows, Linux and macOS.

When the Skill is invoked, do not make the user manually install each dependency one by one.

1. Try `agent-bridge env status` first.
2. If the user provides a GitHub remote URL and `agent-bridge` is available, run `agent-bridge connect <REMOTE_URL>` first. It validates access, clones or resumes the checkout, initializes `.ai/`, infers tests, and installs the repository Skill.
3. If `agent-bridge` itself is unavailable, detect the local OS and offer **one consolidated installation confirmation**:
   - Linux/macOS: `curl -fsSL https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.sh | sh`
   - Windows PowerShell: `irm https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.ps1 | iex`
4. Explain the machine changes before execution. After the user approves, run the bootstrap command instead of giving a long manual checklist.
5. If `agent-bridge` exists but Git, GitHub CLI or Codex CLI/authentication is incomplete, show the plan from `agent-bridge env install` and ask for one consolidated approval. After approval, run `agent-bridge env install --yes`.
6. Never bypass OS elevation, GitHub authorization, or ChatGPT/Codex login. `sudo`, `gh auth login`, and `codex login` remain user-controlled interactive security boundaries.
7. Re-run `agent-bridge env status` after installation. Do not claim readiness from an install command alone.

The installer is architecture-neutral: it detects OS/CPU and delegates binaries to native package managers or the official OpenAI Codex installer. Full unattended review is only possible on platforms for which upstream GitHub CLI and Codex CLI builds/packages exist. On an unsupported CPU/OS, report the exact missing upstream capability instead of pretending the deployment succeeded.

### Desktop-only vs full automation

Codex App/Desktop can discover and use the same Skill from `$HOME/.agents/skills/github-agent-bridge` without using the terminal UI as the primary interface. However, the persistent background reviewer calls `codex exec --ephemeral`, so **Codex CLI is required for the full zero-touch review loop**, even when the user normally works in Codex Desktop.

`agent-bridge env install --skip-codex` is only a dispatch/Desktop fallback and must not be described as full zero-touch readiness.

## Before starting repository work

1. Work from the real target repository.
2. Run `agent-bridge env status`; self-bootstrap missing local prerequisites as described above.
3. Run `agent-bridge doctor`.
4. If the user supplied a GitHub remote URL, use `agent-bridge connect <REMOTE_URL>`; otherwise, if repository setup is incomplete, inspect the repository and infer a real authoritative test command from its existing tooling, then prefer `agent-bridge setup bootstrap` over asking the user to edit `.ai/config.json` manually.
5. Ask only for genuinely security-sensitive attestations that cannot be inferred, such as confirming a tested write-capable GitHub connection or unattended-write policy. Never fabricate `--confirm-write`, `--confirm-unattended`, or Work-trigger confirmation.
6. If the watcher service is missing, install it with `agent-bridge service install` after local prerequisites are ready.
7. Never claim zero-touch readiness unless `agent-bridge doctor` reports `Zero-touch ready: YES`.

## On a new development request in Codex

1. Inspect the repository, relevant instructions, tests and constraints locally.
2. Do only enough analysis to produce a narrow implementation contract; do not spend Codex usage implementing the full change.
3. Create a task with ChatGPT as developer and Codex as reviewer.
4. Check commit drift with `agent-bridge drift <TASK>`.
5. Validate collaboration state with `agent-bridge validate`.
6. Dispatch using `agent-bridge publish task <TASK>`.
7. Stop local implementation and let the GitHub event-triggered ChatGPT Work task take ownership.

## ChatGPT implementation contract

When a marked Task PR wakes ChatGPT:

1. Read `.ai/tasks/<TASK>.md`, repository context/instructions, exact pinned base, and current PR/review state.
2. Design before editing.
3. Branch from the exact pinned base commit.
4. Implement the change and tests.
5. Self-review the exact diff once and fix obvious issues.
6. Use the configured managed or MCP writer to create/update the implementation PR.
7. Put `<!-- agent-bridge:implementation task=TASK-XXXXXX -->` in the PR body.
8. Never merge the implementation PR.
9. If writer capability is unavailable, do not pretend to push.

## Codex local review contract

The persistent watcher reviews each eligible implementation PR head SHA once:

- reject cross-repository PRs;
- enforce the trusted implementation branch prefix;
- verify the task pinned base is an ancestor of the reviewed head;
- fetch the exact head into an isolated worktree;
- run configured authoritative local tests;
- invoke structured `codex exec --ephemeral` review;
- treat actual test evidence as authoritative;
- post a machine-marked `APPROVE` or `REVISE` comment;
- route `REVISE` back to ChatGPT Work for fixes.

Do not modify ChatGPT's implementation branch during normal review.

## Cross-platform setup

The recommended first-install path is the one-command bootstrap in the self-bootstrap section. If the package is already installed, install/update the Skill with:

`agent-bridge skill install --scope user`

The installer writes real files to `$HOME/.agents/skills/github-agent-bridge`; Codex App/Desktop, CLI and IDE clients share this user-level Skill root. Restart Codex after first installation or Skill upgrade.

Install the persistent watcher with:

`agent-bridge service install`

Auto backend mapping:

- Linux: systemd user service.
- macOS: launchd LaunchAgent.
- Windows: per-user Task Scheduler task.

Then run `agent-bridge service status` and `agent-bridge doctor`.

See `references/cross-platform.md` and `references/automation.md` for operational details.

## Safety

- Keep `.env`, tokens, credentials and private keys out of `.ai/`.
- Keep final merge human-controlled unless the user explicitly changes the policy.
- Do not grant GitHub admin/secrets/delete permissions just to simplify setup.
- Local test commands execute implementation PR code; use an appropriate machine/container/VM.
- Do not hide installation commands or authorization steps from the user. Consolidate prompts, but preserve meaningful consent.
