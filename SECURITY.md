# Security policy

## Supported versions

Only the latest 0.x release gets security fixes.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private vulnerability reporting
(**Security → Report a vulnerability** on the repository), or email speak2jerome@gmail.com with "LLMDyno security"
in the subject. You should hear back within a week.

## Security model, briefly

- LLMDyno binds to `127.0.0.1` by default. It has no user accounts; don't expose it to a network you don't trust.
- API keys are encrypted at rest (Windows DPAPI; owner-only file permissions on Linux) and are only passed to the
  per-run proxy container, never to agent sandboxes.
- Agent sandboxes have no internet access: their only route out is an internal Docker network to their own proxy,
  which enforces spend caps.
- Benchmarks, harness manifests and models you import are code and data from third parties. Review them as you would
  any other download.
