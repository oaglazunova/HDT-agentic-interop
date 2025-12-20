# HDT v0.5.0 (2025-12-12)

## Highlights

* **MCP-only architecture**: the HDT is exposed exclusively via MCP tools; REST is no longer a required integration surface.
* **HDT Governor (orchestrator)**:
  * Central decision point for source selection, fallback, and error normalization.
  * Executes tool calls; returns structured results with provenance.
* **Sources MCP façade (internal)**:
  * External systems are wrapped as MCP tools (e.g., GameBus, Google Fit, SugarVita, Trivia) using the existing fetchers/parsers.
  * Enables capability discovery and uniform invocation via MCP rather than bespoke per-client glue.
* **Domain-first tool surface (external)**:
  * HDT-level tools expose capabilities (e.g., walking, diabetes/trivia) without leaking source-specific API details.
* **Structured errors and observability**:
  * All source failures are returned as typed error envelopes (e.g., `not_connected`, `missing_token`, `upstream_error`, `all_sources_failed`) instead of silent empty results.
  * Basic provenance included in tool responses to support debugging and auditing.

## Architecture Overview

* **External interface**: `hdt_mcp.gateway` (HDT MCP server)
  * Exposes HDT-level tools to external agents/clients.
  * Delegates execution to the **HDT Governor**.
* **Internal source interface**: `hdt_sources_mcp.server` (Sources MCP server)
  * Exposes source-specific tools (GameBus/Google Fit/SugarVita/Trivia).
  * Reads connection configuration via merged `config/users.json` + `config/users.secrets.json`.
* **Connectors** (internal implementation detail): provider-specific fetch/parse code lives inside `hdt_sources_mcp` (e.g., `hdt_sources_mcp/core_infrastructure/*`). The external HDT surface remains MCP-only.

## Architecture at a glance
![Architecture-2025-11-20-102953.png](architecture.jpg)

---

## Quickstart (reproducible local run)

### Prerequisites
- Python **3.11+** (tested locally with Python 3.14)
- Git
- (Windows) `py` launcher recommended

### 1) Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
py -V:3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
````

**Windows (Git Bash):**

```bash
py -V:3.14 -m venv .venv
source .venv/Scripts/activate
python --version
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python --version
```

### 2) Install dependencies (editable + dev tools)

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

### 3) Configure users and secrets

This repository expects:

* `config/users.json` (non-secret configuration)
* `config/users.secrets.json` (tokens/credentials; **do not commit**)

If you don’t have configs yet, generate templates:

```bash
python scripts/init_sample_config.py
```

Then edit:

* `config/users.json`
* `config/users.secrets.json`

Important merge rule:

* Identity fields must match across public and secret entries (e.g., `connected_application` + `player_id`) so the overlay merges correctly.
[demo_quickstart.ps1](scripts/demo_quickstart.ps1)
### 4) Run the test suite (canonical validation)

```bash
python -m pytest -q
```

If this passes, your local environment and tool contracts are consistent.

### 5) Run a local end-to-end demo

Run the Option D walk demo:

```bash
python scripts/demo_option_d_walk.py
```

(Optional) Run the MCP smoke script:

```bash
python scripts/smoke_mcp.py
```

### 6) Enable repo quality gates (recommended for contributors)

Install hooks:

```bash
python -m pip install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
```

Run locally once:

```bash
pre-commit run -a
pre-commit run -a --hook-stage pre-push
```

---

## Running the MCP Servers

This repository implements **MCP-only** using **two MCP servers**:

1. **External-facing HDT MCP server**
   Module: `python -m hdt_mcp.gateway`
   Purpose: exposes *domain-level* HDT tools to external agents/clients.

2. **Internal Sources MCP server**
   Module: `python -m hdt_sources_mcp.server`
   Purpose: wraps external systems (GameBus, Google Fit, SugarVita, Trivia) as MCP tools, using fetchers.

The HDT MCP server calls the Sources MCP server internally via a local stdio MCP client (it spawns it as a subprocess).

### Transport modes

* `stdio` (recommended for local dev and demos): MCP messages flow over standard input/output.
  This is ideal for “spawn a server as a subprocess” (internal Sources MCP) and for local testing.
* `streamable-http` (optional): used if you want a network-accessible MCP endpoint.
  Only use this for the **external-facing** server, and only after adding authentication.

### A) Start the external HDT MCP server

PowerShell:

```powershell
$env:MCP_TRANSPORT="stdio"
python -m hdt_mcp.gateway
```

If you prefer `streamable-http` (optional):

```powershell
$env:MCP_TRANSPORT="streamable-http"
python -m hdt_mcp.gateway
```

Notes:

* In `stdio` mode you typically do not “see” a friendly banner. It is meant to be driven by an MCP client (scripts/tests).
* The recommended way to validate behavior is to run `python scripts/demo_option_d_walk.py`.

### B) Start the internal Sources MCP server (usually not started manually)

You normally do **not** run Sources MCP directly, because the HDT MCP client spawns it automatically.

If you want to run it explicitly (debugging):

```powershell
$env:MCP_TRANSPORT="stdio"
python -m hdt_sources_mcp.server
```

### C) Validate everything works (recommended)

Run the demo:

```powershell
python scripts\demo_option_d_walk.py
```

Run the full test suite:

```powershell
python -m pytest -q
```

### D) Common environment variables

* `MCP_TRANSPORT`: `stdio` (default) or `streamable-http`
* `MCP_CLIENT_ID`: identifier for policy/telemetry attribution (e.g., `MODEL_DEVELOPER_1`)
* `HDT_VAULT_ENABLE`: `1` to enable vault read-through/write-through
* `HDT_VAULT_PATH`: location of the vault DB file (e.g., `./data/hdt_vault.sqlite`)
* `HDT_TELEMETRY_DIR`: directory for telemetry JSONL output
* `HDT_DISABLE_TELEMETRY`: `1` to disable telemetry logging

---

## Architecture (Detailed)

### Why two MCP servers?

The design separates the problem into two layers:

* **External MCP contract (domain-first):** what external clients/agents see and call.
* **Internal MCP contract (source-first):** how the HDT interacts with external systems in a uniform way.

This prevents the external tool surface from leaking GameBus/Google Fit/SugarVita implementation details and lets you evolve source connectors independently.

### Components

#### 1) HDT MCP Server — `hdt_mcp.gateway`

Role:

* The **only** supported integration surface for external clients.
* Exposes **domain-level tools** such as:

  * `hdt.walk.fetch@v1`
  * `hdt.trivia.fetch@v1`
  * `hdt.sugarvita.fetch@v1`
  * `hdt.sources.status@v1`

What it does on each tool call:

1. Creates a **correlation id** (`corr_id`) for end-to-end tracing.
2. Validates request parameters (including `purpose` lane).
3. Performs **policy pre-check** (deny fast, avoid upstream calls).
4. Delegates execution to the Governor.
5. Applies **policy redaction** (`apply_policy_safe`) on successful payloads.
6. Writes telemetry (`log_event`) with:

   * tool name
   * args (sanitized)
   * policy meta (allowed/redactions)
   * `corr_id`
   * duration (ms)

#### 2) HDT Governor — `hdt_mcp.mcp_governor.HDTGovernor`

Role:

* Orchestration and deterministic “negotiation rules.”
* Converts multiple source/tool outcomes into one normalized response envelope.
* Produces the **negotiation trace** via `attempts`.

Key behaviors:

* **Source preference + fallback** (walk):

  * try preferred live source (`gamebus` or `googlefit`)
  * fallback to the other on typed errors
* **Vault strategy** (`prefer_data`):

  * `prefer_data="vault"`: vault-only (demos)
  * `prefer_data="live"`: live-only (fail if upstream fails)
  * `prefer_data="auto"`: vault-first or vault-fallback (depending on implementation)
* **Write-through**:

  * after successful live fetch, upsert into vault (best effort)

Outputs:

* Always returns structured dicts:

  * success payload includes `selected_source` and `attempts`
  * failure payload uses typed error envelope + `details` attempt list

#### 3) Sources MCP Server — `hdt_sources_mcp.server`

Role:

* Internal façade that wraps external systems as tools:

  * `source.gamebus.walk.fetch@v1`
  * `source.googlefit.walk.fetch@v1`
  * `source.gamebus.trivia.fetch@v1`
  * `source.gamebus.sugarvita.fetch@v1`
  * `sources.status@v1`

What it does:

1. Loads merged user config: `config/users.json` + `config/users.secrets.json`
2. Resolves the right connector (player_id + token) for the requested user/source
3. Calls fetchers in `hdt_core_infrastructure/`
4. Returns a typed payload:

   * success includes `provenance` (retrieved_at, ms, player_id)
   * failure returns typed errors:

     * `unknown_user`
     * `not_connected`
     * `missing_token`
     * `upstream_error`

Observability:

* Accepts `HDT_CORR_ID` env var and sets it as the current request id, so telemetry correlates across:

  * MCP server tool call → Governor → Sources MCP tool call

#### 4) Connectors (internal to Sources MCP)

Role:

* Provider-specific HTTP/OAuth calls and parsing logic.
* Not part of the external interoperability contract; only exposed through `hdt_sources_mcp.server` tools.

#### 5) Policy engine — `hdt_mcp.policy.*`

Role:

* Enforces **purpose limitation** (analytics/modeling/coaching lanes)
* Supports:

  * deny by tool + purpose
  * field-level redaction by dotted paths
* Used:

  * pre-check denies fast
  * post-processing redacts successful payloads only

#### 6) Telemetry — `hdt_mcp.observability.telemetry`

Role:

* JSONL logging suitable for:

  * debugging
  * audit traces
  * later evaluation of “negotiation behavior”

Records include:

* `kind`: tool/governor/source
* `name`: tool name
* `corr_id`: correlation id across layers
* `ms`: duration
* sanitized args, policy info, attempts (governor)

---

## Data Flow Example: `hdt.walk.fetch@v1`

1. External client calls `hdt.walk.fetch@v1(user_id=1, prefer=gamebus, prefer_data=auto)`.
2. MCP server:

   * sets `corr_id`
   * checks lane policy
   * calls `Governor.fetch_walk(...)`
3. Governor:

   * may try vault first (depending on `prefer_data`)
   * calls Sources MCP tools in order (`source.gamebus.walk.fetch@v1`, then fallback `source.googlefit.walk.fetch@v1`)
   * writes attempts to telemetry
   * on success, upserts records into vault (best effort)
4. MCP server:

   * redacts fields if needed
   * logs telemetry with the same `corr_id`
5. Client receives:

   * records
   * `selected_source`
   * `attempts`
   * `corr_id`

## Automatic Tool Discovery

MCP provides **built-in tool discovery**: clients can query a server to obtain the current list of tools and their JSON schemas (arguments and expected shapes).

### 1) External discovery (client → HDT) — fully automatic

External agentic clients connect to the **HDT MCP server** (`hdt_mcp.gateway`) and can discover available HDT capabilities at runtime:

* **Tool list**: the client can request the current set of tools (e.g., `hdt.walk.fetch@v1`, `hdt.trivia.fetch@v1`, `hdt.sugarvita.fetch@v1`, etc.).
* **Tool schemas**: the client receives the argument schema for each tool.
* **Versioning via tool names**: tools are versioned (e.g., `...@v1`) so clients can safely target stable contracts.

This is the primary interoperability surface.

### 2) Internal discovery (HDT → Sources) — available, not enabled (yet)

In the future, this will be realized via A2A and agent-orchestrator.

### What “negotiation” means in v0.5.0

In this prototype, “negotiation” is implemented as **deterministic orchestration** rather than LLM-driven contract rewriting:

* the Governor applies a clear policy (prefer a source, fallback to another, optionally use vault),
* source outcomes are normalized into a single response envelope,
* the full attempt sequence is recorded for observability.

