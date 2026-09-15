# GitHub writer modes

ChatGPT needs a write-capable path to create implementation branches and PRs. Repository visibility alone is not equivalent to write capability.

## managed

Recommended low-friction mode. The operator connects a GitHub app/connection that actually exposes write actions, scopes it to permitted repositories, tests the capability once, then records that fact with `agent-bridge setup writer --mode managed ...`.

The CLI cannot inspect another ChatGPT session's OAuth grants or confirmation policy. `--confirm-write` and `--confirm-unattended` are explicit operator attestations, not automatic discovery.

## custom-mcp

For advanced/enterprise deployments, provide a remote MCP writer. The optional `agent-bridge-mcp` adapter in this repository uses authenticated `gh` and exposes only the bridge writer contract.

Server-side safety controls:

- `AGENT_BRIDGE_ALLOWED_REPOS` is mandatory;
- write branches default to `ai/` through `AGENT_BRIDGE_BRANCH_PREFIX`;
- text writes are scanned for likely secrets;
- no merge, secrets, repository deletion, or admin tools are exposed.

## readonly

Safe fallback. ChatGPT may plan, review, or produce patches/artifacts, but must not claim that it pushed code or created a PR.

## Stable writer contract

Required semantic actions:

- `get_repository`
- `read_file`
- `list_pull_request_comments`
- `create_branch`
- `commit_files`
- `create_pull_request`
- `update_pull_request`
- `comment_pull_request`

Recommended GitHub permissions are Metadata read, Contents write, Pull Requests write, Issues write, and Actions read.
