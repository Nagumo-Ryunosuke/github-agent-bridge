# Changelog

## 1.0.0 - 2026-09-04

Initial public release of `github-agent-bridge`.

- Added zero-runtime-dependency `agent-bridge` CLI.
- Added `.ai/` repository protocol for Task, Handoff, Review, Decision, and State artifacts.
- Added commit-pinned task contracts and implementation receipts.
- Added `base_commit` context-drift detection.
- Added explicit workflow state transitions and `next_agent` routing.
- Added commit-pinned review results for ChatGPT/Codex handoffs.
- Added basic secret scanning for AI collaboration artifacts.
- Added JSON Schemas, templates, tests, and GitHub Actions CI.
- Positioned GitHub/Git as the transport and durable source of truth; no browser automation or shared daemon required.
