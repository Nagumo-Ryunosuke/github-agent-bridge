# Changelog

## 1.3.0 - 2026-09-04

Reduced the remaining one-time setup burden and added an explicit zero-touch readiness gate.

- Added `agent-bridge setup bootstrap` to configure writer mode, repository allowlist, Codex review commands, test policy, and Work-trigger confirmation in one pass.
- Bootstrap automatically infers the current `owner/repo` from a github.com `origin` when `--repository` is omitted.
- Added `agent-bridge setup work-trigger --confirm|--clear` to persist the one platform step that cannot currently be created through a public CLI/API.
- Added `agent-bridge doctor` with human-readable and JSON diagnostics.
- Doctor validates bridge initialization, github.com origin, `gh` installation/authentication, Codex CLI availability, writer/write-unattended readiness, repository allowlisting, ChatGPT Work trigger confirmation, authoritative local test policy, implementation branch prefix, and the human merge safety gate.
- Added aggregate `zero_touch_ready` status so automation can refuse to claim a fully unattended workflow before all critical capabilities are present.
- Updated Work-trigger instructions to reflect that event-triggered tasks are created on ChatGPT Web/iOS/Android; desktop can view existing tasks but cannot currently create/edit trigger conditions.
- Tightened repository configuration validation and config schema coverage.

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
