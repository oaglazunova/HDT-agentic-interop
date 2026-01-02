# HDT v0.5.0 (2025-12-12)

## Highlights

* **MCP-only HDT interface**: HDT capabilities are exposed via MCP tools; REST is not part of the primary integration contract.
* **External HDT MCP server** (`hdt_mcp.gateway`):

  * Domain-first tool surface (`hdt.walk.fetch.v1`, `hdt.trivia.fetch.v1`, `hdt.sugarvita.fetch.v1`, `hdt.sources.status.v1`).
  * Per-call instrumentation: **purpose-lane validation**, **policy pre-check (deny fast)**, **policy redaction on success**, and **telemetry logging**.
* **HDT Governor (orchestrator)** (`hdt_mcp.governor.HDTGovernor`):

  * Centralizes **source selection**, **fallback**, and **error normalization** across external systems.
  * Produces consistent HDT-level responses with:

    * `selected_source`
    * `attempts` (negotiation trace)
    * structured failure modes
  * Optional vault strategy via `prefer_data=auto|vault|live` and write-through behavior on successful live fetches (best effort).
* **Sources MCP façade (internal)** (`hdt_sources_mcp.server`):

  * Wraps connectors as MCP tools:

    * GameBus walk, Google Fit walk, GameBus Trivia, GameBus SugarVita
  * Uniform typed errors from all source tools (`unknown_user`, `not_connected`, `missing_token`, `upstream_error`, etc.).
* **End-to-end observability**:

  * Correlation id (`corr_id`) is propagated across **MCP Server → Governor → Sources MCP** to support traceability.
  * Telemetry is emitted as JSONL records, including governor negotiation traces.
* **Config overlay retained**:

  * Merged `config/users.json` + `config/users.secrets.json` remains the canonical way to resolve per-user source identifiers and credentials.
* **Quickstart scripts** validate the full chain:

  * Sources MCP discovery/invocation, Governor fallback, and external HDT MCP tool calls.

## Known Issues

* Upstream connectivity depends on valid per-source credentials; placeholder tokens will yield `upstream_error`.
* The Governor’s negotiation logic is intentionally minimal (prefer one source, fallback to another; optional vault preference/fallback). Advanced selection (quality ranking, purpose-aware minimization, source scoring) is not yet implemented.
* Telemetry/logging is suitable for debugging and demos, but not yet hardened for production (e.g., retention, privacy guarantees beyond basic sanitization, configurable sinks).
