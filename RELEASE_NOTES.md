}

# v0.5.0 — IEEE Software Prototype Milestone (2025-12-12)

## Highlights

* **MCP-only HDT interface (Option D)**: HDT capabilities are exposed via MCP tools; REST/OpenAPI is not part of the primary contract.
* **HDT Governor (orchestrator)**:

  * Centralizes source selection, fallback, and error normalization across external systems.
  * Produces consistent HDT-level responses with provenance and structured failure modes.
* **Sources MCP façade (internal)** over external systems:

  * Wraps deterministic connectors (GameBus, Google Fit, SugarVita, Trivia) as MCP tools.
  * Enables capability discovery and uniform invocation via MCP instead of per-client glue code.
* **Structured error envelopes** across sources:

  * `not_connected`, `missing_token`, `upstream_error`, `all_sources_failed` (and similar), rather than silent empty results.
* **Config overlay retained**: merged `config/users.json` + `config/users.secrets.json` remains the canonical way to resolve per-user source credentials and identifiers.
* **Quickstart scripts** to validate the full chain:

  * Sources MCP discovery/invocation, Governor fallback, and external HDT MCP tool calls.

## Breaking Changes

* **REST assumptions removed**: integrations should target MCP tools (external HDT MCP server) rather than HTTP endpoints / OpenAPI.
* **Tool-first contract**: versioned tool names and schemas define compatibility; source-specific API details are hidden behind the Sources MCP façade.
* **Error semantics changed**: callers must handle typed error envelopes (instead of empty lists).

## Known Issues

* Upstream connectivity depends on valid per-source credentials; placeholder tokens will yield `upstream_error`.
* The Governor’s negotiation logic is intentionally minimal (prefer one source, fallback to another). Advanced selection (quality ranking, purpose-aware minimization, source scoring) is not yet implemented.
* Some legacy modules from the REST-bridged architecture may still exist in the repo while the migration completes; Option D entrypoint is `HDT_MCP.server_option_d`.

## Upgrade Notes

* Ensure `connected_application` + `player_id` pairs match between `config/users.json` and `config/users.secrets.json`; otherwise secrets will not merge onto public connectors.
* Keep the Sources MCP server internal (stdio transport) and avoid exposing it on untrusted networks.
* If you previously relied on policy lanes/vault/telemetry from the earlier milestone branch, reintroduce them as Governor-enforced mechanisms and/or dedicated MCP tools as the Option D migration progresses.
