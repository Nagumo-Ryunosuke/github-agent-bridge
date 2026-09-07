# Automation loop

The intended steady-state loop keeps development reasoning in a normal ChatGPT Web Chat and uses Work only as an optional bounded event broker:

```text
Codex local analysis
  -> Task contract pinned to exact base SHA
  -> GitHub Task PR
  -> optional ChatGPT Work event broker
  -> compact handoff
  -> normal ChatGPT Web Chat design + implementation + tests + self-review
  -> marked Implementation PR
  -> persistent local Codex watcher
  -> exact-SHA local tests + structured review
  -> APPROVE -> human merge
     REVISE  -> GitHub machine-marked comment -> optional Work broker -> Chat fix -> new head -> Codex re-review
```

Work must not become the primary planner/developer. Event-triggered Work may read only enough task/PR metadata to prepare the handoff; it must not design, edit code, run broad tests, use the writer, or create/update the implementation PR.

A normal ChatGPT Web Chat must never invoke Work automatically. Before any ad-hoc Work delegation, Chat must explain the capability gap and bounded operation, ask the user whether Work may be used, and ask which model/reasoning level to use when selectable. If model selection is unavailable, Chat must disclose that the platform default Work model would be used and wait for explicit approval.

For persistent event brokers, obtain the user's model/reasoning approval when the trigger is created and prefer the least costly option capable of reliable event parsing/handoff. Do not default to the newest or strongest model.

The watcher deduplicates exact PR head SHAs in Git-private state. It does not rely on the current working tree's committed task state when a task contract can be recovered from GitHub refs.

Run `agent-bridge doctor` after initial setup. `Zero-touch ready: YES` means the configured transport/review automation checks pass; it does not authorize Work to perform primary implementation or remove the normal Chat development step.
