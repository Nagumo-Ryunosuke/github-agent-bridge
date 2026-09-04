---
name: github-agent-bridge
description: Automate GitHub-mediated development where Codex locally analyzes and dispatches, ChatGPT Web/Work designs and implements, and Codex reviews each implementation PR with real tests. Use for automated ChatGPT/Codex handoff, Task PR dispatch, exact-SHA review loops, zero-touch setup, or cross-platform Codex App/CLI watcher service management.
---

# GitHub Agent Bridge

Treat this role split as the default architecture:

- **GitHub** = communication, durable context, PR/event transport, exact SHA identity.
- **ChatGPT Web/Work** = architecture, high-quality reasoning, primary code implementation, test authoring, first self-review.
- **Codex** = local repository reconnaissance/dispatch, second review, real test execution, debugging, adversarial verification.
- **Human** = final merge/acceptance.

Do not silently invert these roles. Codex should not become the primary implementer unless ChatGPT write capability is unavailable or the user explicitly asks for a local fallback.

## Codex App / CLI portability

This Skill is intended to behave the same from Codex App, Codex CLI, and Codex IDE clients.

Prefer a user installation so every local Codex surface can discover the same Skill:

`agent-bridge skill install --scope user`

The installer writes real files to `$HOME/.agents/skills/github-agent-bridge`, the Codex USER Skill root. Restart Codex if a newly installed Skill is not visible immediately.

For repository-only distribution, use:

`agent-bridge skill install --scope repo`

Read `references/cross-platform.md` for OS-specific service behavior.

## On a new development request in Codex

1. Inspect the real local repository, relevant instructions, tests, architecture, and constraints.
2. If the bridge has not been configured, prefer `agent-bridge setup bootstrap` over asking the user to edit `.ai/config.json` manually.
3. Run `agent-bridge doctor`. Treat `zero_touch_ready=false` as a setup/capability issue; do not claim the unattended loop is operational until critical checks pass.
4. Summarize the task into a narrow implementable contract; do not spend tokens implementing the full change yet.
5. Create a commit-pinned task with ChatGPT as developer and Codex as reviewer.
6. Run `agent-bridge drift <TASK>` before dispatch. Treat code drift as a replanning signal; `.ai/`-only drift is metadata and may be safe.
7. Run `agent-bridge validate`.
8. Publish automatically with `agent-bridge publish task <TASK>` rather than asking the user to manually create a PR.
9. Stop local implementation work and let the GitHub event-triggered ChatGPT Work task take ownership.

## ChatGPT Work implementation policy

When a Task PR event wakes ChatGPT:

1. Read the Task PR, `.ai/tasks/<TASK>.md`, context, repository instructions, and exact pinned base.
2. Use the highest suitable available reasoning model; never hard-code one historical model name into the protocol.
3. Design the solution before editing.
4. Create the implementation branch from the **exact pinned base commit**, not simply from the current branch head.
5. Implement the change and tests.
6. Perform a first self-review of the exact diff. Fix obvious correctness, regression, security, concurrency, compatibility, and maintainability issues before handoff.
7. Use the configured writer (`managed` or `custom-mcp`) to commit/push and create/update the Implementation PR.
8. Put `<!-- agent-bridge:implementation task=TASK-XXXXXX -->` in the PR body.
9. Never merge the PR.
10. If writer capability is missing, do not pretend a push occurred. Produce a patch/artifact and report the capability gap.

## Writer modes

Read `references/writer-modes.md`.

- `managed`: a pre-connected write-capable GitHub app/connection authorized once for the permitted repositories. The standard read-oriented GitHub app alone is not sufficient.
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

Do not modify ChatGPT's implementation branch during normal review. A `REVISE` comment should route control back to ChatGPT Work, which fixes the PR and pushes a new head. The watcher then reviews the new head automatically.

## One-time automation setup

Prefer:

`agent-bridge setup bootstrap ...`

The CLI can configure and verify the local/GitHub side, but ChatGPT Work event-triggered tasks currently require one interactive creation step on ChatGPT Web/iOS/Android. Desktop can view existing triggers but cannot currently create/edit their trigger conditions.

Create two event-triggered ChatGPT Work tasks:

1. Task PR opened/ready + `agent-bridge:task` marker → implementation workflow.
2. New PR comment + `agent-bridge:codex-review` + `verdict=REVISE` → fix workflow.

After both are created, run:

`agent-bridge setup work-trigger --confirm`

Then install/start the persistent reviewer:

`agent-bridge service install`

Check it with:

`agent-bridge service status`

Once the watcher has emitted a fresh heartbeat, require:

`agent-bridge doctor`

before claiming zero-touch operation is ready. Work-trigger confirmation must match the current repository scope.

Do not trigger ChatGPT on every implementation commit update; Codex watcher already handles new PR heads. This prevents duplicate ChatGPT jobs and unnecessary usage.

## Safety and validation

- Run `agent-bridge validate` before publishing `.ai` artifacts.
- Do not place tokens, `.env`, credentials, private keys, or secrets in `.ai/`.
- `agent-bridge setup review --test-command ...` commands are trusted local commands. PR code can execute through tests; use an appropriate local/container/VM environment.
- Service installers use per-user OS facilities and should not require repository-admin, secrets, delete, or machine-admin permissions.
- Keep final merge human-controlled by default.
- Do not set `--confirm-write`, `--confirm-unattended`, or Work-trigger confirmation unless the actual platform behavior has been verified for the current repository scope.

## References

- `references/bootstrap.md` — one-shot setup and runtime zero-touch readiness checks.
- `references/cross-platform.md` — Codex App/CLI Skill discovery and OS service backends.
- `references/automation.md` — end-to-end event loop.
- `references/writer-modes.md` — managed/MCP/readonly choices and permissions.
- `references/protocol.md` — durable task/handoff state contract.
- `references/security.md` — collaboration-data safety.
