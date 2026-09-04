# Protocol

GitHub/Git are the durable source of truth. Chat history is advisory.

## Roles

- dispatcher: Codex
- developer: ChatGPT
- reviewer: Codex
- merger: human by default

## Task identity

Each Task is pinned to `base.branch` and exact `base.commit`. The implementation PR head SHA is the live implementation identity for each review iteration.

## States

`draft -> ready -> claimed -> in_progress -> review_required -> reviewing -> approved -> done`

Alternate transitions include `blocked`, `changes_requested`, and `stale`. A Codex `REVISE` result routes the next action back to ChatGPT and clears first-pass self-review state for the next implementation iteration.

## Machine markers

- Task PR: `<!-- agent-bridge:task task=TASK-XXXXXX -->`
- Implementation PR: `<!-- agent-bridge:implementation task=TASK-XXXXXX -->`
- Codex review comment: `<!-- agent-bridge:codex-review task=TASK-XXXXXX verdict=REVISE head=<sha> -->`

Machine markers are routing metadata; exact Git SHAs remain authoritative.
