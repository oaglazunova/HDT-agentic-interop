# HDT v0.5.0 (2025-12-12)

Prototype for an **MCP** Human Digital Twin (HDT) interoperability gateway, designed to support: purpose-limited tool access (“lanes”), deterministic orchestration (“governor”), typed errors, and auditable telemetry.

## Highlights

- **MCP-only architecture**: the HDT is exposed exclusively via MCP tools; REST is not a required integration surface.
- **HDT Governor (orchestrator)**:
  - Central decision point for source selection, fallback, and error normalization.
  - Executes tool calls; returns structured results with provenance and attempt traces.
- **Sources MCP façade (internal)**:
  - External systems are wrapped as MCP tools (e.g., GameBus, Google Fit, SugarVita, Trivia) using existing fetchers/parsers.
  - Enables capability discovery and uniform invocation via MCP rather than bespoke per-client glue.
- **Domain-first tool surface (external)**:
  - HDT-level tools expose capabilities (e.g., walking, diabetes/trivia) without leaking source-specific API details.
- **Structured errors and observability**:
  - Source failures are returned as typed error envelopes (e.g., `not_connected`, `missing_token`, `upstream_error`, `all_sources_failed`) instead of silent empty results.
  - Tool responses include basic provenance (and `corr_id`) to support debugging and auditing.

## Architecture Overview

- **External interface**: `hdt_mcp.gateway` (HDT MCP server)
  - Exposes HDT-level tools to external agents/clients.
  - Delegates execution to the **HDT Governor**.
- **Internal source interface**: `hdt_sources_mcp.server` (Sources MCP server)
  - Exposes source-specific tools (GameBus/Google Fit/SugarVita/Trivia).
  - Reads connection configuration via merged `config/users.json` + `config/users.secrets.json`.
- **Connectors** (internal implementation detail): provider-specific fetch/parse code lives inside `hdt_sources_mcp`.
  The external HDT surface remains MCP-only.

## Architecture at a glance

![Architecture](./docs/architecture.jpg)

---

## Demos (IEEE paper / reviewer-friendly)

- **One-command demo (recommended):** `.\scripts\demo_ieee_all.ps1`  
  Runs:
  1) Privacy & purpose lanes (deny-fast + modeling-safe outputs + redaction differences)  
  2) Transparency / traceability (telemetry with `corr_id` + JSONL summary)  
  3) Policy matrix (clients × purposes × tools)

- **Demo documentation:** see `docs/DEMO.md` for expected outputs and suggested screenshots.

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

### 4) Run the test suite (canonical validation)

```bash
python -m pytest -q
```

If this passes, your local environment and tool contracts are consistent.

### 5) Run the IEEE demo (recommended end-to-end)

**Windows (PowerShell):**

```powershell
.\scripts\demo_ieee_all.ps1
```

If execution policy blocks scripts:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_ieee_all.ps1
```

Artifacts are written under `artifacts/telemetry/` and `artifacts/vault/` (do not commit).

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
   Purpose: wraps external systems (GameBus, Google Fit, SugarVita, Trivia) as MCP tools.

The HDT MCP server calls Sources MCP internally via a local stdio MCP client (it spawns the Sources server as a subprocess).

### Transport modes

* `stdio` (recommended for local dev and demos): MCP messages flow over standard input/output.
  Ideal for “spawn a server as a subprocess” and for local testing.
* `streamable-http` (optional): use only for the **external-facing** server, and only after adding authentication.

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

* In `stdio` mode you typically do not see a friendly “listening” banner. It is meant to be driven by an MCP client (scripts/tests).
* The recommended validation is to run `.\scripts\demo_ieee_all.ps1` or `python scripts/demo_ieee_transparency.py`.

### B) Start the internal Sources MCP server (usually not started manually)

You normally do **not** run Sources MCP directly, because the HDT MCP client spawns it automatically.

If you want to run it explicitly (debugging):

```powershell
$env:MCP_TRANSPORT="stdio"
python -m hdt_sources_mcp.server
```

### C) Validate everything works (recommended)

Run the full demo:

```powershell
.\scripts\demo_ieee_all.ps1
```

Run the full test suite:

```powershell
python -m pytest -q
```

### D) Common environment variables

* `MCP_TRANSPORT`: `stdio` (default) or `streamable-http`
* `MCP_CLIENT_ID`: identifier for policy/telemetry attribution (e.g., `MODEL_DEVELOPER_1`)
* `HDT_POLICY_PATH`: path to the policy JSON (e.g., `config/policy_ieee_demo.json`)
* `HDT_VAULT_ENABLE`: `1` to enable vault read-through/write-through
* `HDT_VAULT_PATH`: location of the vault DB file (e.g., `./artifacts/vault/hdt_vault.sqlite`)
* `HDT_TELEMETRY_DIR`: directory for telemetry JSONL output
* `HDT_DISABLE_TELEMETRY`: `1` to disable telemetry logging
* `HDT_DEMO_TIMEOUT_SEC`: demo call timeout (default `30`)

---

## Test and debug with MCP Inspector (Windows + Git Bash)

The MCP Inspector is an interactive UI for exploring an MCP server: list tools, call them with JSON inputs, and inspect responses. It runs a local web UI (default `http://localhost:6274`) and a local proxy server (default port `6277`).

### Prerequisites

* Node.js (for `npx`)
* This repo installed in a Python virtualenv:

  ```bash
  python -m pip install -e ".[dev]"
  ```

### Recommended: offline / deterministic mode (seeded vault)

This mode does not require live GameBus credentials and is suitable for demos and reviewers.

1. Initialize sample config + seeded vault:

```bash
python scripts/init_sample_config.py
python scripts/init_sample_vault.py
```

2. Launch the Inspector against the HDT gateway (STDIO transport):

```bash
npx @modelcontextprotocol/inspector \
  -e MCP_TRANSPORT=stdio \
  -e HDT_VAULT_ENABLE=1 \
  -e HDT_VAULT_PATH=artifacts/vault/hdt_vault_ieee_demo.sqlite \
  -- python -m hdt_mcp.gateway
```

Notes:

* `--` separates Inspector arguments from the server command/args.
* Run this from an *activated* venv so `python -m hdt_mcp.gateway` uses the correct environment.

3. Open the Inspector UI:

* Navigate to `http://localhost:6274` in your browser.

### Suggested tool calls to try

In the Inspector UI, open the **Tools** panel and call:

* **Policy explain (why a tool is allowed/denied in a lane)**

  * Tool: `hdt.policy.explain.v1`
  * Input:

    ```json
    { "tool": "hdt.walk.fetch.v1", "purpose": "modeling" }
    ```

* **Raw walk fetch (allowed in coaching/analytics; denied in modeling by policy)**

  * Tool: `hdt.walk.fetch.v1`
  * Input (analytics):

    ```json
    {
      "user_id": 1,
      "start_date": "2025-11-01",
      "end_date": "2025-11-03",
      "prefer_data": "vault",
      "purpose": "analytics"
    }
    ```
  * Input (modeling; expected deny):

    ```json
    {
      "user_id": 1,
      "start_date": "2025-11-01",
      "end_date": "2025-11-03",
      "prefer_data": "vault",
      "purpose": "modeling"
    }
    ```

* **Modeling-safe features**

  * Tool: `hdt.walk.features.v1`
  * Input:

    ```json
    {
      "user_id": 1,
      "start_date": "2025-11-01",
      "end_date": "2025-11-03",
      "prefer_data": "vault",
      "purpose": "modeling"
    }
    ```

* **Telemetry (recent calls)**

  * Tool: `hdt.telemetry.recent.v1`
  * Input:

    ```json
    { "n": 50, "purpose": "analytics" }
    ```

### Optional: inspect the sources server directly

```bash
npx @modelcontextprotocol/inspector -e MCP_TRANSPORT=stdio -- python -m hdt_sources_mcp.server
```

### Troubleshooting

* **Port conflicts:** Inspector uses ports `6274` (UI) and `6277` (proxy) by default; free those ports if they are occupied.
* **Nothing “prints” from the server:** with STDIO, servers often don’t show a typical “listening” banner; validate by listing tools and calling `hdt.sources.status.v1` / `hdt.healthz.v1` in the UI.

---

## Architecture (Detailed)

### Why two MCP servers?

The design separates the system into two layers:

* **External MCP contract (domain-first):** what external clients/agents see and call.
* **Internal MCP contract (source-first):** how the HDT interacts with external systems uniformly.

This prevents the external tool surface from leaking GameBus/Google Fit/SugarVita implementation details and lets you evolve connectors independently.

### Components

#### 1) HDT MCP Server — `hdt_mcp.gateway`

Role:

* The **only** supported integration surface for external clients.
* Exposes **domain-level tools** such as:

  * `hdt.walk.fetch.v1`
  * `hdt.walk.features.v1`
  * `hdt.trivia.fetch.v1`
  * `hdt.sugarvita.fetch.v1`
  * `hdt.sources.status.v1`
  * `hdt.policy.explain.v1`
  * `hdt.telemetry.recent.v1`

What it does on each tool call:

1. Creates a **correlation id** (`corr_id`) for end-to-end tracing.
2. Validates request parameters (including `purpose` lane).
3. Performs **policy pre-check** (deny fast, avoid upstream calls).
4. Delegates execution to the Governor.
5. Applies **policy redaction** (`apply_policy_safe`) on successful payloads.
6. Writes telemetry (JSONL) with:

   * tool name
   * sanitized args
   * policy meta (allowed/redactions)
   * `corr_id`
   * duration (ms)

#### 2) HDT Governor — `hdt_mcp.governor.HDTGovernor`

Role:

* Orchestration and deterministic “negotiation rules.”
* Converts multiple source/tool outcomes into one normalized response envelope.
* Produces a **negotiation trace** via `attempts`.

Key behaviors:

* **Source preference + fallback**:

  * try preferred live source (e.g., `gamebus` or `googlefit`)
  * fallback to the other on typed errors
* **Vault strategy** (`prefer_data`):

  * `prefer_data="vault"`: vault-only (demos)
  * `prefer_data="live"`: live-only (fail if upstream fails)
  * `prefer_data="auto"`: vault-first and/or vault-fallback depending on configuration
* **Write-through**:

  * after successful live fetch, upsert into vault (best effort)

Outputs:

* Success payloads include `selected_source` and `attempts`.
* Failure payloads return a typed error envelope plus attempt details.

#### 3) Sources MCP Server — `hdt_sources_mcp.server`

Role:

* Internal façade that wraps external systems as tools such as:

  * `source.gamebus.walk.fetch.v1`
  * `source.googlefit.walk.fetch.v1`
  * `source.gamebus.trivia.fetch.v1`
  * `source.gamebus.sugarvita.fetch.v1`
  * `sources.status.v1`

What it does:

1. Loads merged user config: `config/users.json` + `config/users.secrets.json`
2. Resolves connector configuration for the requested user/source
3. Calls provider fetchers/parsers in `hdt_sources_mcp`
4. Returns typed payloads:

   * success includes `provenance` (retrieved_at, ms, player_id where applicable)
   * failure returns typed errors:

     * `unknown_user`
     * `not_connected`
     * `missing_token`
     * `upstream_error`

Correlation:

* The HDT layer can pass a correlation id to the Sources layer (via environment) so telemetry correlates across:
  MCP tool call → Governor → Sources MCP tool call.

#### 4) Connectors (internal to Sources MCP)

Role:

* Provider-specific HTTP/OAuth calls and parsing logic.
* Not part of the external interoperability contract; exposed only through `hdt_sources_mcp.server` tools.

#### 5) Policy engine — `hdt_mcp.policy.*`

Role:

* Enforces **purpose limitation** (analytics/modeling/coaching lanes)
* Supports:

  * deny by tool + purpose
  * field-level redaction by dotted paths
* Used for:

  * pre-check denies fast
  * post-processing redacts successful payloads only

#### 6) Telemetry — JSONL traces (tool + governor)

Role:

* JSONL logging suitable for:

  * debugging
  * audit traces
  * evaluation of “negotiation behavior”

Records include:

* `kind`: tool/governor/source
* `name`: tool name
* `corr_id`: correlation id across layers
* `request_id`: request id (often equal to `corr_id` in demos)
* `ms`: duration
* sanitized args and policy info

---

## Data Flow Example: `hdt.walk.fetch.v1`

1. External client calls `hdt.walk.fetch.v1(user_id=1, prefer=gamebus, prefer_data=auto)`.
2. HDT MCP server:

   * sets `corr_id`
   * checks lane policy
   * calls `Governor.fetch_walk(...)`
3. Governor:

   * may try vault first (depending on `prefer_data`)
   * calls Sources MCP tools in order (e.g., `source.gamebus.walk.fetch.v1`, then fallback `source.googlefit.walk.fetch.v1`)
   * records `attempts`
   * on success, upserts records into vault (best effort)
4. HDT MCP server:

   * redacts fields if needed
   * logs telemetry with the same `corr_id`
5. Client receives:

   * records (or modeling-safe features via `hdt.walk.features.v1`)
   * `selected_source`
   * `attempts`
   * `corr_id`

---

## Automatic Tool Discovery

MCP provides built-in tool discovery: clients can query a server to obtain the current list of tools and their JSON schemas (arguments and expected shapes).

### 1) External discovery (client → HDT)

External agentic clients connect to the **HDT MCP server** (`hdt_mcp.gateway`) and can discover available HDT capabilities at runtime:

* **Tool list** (e.g., `hdt.walk.fetch.v1`, `hdt.trivia.fetch.v1`, `hdt.sugarvita.fetch.v1`, etc.)
* **Tool schemas** (argument shapes for each tool)
* **Versioning via tool names** (e.g., `....v1`) to preserve stable contracts

### 2) Internal discovery (HDT → Sources)

The Sources MCP server similarly exposes tool schemas for the internal source façade. The Governor uses deterministic orchestration rules today; more dynamic discovery/negotiation can be layered on later without changing the external tool surface.

### What “negotiation” means in v0.5.0

In this prototype, “negotiation” is implemented as deterministic orchestration rather than LLM-driven contract rewriting:

* the Governor applies a clear strategy (prefer source, fallback, optionally use vault),
* source outcomes are normalized into a single response envelope,
* the attempt sequence is recorded for observability.
