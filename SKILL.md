---
name: github-agent-bridge
description: Coordinate ChatGPT, Codex, and other coding agents through a GitHub repository using commit-pinned task contracts, durable handoff reports, review artifacts, and a machine-readable workflow state. Use when agents need to exchange plans, implementation results, blockers, or reviews without relying on shared chat history; when a task must be pinned to an exact branch/commit; or when the user wants GitHub to be the single source of truth for cross-agent work.
---

# GitHub Agent Bridge

Use Git and repository-local `.ai/` files as the durable coordination layer between independent AI agents.

## Core rules

1. Treat repository state, exact commit SHAs, PRs, and CI as authoritative. Chat history is advisory only.
2. Before acting on a task, read `.ai/state/tasks.json`, the task file, relevant `.ai/context/*`, and repository-local instructions such as `AGENTS.md`.
3. Never implement a task before checking its pinned `base.commit` against the current base branch. Run `agent-bridge drift TASK-XXXXXX`.
4. Never review an implementation without anchoring the review to the exact implementation commit.
5. Every implementation that requests review must create a handoff report.
6. Never silently overwrite another agent's conclusion. Add a new task, handoff, review, or ADR instead.
7. Do not put credentials, tokens, `.env` contents, private keys, or unnecessary private data into `.ai/`.
8. Run `agent-bridge validate` before committing collaboration artifacts.

## Startup workflow

1. Verify the CLI exists: `agent-bridge --help`.
2. Run `agent-bridge status`.
3. Read the task whose `next_agent` matches the current agent.
4. Read `.ai/context/constraints.md` and any relevant architecture/project context.
5. Run `agent-bridge drift <TASK_ID>` before implementation or review.

## ChatGPT planning workflow

When ChatGPT is responsible for architecture/planning:

1. Inspect current repository facts before writing the task.
2. Create a task with an explicit objective, assigned agent, and target branch when known:
   `agent-bridge task create --title "..." --objective "..." --assigned-to codex --target-branch codex/...`
3. Expand `.ai/tasks/<TASK_ID>.md` with concrete requirements, constraints, acceptance criteria, and deliverables.
4. Commit/push the task artifact so Codex can retrieve it from GitHub.

## Codex implementation workflow

1. Run `agent-bridge status` and locate a ready task assigned to Codex.
2. Run `agent-bridge drift <TASK_ID>`. If drift affects relevant files, stop and mark the task stale or request replanning rather than blindly implementing an old plan.
3. Claim and start the task:
   `agent-bridge task claim <TASK_ID> --agent codex`
   `agent-bridge task start <TASK_ID>`
4. Implement and validate locally.
5. Commit the implementation and preferably open a PR.
6. Record the handoff:
   `agent-bridge task finish <TASK_ID> --commit <SHA> --branch <BRANCH> --pr <N> --summary "..."`
7. Enrich the handoff file with exact validation commands, high-signal changed files, risks, and reviewer questions.
8. Run `agent-bridge validate`, then commit/push the handoff/state update.

## ChatGPT review workflow

1. Read the task, implementation handoff, PR/diff, and CI evidence.
2. Confirm the implementation commit equals the commit recorded in task state.
3. Review that exact commit.
4. Record one result:
   - approve: `agent-bridge review <TASK_ID> --result approve --commit <SHA> --summary "..."`
   - request changes: `agent-bridge review <TASK_ID> --result request-changes --commit <SHA> --summary "..."`
5. Add concrete Critical/Major/Minor findings to the review artifact.
6. Commit/push the review/state update.
7. After human merge/acceptance, use `agent-bridge task complete <TASK_ID>`.

## Context drift

A task is pinned to a base branch and commit. If the base branch advances, `agent-bridge drift` reports the new commit and files changed since task creation. Treat drift in files relevant to the task as a replanning signal.

## References

- Read `references/protocol.md` for the state machine and artifact contract.
- Read `references/security.md` before exposing private repositories or generating shared context.
- Read `references/prior-art.md` when evaluating overlap with other handoff skills.
