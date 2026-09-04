# Contributing

Contributions should preserve the core invariant: an agent must be able to recover the current workflow from repository facts without access to another agent's chat history.

## Development

```bash
python3 -m pip install -e .
make check
```

## Protocol changes

Protocol changes should:

1. document backward-compatibility implications;
2. update `references/protocol.md`;
3. update relevant schemas;
4. include tests for state transitions or validation behavior.

Avoid adding service/API dependencies to the core protocol when equivalent Git facts are sufficient.
