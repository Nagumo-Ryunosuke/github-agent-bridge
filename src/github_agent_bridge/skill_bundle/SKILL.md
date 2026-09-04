---
name: github-agent-bridge
description: Coordinate GitHub-mediated development where Codex analyzes and dispatches locally, ChatGPT Web/Work designs and implements, and Codex reviews each implementation PR with real local tests. Use for automated ChatGPT/Codex handoff, Task PR dispatch, exact-SHA review loops, or bridge setup/doctor/service operations.
---

# GitHub Agent Bridge

Use this role split unless the user explicitly overrides it:

- **GitHub**: durable task/context/event transport and exact SHA identity.
- **ChatGPT Web/Work**: architecture, high-quality reasoning, primary implementation, tests, first self-review.
- **Codex**: local requirement reconnaissance, task dispatch, second review, real test execution, debugging and verification.
- **Human**: final merge/acceptance by default.

## Before starting work

1. Work from the real target repository.
2. Run `agent-bridge doctor`.
3. If setup is incomplete, prefer `agent-bridge setup bootstrap` and follow its remediation output.
4. If the watcher service is missing, install it with `agent-bridge service install`.
5. Never claim zero-touch readiness unless `agent-bridge doctor` reports `Zero-touch ready: YES`.

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

Install this Skill for all local Codex surfaces with:

`agent-bridge skill install --scope user`

The installer writes real files to `$HOME/.agents/skills/github-agent-bridge`; this is the Codex USER skill root used by Codex App, CLI and IDE clients.

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
