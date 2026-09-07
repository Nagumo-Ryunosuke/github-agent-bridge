---
name: github-agent-bridge
description: Coordinate GitHub-mediated development where Codex analyzes and dispatches locally, a normal ChatGPT Web Chat designs and implements, optional Work brokers events or explicitly approved bounded automation, and Codex reviews each implementation PR with real local tests. Use for automated ChatGPT/Codex handoff, Task PR dispatch, exact-SHA review loops, cross-platform setup, or watcher service management.
---

# GitHub Agent Bridge

Use this role split unless the user explicitly overrides it:

- **GitHub**: durable task/context/event transport and exact SHA identity.
- **ChatGPT Web Chat**: architecture, high-quality reasoning, primary implementation, tests, first self-review, and development decisions.
- **ChatGPT Work**: optional bounded event/automation broker only; never the default developer.
- **Codex**: local requirement reconnaissance, task dispatch, second review, real test execution, debugging and verification.
- **Human**: final merge/acceptance and explicit approval for ad-hoc Work delegation.

## Chat-first resource-control contract

A normal ChatGPT Web Chat is the default development surface.

Never invoke, create, switch to, or delegate implementation to ChatGPT Work automatically from Chat. Task complexity is not permission to use Work.

Before any ad-hoc Chat-to-Work delegation:

1. Explain the exact capability gap.
2. Describe the bounded operation proposed for Work; keep architecture/design ownership in Chat.
3. Ask whether the user permits this Work run.
4. Ask which model/reasoning level to use when selectable. Never default to the newest, strongest, or most expensive model merely because it is available.
5. If model selection is unavailable, disclose that the platform default Work model would be used and ask whether to proceed.
6. Wait for explicit approval.
7. Return control to Chat after the bounded operation finishes.

Approval is per operation, not blanket permission for later Work runs.

GitHub event-triggered Work tasks are a separate pre-authorized case and must be **broker-only**: parse the event, identify task/review state, prepare a compact handoff, and stop. They must not design, edit code, run broad tests, use the writer, create/update implementation PRs, start another Work task, or escalate the configured model/reasoning level. Obtain the user's model/reasoning approval when creating each persistent broker trigger; if model selection is unavailable, disclose the platform default before enabling it.

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
6. Use the system default browser for authentication. GitHub login must use `gh auth login -w`; Codex login opens its OAuth page in the system default browser. Do not route these flows through the Codex in-app browser unless the user explicitly asks.
7. Never bypass OS elevation, GitHub authorization, or ChatGPT/Codex login. These remain user-controlled interactive security boundaries.
8. Re-run `agent-bridge env status` after installation. Do not claim readiness from an install command alone.

The installer is architecture-neutral: it detects OS/CPU and delegates binaries to native package managers or the official OpenAI Codex installer. Full unattended local review is only possible on platforms for which upstream GitHub CLI and Codex CLI builds/packages exist. On an unsupported CPU/OS, report the exact missing upstream capability instead of pretending deployment succeeded.

### Desktop-only vs automated review

Codex App/Desktop can discover and use the same Skill from `$HOME/.agents/skills/github-agent-bridge` without using the terminal UI as the primary interface. However, the persistent background reviewer calls `codex exec --ephemeral`, so **Codex CLI is required for the automated review loop**, even when the user normally works in Codex Desktop.

`agent-bridge env install --skip-codex` is only a dispatch/Desktop fallback and must not be described as full reviewer readiness.

## Before starting repository work

1. Work from the real target repository.
2. Run `agent-bridge env status`; self-bootstrap missing local prerequisites as described above.
3. Run `agent-bridge doctor`.
4. If the user supplied a GitHub remote URL, use `agent-bridge connect <REMOTE_URL>`; otherwise, if repository setup is incomplete, inspect the repository and infer a real authoritative test command from its existing tooling, then prefer `agent-bridge setup bootstrap` over asking the user to edit `.ai/config.json` manually.
5. Ask only for genuinely security-sensitive attestations that cannot be inferred, such as confirming a tested write-capable GitHub connection or unattended-write policy. Never fabricate `--confirm-write`, `--confirm-unattended`, or Work-trigger confirmation.
6. If the watcher service is missing, install it with `agent-bridge service install` after local prerequisites are ready.
7. Treat Work-trigger readiness only as optional broker automation readiness; it never authorizes Work to perform primary implementation.

## On a new development request in Codex

1. Inspect the repository, relevant instructions, tests and constraints locally.
2. If the user supplies a GitHub remote URL, run `agent-bridge connect <REMOTE_URL>` first so the standard `.ai/` bridge files are present.
3. Do only enough analysis to produce a narrow implementation contract; do not spend Codex usage implementing the full change.
4. Create a task with ChatGPT as developer and Codex as reviewer.
5. Check commit drift with `agent-bridge drift <TASK>`.
6. Validate collaboration state with `agent-bridge validate`.
7. Dispatch using `agent-bridge publish task <TASK>`.
8. Stop local implementation. Continue architecture/design and implementation in a normal ChatGPT Web Chat. Optional Work event brokers may only prepare a compact handoff.

## ChatGPT Web Chat implementation contract

When the user continues a marked Task PR in a normal ChatGPT Web Chat:

1. Read `.ai/tasks/<TASK>.md`, repository context/instructions, exact pinned base, and current PR/review state.
2. Keep architecture/design, implementation decisions, test design and self-review in Chat.
3. Design before editing.
4. Branch from the exact pinned base commit.
5. Implement the change and tests.
6. Self-review the exact diff once and fix obvious issues.
7. Use the configured managed or MCP writer to create/update the implementation PR when available.
8. Put `<!-- agent-bridge:implementation task=TASK-XXXXXX -->` in the PR body.
9. Never merge the implementation PR.
10. If writer capability is unavailable, do not pretend to push.
11. Never invoke Work automatically. If a specific operation cannot be completed in Chat, follow the resource-control contract and wait for explicit user/model approval first.

## Work delegation contract

Work is subordinate to the active Chat conversation.

Allowed uses after explicit approval include a bounded browser/computer-use operation, a clearly specified automation step whose decisions were already made in Chat, or an optional pre-authorized GitHub event broker. Work must not independently redesign the solution, expand scope, choose a higher-cost model, perform primary implementation, or recursively create another Work task.

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
- route `REVISE` back to the normal ChatGPT Web Chat for fixes.

Do not modify ChatGPT's implementation branch during normal review. An optional Work broker may summarize a `REVISE` event, but it must not fix code or push a new head.

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

## Optional Work broker setup

`agent-bridge trigger automation-setup` renders the current broker-only setup instructions.

Before saving a persistent Work broker, show the user the intended model/reasoning level and obtain explicit approval. Prefer the least costly option sufficient for GitHub event parsing and handoff. If the platform cannot expose model selection, disclose the platform-default Work model and ask whether to continue.

The two supported broker roles are:

1. Task PR opened/ready + `agent-bridge:task` → compact implementation handoff for Chat.
2. PR comment + `agent-bridge:codex-review` + `verdict=REVISE` → compact revision handoff for Chat.

After the brokers are actually configured and model-approved, `agent-bridge setup work-trigger --confirm` may record that setup. This confirmation never grants permission for Work to implement or for Chat to launch future Work runs automatically.

## Safety

- Keep `.env`, tokens, credentials and private keys out of `.ai/`.
- Keep final merge human-controlled unless the user explicitly changes the policy.
- Do not grant GitHub admin/secrets/delete permissions just to simplify setup.
- Local test commands execute implementation PR code; use an appropriate machine/container/VM.
- Do not hide installation commands, model/resource implications, or authorization steps from the user.
