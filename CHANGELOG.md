# Changelog

## 1.4.0 - 2026-09-04

Made the Codex side portable across App/CLI/IDE surfaces and added cross-platform persistent watcher service management.

- Added `agent-bridge skill install|status|uninstall` with `user` and `repo` scopes.
- User Skill installation writes real files to `$HOME/.agents/skills/github-agent-bridge`, allowing Codex App, CLI and IDE clients to share the same Skill discovery scope.
- Bundled `SKILL.md`, `agents/openai.yaml`, and portable references inside the Python wheel so Skill installation works from an installed package instead of requiring a source checkout.
- Migrated `agents/openai.yaml` to the current `interface` / `policy` metadata structure for desktop Codex UI compatibility.
- Added `agent-bridge service install|status|restart|uninstall`.
- Linux uses a per-user `systemd --user` unit; macOS uses a LaunchAgent; Windows uses a per-user Task Scheduler task with LIMITED run level.
- Service definitions use the Python interpreter that installed the service and refuse installation if that interpreter cannot import `github_agent_bridge`.
- Each repository gets an independent service identity and log/state directory so one user can watch multiple repositories.
- Kept watcher heartbeat/`agent-bridge doctor` as the authoritative runtime readiness signal rather than trusting localized service-manager status alone.
- Added cross-platform service/Skill tests and expanded GitHub Actions from Linux-only to Windows, macOS, and Linux across Python 3.9/3.11/3.13.
- Added wheel checks that verify the packaged Skill assets are actually present.

## 1.3.0 - 2026-09-04

Reduced the remaining one-time setup burden and added an explicit runtime zero-touch readiness gate.

- Added `agent-bridge setup bootstrap` to configure writer mode, repository allowlist, Codex review commands, test policy, and Work-trigger confirmation in one pass.
- Bootstrap automatically infers the current `owner/repo` from a github.com `origin` when `--repository` is omitted and preserves existing setup on repeated runs.
- Added `agent-bridge setup work-trigger --confirm|--clear` to persist the one platform step that cannot currently be created through a public CLI/API.
- Work-trigger confirmation is bound to the configured repository scope instead of being a global boolean.
- Writer write/unattended confirmations are invalidated when writer backend or repository scope changes and can be explicitly revoked with `--clear-write` / `--clear-unattended`.
- Added `agent-bridge doctor` with human-readable and JSON diagnostics.
- Doctor validates bridge initialization, github.com origin, `gh` installation/authentication, actual `gh` repository access, Codex CLI availability, writer/write-unattended readiness, repository allowlisting, repository-scoped ChatGPT Work trigger confirmation, authoritative local test policy, implementation branch prefix, and the human merge safety gate.
- Added a Git-private heartbeat written only by the long-running Codex watcher; stale/missing watcher heartbeat prevents `zero_touch_ready=true`. `watch --once` intentionally does not claim service health.
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
