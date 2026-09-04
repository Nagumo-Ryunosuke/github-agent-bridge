# Changelog

## 1.2.0 - 2026-09-04

Shifted the bridge to the target developer/reviewer split and added event-driven automation.

- Made ChatGPT the default primary developer and Codex the default local reviewer.
- Added ChatGPT first-pass self-review gating before handoff.
- Added managed, custom-MCP, and readonly GitHub writer modes with explicit capability/unattended confirmation.
- Added a stable least-privilege writer contract that excludes merge, secrets, deletion, and admin actions.
- Added optional `agent-bridge-mcp` GitHub Writer MCP with exact-SHA branch creation, atomic multi-file commits, mandatory repository allowlisting, branch-prefix enforcement, and secret scanning.
- Added one-time ChatGPT Work event-trigger setup prompts for Task PRs and Codex `REVISE` comments.
- Added isolated, retry-safe `agent-bridge publish task` automation so Codex can dispatch without changing the user's current worktree.
- Added Implementation PR and Codex review machine markers.
- Added local Codex watcher with exact PR-head SHA deduplication stored in Git-private state and GitHub Task-branch fallback when local task state is absent.
- Added cross-repository and trusted-branch-prefix execution guards.
- Added real local test-command execution and structured `codex exec --ephemeral` review.
- Added local JSON validation and made actual test evidence authoritative over model-reported results.
- Blocked unattended approval when required local tests are missing or failing.
- Added metadata-only context-drift classification.
- Added `agent-bridge setup review` for no-edit test configuration.

## 1.0.0 - 2026-09-04

Initial public release of `github-agent-bridge` with commit-pinned Task/Handoff/Review state, drift detection, secret scanning, JSON Schemas, CLI, tests, and CI.
