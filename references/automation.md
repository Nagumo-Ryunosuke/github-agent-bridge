# Event-driven automation

The default loop is intentionally asynchronous between products but durable through GitHub events and exact commit identity.

```text
Codex local dispatch
  -> Task PR (agent-bridge:task)
  -> ChatGPT Work event trigger
  -> ChatGPT design + implementation + tests + self-review
  -> Implementation PR (agent-bridge:implementation)
  -> local agent-bridge watcher
  -> trusted tests + codex exec review
  -> APPROVE or REVISE marker comment
  -> REVISE comment triggers ChatGPT Work fix
  -> new PR head SHA triggers Codex review again
```

## Trigger policy

Configure two ChatGPT Work tasks once:

1. PR opened/ready and body contains `agent-bridge:task`: implement the referenced task.
2. New PR comment contains `agent-bridge:codex-review` and `verdict=REVISE`: fix the current implementation PR.

Do not trigger ChatGPT on every implementation commit. The local watcher is responsible for each new implementation PR head and deduplicates by SHA.

## Local watcher

Run `agent-bridge watch` under a user service, supervisor, or another persistent process manager. The watcher:

- only considers open PRs with the implementation marker;
- refuses cross-repository PRs;
- enforces the configured branch prefix (`ai/` by default);
- resolves Task metadata locally or from the deterministic Task branch;
- checks out the exact PR head in a temporary worktree;
- runs trusted configured tests;
- executes Codex non-interactively;
- posts one machine-marked review comment for that head;
- stores deduplication state in Git-private metadata, not committed `.ai/` state.

Human merge remains the default terminal gate.
