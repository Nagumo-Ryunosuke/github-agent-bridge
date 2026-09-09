# AI Collaboration State

GitHub is the durable transport and source of truth. ChatGPT is the primary planner/developer; Codex is the local reviewer and test executor.

- `context/`: durable project context
- `tasks/`: commit-pinned task contracts
- `handoffs/`: implementation reports
- `reviews/`: commit-pinned review results
- `state/`: machine-readable workflow state
- `config.json`: role, writer, trigger, and local-review configuration
