# Prior art and differentiation

Several projects already provide durable agent handoff or cross-tool session continuity. This project intentionally focuses on a narrower GitHub-native engineering protocol.

## Adjacent approaches

- repository-local agent handoff/state files for Codex and Claude
- Git + Markdown session handoff for multiple coding agents
- file-based GPT planning/review to another execution model
- browser-driven Codex-to-ChatGPT reasoning bridges

## Differentiators

`github-agent-bridge` is centered on:

1. GitHub/repository state as the single source of truth.
2. Task contracts pinned to an exact base commit.
3. Explicit context-drift detection before execution.
4. An implementation handoff pinned to an exact implementation commit.
5. A review pinned to that exact implementation commit.
6. A small machine-readable state machine that tells agents who acts next.
7. A future path to Issues/PR/Checks mirroring without making browser automation the coordination primitive.
