# Event-driven automation

The default loop is intentionally asynchronous between products but durable through GitHub events and exact commit identity. ChatGPT Web Chat owns development reasoning; Work is optional and broker-only.

```text
Codex local dispatch
  -> Task PR (agent-bridge:task)
  -> optional ChatGPT Work event broker
  -> compact task handoff
  -> normal ChatGPT Web Chat design + implementation + tests + self-review
  -> Implementation PR (agent-bridge:implementation)
  -> local agent-bridge watcher
  -> trusted tests + codex exec review
  -> APPROVE or REVISE marker comment
  -> optional Work broker prepares revision handoff
  -> normal ChatGPT Web Chat fixes the PR
  -> new PR head SHA triggers Codex review again
```

## Trigger policy

If GitHub event-triggered Work tasks are enabled, configure exactly two bounded brokers:

1. PR opened/ready and body contains `agent-bridge:task`: identify the task and prepare a compact handoff for a normal ChatGPT Web Chat.
2. New PR comment contains `agent-bridge:codex-review` and `verdict=REVISE`: identify the reviewed head/findings and prepare a compact revision handoff for Chat.

The Work broker must not design, implement, edit files, run broad tests, use the writer, create/update an implementation PR, or delegate to another Work task.

### Resource and model gate

ChatGPT Web Chat must never invoke Work automatically. Task complexity is not permission to switch surfaces.

Before any ad-hoc Chat-to-Work delegation:

1. Explain the capability gap that Chat cannot handle directly.
2. Describe the exact bounded operation proposed for Work.
3. Ask the user whether Work may be used.
4. Ask which model/reasoning level to use when the platform exposes that choice.
5. If model selection is unavailable, disclose that the platform default Work model would be used and obtain explicit approval before proceeding.

For persistent GitHub event brokers, model approval happens when the trigger is created. Prefer the least costly model/reasoning level that can reliably parse the event and prepare the handoff. Never select the newest/strongest model merely because it is available.

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
