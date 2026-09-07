---
name: github-agent-bridge
description: Coordinate GitHub-mediated development where Codex analyzes and dispatches locally, a normal ChatGPT Web Chat designs and implements, optional Work brokers GitHub events or explicitly approved bounded automation, and Codex reviews each implementation PR with real local tests. Use for automated ChatGPT/Codex handoff, Task PR dispatch, exact-SHA review loops, cross-platform setup, or watcher service management.
---

# GitHub Agent Bridge

Treat this role split as the default architecture:

- **GitHub** = communication, durable context, PR/event transport, exact SHA identity.
- **ChatGPT Web Chat** = primary architecture, reasoning, code implementation, test authoring, first self-review, and development decisions.
- **ChatGPT Work** = optional bounded automation/event broker only; never the default developer.
- **Codex** = local repository reconnaissance/dispatch, second review, real test execution, debugging, adversarial verification.
- **Human** = final merge/acceptance and explicit approval for any ad-hoc Work delegation.

Do not silently invert these roles. Codex should not become the primary implementer unless ChatGPT write capability is unavailable or the user explicitly asks for a local fallback. Work must not become the primary implementer merely because it is available or because a task is complex.

## Chat-first resource-control policy

A normal ChatGPT Web Chat is the default and primary development surface.

**Never invoke, create, switch to, or delegate implementation to ChatGPT Work automatically from Chat. Task complexity is not permission to use Work.**

Before any ad-hoc Chat-to-Work delegation:

1. Explain the exact capability gap that prevents Chat from completing the operation directly.
2. Describe the bounded operation proposed for Work. Keep architecture/design ownership in Chat.
3. Ask the user whether Work may be used for this operation.
4. Ask which model/reasoning level the user wants when the platform exposes that choice. Do not default to the newest, strongest, or most expensive model.
5. If model selection is unavailable, state clearly that the platform default Work model would be used and ask whether to proceed.
6. Wait for explicit approval before invoking Work.
7. After Work completes the bounded operation, return control to Chat for review and all further decisions.

A user approval for one Work operation does not grant blanket permission for later Work runs.

GitHub event-triggered Work tasks are a separate, pre-authorized automation case. They must be configured as **brokers only**: parse the event, identify the task/review state, prepare a compact handoff, and stop. They must not design, edit code, run broad tests, use the writer, create/update implementation PRs, or start another Work task. The user must approve the event trigger's model/reasoning choice when the trigger is created; if the platform cannot expose that choice, disclose the platform-default model before enabling the trigger.

## Self-bootstrap and permission protocol

The user should be able to read the README, run one bootstrap command, then use this Skill from Codex App/Desktop or Codex CLI without manually installing each dependency.

When this Skill is invoked:

1. Try `agent-bridge env status` first.
2. If the user provides a GitHub remote URL and `agent-bridge` is available, run `agent-bridge connect <REMOTE_URL>` first. It validates access, clones or resumes the checkout, initializes `.ai/`, infers tests, and installs the repository Skill.
3. If `agent-bridge` is not installed, detect the operating system and offer **one consolidated installation confirmation**. After approval, run the appropriate one-command bootstrap:
   - Linux/macOS: `curl -fsSL https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.sh | sh`
   - Windows PowerShell: `irm https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.ps1 | iex`
4. If `agent-bridge` exists but local dependencies are incomplete, show the installation plan produced by `agent-bridge env install`, ask once, then run `agent-bridge env install --yes` after approval.
5. Do not ask separately for every package. Consolidate non-sensitive machine changes into one approval whenever possible.
6. Use the system default browser for authentication. GitHub login must use `gh auth login -w`; Codex login opens its OAuth page in the system default browser. Do not route these flows through the Codex in-app browser unless the user explicitly asks.
7. Do not bypass security boundaries. OS elevation, GitHub authorization and ChatGPT/Codex account login remain interactive user actions.
8. Re-run `agent-bridge env status` after changes. Installation success is not equivalent to authentication/readiness.

The bootstrap is deliberately architecture-neutral: Python code does not hard-code x86 paths, Linux uses the detected distribution package manager, Windows uses WinGet, macOS uses native tooling/Homebrew when necessary, and Codex CLI is installed using OpenAI's architecture-aware official installer. Full local review automation still depends on upstream GitHub CLI and Codex CLI availability for the actual OS/CPU. If an upstream binary/package does not exist for a platform, report that boundary precisely and retain whatever Skill/dispatch functionality is available.

## Codex App / CLI portability

This Skill is intended to behave the same from Codex App/Desktop, Codex CLI, and Codex IDE clients.

Prefer a user installation so every local Codex surface can discover the same Skill:

`agent-bridge skill install --scope user`

The installer writes real files to `$HOME/.agents/skills/github-agent-bridge`, the Codex USER Skill root. Restart Codex if a newly installed/updated Skill is not visible immediately.

For repository-only distribution, use:

`agent-bridge skill install --scope repo`

The persistent unattended reviewer invokes `codex exec --ephemeral`, so Codex CLI remains a runtime dependency for the automated review loop. `agent-bridge env install --skip-codex` is only a desktop/dispatch fallback, not full reviewer readiness.

Read `references/cross-platform.md` for OS-specific service behavior.

## On a new development request in Codex

1. Inspect the real local repository, relevant instructions, tests, architecture, and constraints.
2. Run `agent-bridge env status`. If local prerequisites are incomplete, follow the self-bootstrap protocol above instead of giving a manual dependency checklist.
3. If the user supplied a GitHub remote URL, use `agent-bridge connect <REMOTE_URL>`; otherwise, if the bridge has not been configured for this repository, inspect the existing project tooling and infer a real authoritative test command, then prefer `agent-bridge setup bootstrap` over asking the user to edit `.ai/config.json` manually.
4. Run `agent-bridge doctor` and report any setup/capability gap honestly.
5. Ask only for genuinely non-inferable security attestations. Never fabricate `--confirm-write`, `--confirm-unattended`, or Work-trigger confirmation.
6. Summarize the task into a narrow implementable contract; do not spend Codex usage implementing the full change yet.
7. Create a commit-pinned task with ChatGPT as developer and Codex as reviewer.
8. Run `agent-bridge drift <TASK>` before dispatch. Treat code drift as a replanning signal; `.ai/`-only drift is metadata and may be safe.
9. Run `agent-bridge validate`.
10. Publish with `agent-bridge publish task <TASK>` rather than asking the user to manually create a PR.
11. Stop local implementation work. The implementation must continue in a normal ChatGPT Web Chat. If optional GitHub event-triggered Work brokers are configured, they may only prepare a compact handoff/notification; they must not take ownership of implementation.

## ChatGPT Web Chat implementation policy

When the user continues a published task in a normal ChatGPT Web Chat:

1. Read the Task PR, `.ai/tasks/<TASK>.md`, context, repository instructions, and exact pinned base.
2. Keep planning, architecture, implementation decisions, test design, and self-review in this Chat conversation.
3. Design the solution before editing.
4. Create the implementation branch from the **exact pinned base commit**, not simply from the current branch head.
5. Implement the change and tests.
6. Perform a first self-review of the exact diff. Fix obvious correctness, regression, security, concurrency, compatibility, and maintainability issues before handoff.
7. Use the configured writer (`managed` or `custom-mcp`) to commit/push and create/update the Implementation PR when available.
8. Put `<!-- agent-bridge:implementation task=TASK-XXXXXX -->` in the PR body.
9. Never merge the PR.
10. If writer capability is missing, do not pretend a push occurred. Produce a patch/artifact and report the capability gap.
11. Do not invoke Work automatically. If a specific operation requires a capability unavailable in Chat, follow the resource-control policy above and wait for explicit user/model approval before any Work delegation.

## Work delegation policy

Work is subordinate to Chat, not a peer primary developer.

Allowed uses after explicit approval include:

- a bounded browser/computer-use or multi-step operation that Chat cannot execute directly;
- a clearly specified automation step whose inputs/outputs are already decided in Chat;
- an optional pre-authorized GitHub event broker that produces only a compact handoff.

Work must not independently redesign the solution, expand scope, choose a higher-cost model, perform primary implementation, or recursively create another Work task.

## Writer modes

Read `references/writer-modes.md`.

- `managed`: a pre-connected write-capable GitHub app/connection authorized once for the permitted repositories.
- `custom-mcp`: a user-provided remote MCP writer. This repository includes the optional `agent-bridge-mcp` adapter.
- `readonly`: planning/patch fallback only.

The stable writer contract permits repository/file/PR reads plus branch, atomic file commit, PR create/update, and PR comments. It forbids merge, secrets, deletion, and admin operations by default.

Writer confirmations are scoped safety attestations. If the writer backend or repository allowlist changes, treat previous write/unattended confirmation as invalid and re-confirm only after the new scope has actually been tested. Use `--clear-write` / `--clear-unattended` if permissions are revoked.

## Codex local review policy

Prefer the persistent watcher installed by:

`agent-bridge service install`

The automatic backend is a systemd user service on Linux, a LaunchAgent on macOS, and a per-user Task Scheduler task on Windows. If service installation is unavailable, `agent-bridge watch` remains the manual fallback.

For each new eligible PR head SHA:

1. Reject cross-repository PRs.
2. Enforce the trusted implementation branch prefix (`ai/` by default).
3. Verify that the implementation PR head descends from the Task's exact pinned base commit before executing PR code.
4. Fetch the exact PR head into an isolated temporary worktree.
5. Run the configured trusted local test commands.
6. Invoke non-interactive `codex exec --ephemeral` for adversarial review of the exact diff and relevant surrounding code.
7. Require structured `APPROVE` or `REVISE` output and validate that JSON locally.
8. Treat actual test output as authoritative; model-reported test results cannot overwrite it.
9. If required tests are missing or fail, do not approve.
10. Post one machine-marked PR comment for that head SHA:
   `<!-- agent-bridge:codex-review task=TASK-XXXXXX verdict=REVISE head=<sha> -->`
11. Deduplicate by exact head SHA using Git-private local state.
12. In long-running mode, record a Git-private heartbeat after each successful poll. `watch --once` must not claim persistent reviewer health.

Do not modify ChatGPT's implementation branch during normal review. A `REVISE` comment routes the task back to the normal ChatGPT Web Chat. An optional Work event broker may summarize that comment, but it must not fix the branch. The watcher reviews the new Chat-produced head automatically.

## Optional event-broker setup

Use `agent-bridge trigger automation-setup` to render the current broker setup instructions.

If the user wants GitHub event notifications/handoffs through Work, configure two **broker-only** event-triggered Work tasks:

1. Task PR opened/ready + `agent-bridge:task` marker → compact implementation handoff for Chat.
2. New PR comment + `agent-bridge:codex-review` + `verdict=REVISE` → compact revision handoff for Chat.

Before saving either broker, show the user the intended Work model/reasoning level and obtain explicit approval. Prefer the least costly option sufficient for event parsing/handoff. If the platform does not expose model selection, disclose that the platform default Work model will be used and ask whether to proceed.

The broker prompt must explicitly prohibit architecture/design work, code edits, tests, writer use, implementation PR writes, recursive Work calls, and model escalation.

After both brokers are actually created and model-approved, run:

`agent-bridge setup work-trigger --confirm`

Then install/start the persistent reviewer:

`agent-bridge service install`

Check it with:

`agent-bridge service status`

Do not trigger a Work task on every implementation commit update; Codex watcher already handles new PR heads.

## Safety and validation

- Run `agent-bridge validate` before publishing `.ai` artifacts.
- Do not place tokens, `.env`, credentials, private keys, or secrets in `.ai/`.
- `agent-bridge setup review --test-command ...` commands are trusted local commands. PR code can execute through tests; use an appropriate local/container/VM environment.
- Service installers use per-user OS facilities and should not require repository-admin, secrets, delete, or machine-admin permissions.
- Keep final merge human-controlled by default.
- Do not set `--confirm-write`, `--confirm-unattended`, or Work-trigger confirmation unless the actual platform behavior has been verified for the current repository scope.
- A Work-trigger confirmation confirms only the bounded broker automation, never permission for primary implementation or future ad-hoc Work runs.
- Do not hide installation commands, model/resource implications, or permission changes from the user.

## References

- `references/bootstrap.md` — one-shot setup and runtime readiness checks.
- `references/cross-platform.md` — Codex App/CLI Skill discovery and OS service backends.
- `references/automation.md` — Chat-first event/broker/review loop.
- `references/writer-modes.md` — managed/MCP/readonly choices and permissions.
- `references/protocol.md` — durable task/handoff state contract.
- `references/security.md` — collaboration-data safety.
