# Protocol v1

## Goal

Allow independent agents such as ChatGPT Web and Codex to collaborate through durable repository state without shared chat history.

## Source of truth

Priority order:

1. Git commit / branch / PR / CI facts
2. `.ai/state/tasks.json`
3. Task, handoff, review, ADR artifacts
4. Agent chat history

## Task lifecycle

```text
draft -> ready -> claimed -> in_progress -> review_required -> reviewing
                                   ^             |              |
                                   |             |              +-> changes_requested -> in_progress
                                   |             +-----------------> approved -> done
                                   +-> blocked -> in_progress

Any active task may become stale when its pinned context is no longer safe.
```

## Task contract

A task must identify:

- `task_id`
- title/objective
- requested/assigned agent
- status
- priority
- base branch and exact base commit
- target branch when known
- acceptance criteria

The Markdown task is for humans/agents. `.ai/state/tasks.json` is the machine-readable index.

## Implementation handoff

A handoff must identify:

- task id
- agent
- base commit
- implementation commit
- implementation branch
- PR when available
- summary
- validation evidence
- remaining risks/questions

## Review contract

A review must identify:

- task id
- reviewer
- exact reviewed commit
- result (`approve` or `request-changes`)
- findings and required changes

A reviewer must not approve a commit different from the implementation commit currently recorded in state.

## GitHub-native evolution

v1.0 stores the protocol in Git-tracked files. Later versions may mirror state into GitHub Issues, PR labels, Checks, and Actions, but repository files remain portable across hosting providers.
