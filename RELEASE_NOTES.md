# v0.5.0 — IEEE Software Prototype Milestone (2025-12-12)

## Highlights
- **Light Domain Layer** (ports/services) so MCP tools are adapter-agnostic.
- **MCP façade** with domain-shaped tools:
  - `hdt.walk.stream@v1`, `hdt.walk.stats@v1`, `behavior_strategy@v1`, plus data tools.
- **Policy lanes** (analytics/modeling/coaching) with field redaction & deny support.
- **Vault** integration (read-mostly, write-through) + maintenance tool.
- **Telemetry** JSONL with request correlation and redaction counts.
- **API hardening**: stable ETag/304, pagination headers, merged `users.json` + `users.secrets.json`.
- **Quickstart** docs, sample `config/*.json`, `.env.example`.
- **CI/pre-commit** hooks: pytest smoke, basic hygiene.

## Breaking Changes
- Domain-first JSON shapes on MCP tools; adapters should be wrapped via domain ports.

## Known Issues
- Only a single concrete walk adapter is wired by default; others are stubs.
- Coaching tool uses a lightweight strategy; LLM client remains optional.

## Upgrade Notes
- Review `config/policy.json` examples before enabling redactions/denies in production-like runs.
- Install dev tooling: `pip install -e .[dev]` to satisfy pre-commit hooks.
