# github-agent-bridge

A GitHub transport bridge for durable, commit-pinned collaboration between ChatGPT Web, Codex, and other coding agents.

> Chat history is temporary. Repository state is durable.

`github-agent-bridge` uses GitHub/Git as the transport and source of truth between AI agents that do not share a runtime or conversation history. ChatGPT Web can publish plans and reviews through GitHub; Codex can consume those artifacts with normal Git tooling, implement code, and publish commit-pinned handoffs back for review.

## Why

Cross-agent workflows commonly fail because one model plans against an old snapshot, another agent changes the repository, and the reviewer cannot tell exactly what was implemented. Browser automation can relay messages, but it is fragile and difficult to audit.

The bridge intentionally avoids browser automation, a shared daemon, or a proprietary relay. Git/GitHub remain the durable source of truth:

```text
ChatGPT (plan / architecture)
        |
        v
  Task @ base_commit
        |
        v
      GitHub
        |
        v
Codex (implement / test)
        |
        v
 Handoff @ impl_commit
        |
        v
      GitHub PR
        |
        v
ChatGPT (review exact commit)
        |
        +---- request changes ---> Codex
        |
        +---- approve -----------> Human / merge
```

## Why this bridge exists

This is not a generic session transcript exporter or a full multi-agent control plane. v1.0 focuses on a narrow cross-product transport contract:

- GitHub/repository state as the source of truth
- tasks pinned to exact `base_commit`
- explicit context-drift detection
- implementation handoffs pinned to exact commits
- reviews pinned to the implementation commit
- a workflow state that declares `next_agent`
- compatibility with GitHub Issues/PRs as the natural transport layer

See `references/prior-art.md`.

## Repository layout after initialization

```text
.ai/
├── README.md
├── context/
│   ├── project.md
│   ├── architecture.md
│   └── constraints.md
├── tasks/
├── handoffs/
├── reviews/
├── decisions/
└── state/
    └── tasks.json
```

## Install locally

```bash
python3 -m pip install -e .
agent-bridge --help
```

Or install the Skill folder with Codex's skill installer after this repository is published.

## Quick start

Initialize a repository:

```bash
cd your-project
agent-bridge init
```

Create a task (typically ChatGPT/planner):

```bash
agent-bridge task create \
  --title "Refactor tag synchronization" \
  --objective "Unify scheduled sync, manual repair, and reconciliation." \
  --assigned-to codex \
  --priority high \
  --target-branch codex/tag-sync-v2
```

Codex checks context drift before implementing:

```bash
agent-bridge status
agent-bridge drift TASK-000001
agent-bridge task claim TASK-000001 --agent codex
agent-bridge task start TASK-000001
```

After implementation:

```bash
agent-bridge task finish TASK-000001 \
  --commit <implementation-sha> \
  --branch codex/tag-sync-v2 \
  --pr 42 \
  --summary "Unified tag synchronization and added tests."
```

Reviewer records a commit-pinned result:

```bash
agent-bridge review TASK-000001 \
  --result approve \
  --commit <implementation-sha> \
  --summary "Implementation satisfies the task contract."
```

Validate before commit/push:

```bash
agent-bridge validate
```

## v1.0 scope

Included:

- Codex-compatible `SKILL.md`
- zero-runtime-dependency Python CLI
- `.ai/` initialization
- task creation/state machine
- base-commit pinning and drift reporting
- implementation handoff files
- commit-pinned reviews
- basic secret scanning
- tests

Planned:

- richer GitHub Issues/PR label mirroring
- GitHub Checks/Actions integration
- automatic PR metadata synchronization
- stale-task policy based on affected paths
- multi-agent routing policies
- signed/verified handoff receipts

## License

MIT
