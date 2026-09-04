# Security

The `.ai/` directory is designed to be committed and may therefore be published or shared.

Never store:

- `.env` content
- API keys or access tokens
- passwords
- private keys/certificates
- browser cookies/session tokens
- private session transcripts unless explicitly sanitized
- credentials copied from CI logs

Before committing, run:

```bash
agent-bridge validate
```

The v1.0 scanner is intentionally conservative and cannot guarantee secret detection. Use repository-native secret scanning as an additional defense.
