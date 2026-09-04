# Automation loop

The intended steady-state loop is:

```text
Codex local analysis
  -> Task contract pinned to exact base SHA
  -> GitHub Task PR
  -> ChatGPT Work event trigger
  -> ChatGPT design + implementation + tests + self-review
  -> marked Implementation PR
  -> persistent local Codex watcher
  -> exact-SHA local tests + structured review
  -> APPROVE -> human merge
     REVISE  -> GitHub machine-marked comment -> ChatGPT Work fix -> new head -> Codex re-review
```

The watcher deduplicates exact PR head SHAs in Git-private state. It does not rely on the current working tree's committed task state when a task contract can be recovered from GitHub refs.

Run `agent-bridge doctor` after initial setup. `Zero-touch ready: YES` is the readiness gate for unattended operation.
