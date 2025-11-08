# HDT Prototype with Agentic Interoperability 

This project provides a prototype of an interoperable and modular **Human Digital Twins (HDT)** system architecture.

Interoperability refers to the system's ability to access, synthesize, and standardize health data from diverse applications and platforms such as GameBus and Google Fit. These capabilities allow external model developers to efficiently locate and utilize the exact data they need for building models.

Modularity refers to the system's capacity to support the open development, testing, and integration of various virtual twin models. This flexibility encourages collaboration and facilitates the extension of the system with new functionalities.

This prototype establishes a solid foundation for future expansion and improvement. To foster further development, this public repository is intended to serve as a collaborative resource for researchers and developers interested in advancing such systems.


The remainder of this README provides detailed information about the system components and instructions for deployment.

## Table of Contents
- [System Architecture](#system-architecture)
  - [Subfolder Dependencies and Functions](#subfolder-dependencies-and-functions)
- [API Documentation](#api-documentation)
- [Setup and Installation](#setup-and-installation)
  - [Prerequisites](#prerequisites)
  - [Environment Setup](#environment-setup)
- [Configuration](#configuration)
  - [External APIs (GameBus, Google Fit)](#external-apis-gamebus-google-fit)
  - [User Permissions](#user-permissions)
- [Usage](#usage)
  - [Running the API](#running-the-api)
  - [Interacting with the API](#interacting-with-the-api)
- [How Components Interact](#how-components-interact)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## System Architecture

### Subfolder Dependencies and Functions

#### **`config` Subfolder**
- **Purpose**: Centralizes configurations, API keys, external party definitions, and user permissions.
- **Key Files**:
  - `.env`: Stores API keys for secure access.
  - `config.py`: Loads API keys and permissions, with error handling for missing configurations.
  - `external_parties.json`: Defines external clients with their `client_id`s.
  - `user_permissions.json`: Maps user IDs to allowed external clients and their permitted actions.
  - `users.json`: Provides details about users, including their connected apps for each health domain and the associated authentication tokens.

#### **`HDT_CORE_INFRASTRUCTURE` Subfolder**
- **Purpose**: Handles data fetching, parsing, authentication, and API exposure (to be extended with more available data sources and API endpoints).
- **Key Files**:
  - `auth.py`: Implements an authentication and authorization decorator based on API keys, user permissions, and required actions.
  - `GAMEBUS_DIABETES_fetch.py`: Fetches Trivia and SugarVita from the GameBus API.
  - `GAMEBUS_DIABETES_parse.py`: Contains parsing functions for converting raw responses from GameBus into structured formats.
  - `GAMEBUS_WALK_fetch.py`: Fetches walk from the GameBus API.
  - `GAMEBUS_WALK_parse.py`: Contains parsing functions for converting raw responses from GameBus into structured formats.
  - `GOOGLE_FIT_WALK_fetch`: Fetches Google Fit step count data.
  - `GOOGLE_FIT_WALK_parse`:Contains parsing functions for converting raw responses from Google Fit into structured formats.
  - `HDT_API.py`: Flask app exposing the following endpoints:
    - **for Model Developers**:
      - `/get_trivia_data`: Retrieves standardized trivia playthrough metrics.
      - `/get_sugarvita_data`: Retrieves standardized SugarVita playthrough metrics.
      - `/get_walk_data`: Retrieves standardized walk-related metrics.
    - **for App Developers**:
      - `/get_sugarvita_player_types`: Retrieves SugarVita player type scores.
      - `/get_health_literacy_diabetes`: Retrieves diabetes-related health literacy scores.

#### **`Virtual_Twin_Models` Subfolder**
- **Purpose**: Calculate health literacy and player type scores (to be extended with more diverse models).
- **Key Files**:
  - `HDT_DIABETES_calculations.py`: Contains functions for metric manipulation, normalization, scoring, and player-type determination.
  - `HDT_DIABETES_model.py`: Orchestrates fetching data from APIs, calculating scores, and storing results in `diabetes_pt_hl_storage.json`.

#### **`diabetes_pt_hl_storage.json`**
- **Purpose**: Acts as persistent storage for the model results, including health literacy scores and player types. (In the future, the collection of trained models and resulting outputs will be stored in the cloud, forming the main "Virtual Twin".)

---

## API Documentation

Full documentation for the **HDT API endpoints** is available through Swagger:
[Swagger Documentation](https://pimvanvroonhoven.github.io/Interoperable-and-modular-HDT-system-prototype/)


---

## Setup and Installation

### Prerequisites
1. Python 3.8 or higher.
2. A virtual environment tool like `venv` or `conda`.
3. [Postman](https://www.postman.com/) or cURL (optional, for testing the API).

### Environment Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/YourUsername/HDT-agentic-interop.git
   cd HDT-agentic-interop
   ```

2. Set up a virtual environment:
   ```bash
   python -m venv venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up the `.env` file in the root folder:
   ```plaintext
   HDT_API_BASE=http://localhost:5000 
   HDT_API_KEY=your_key_here
   MCP_TRANSPORT=stdio
   HDT_ALLOW_PLACEHOLDER_MOCKS=1
   HDT_ENABLE_POLICY_TOOLS=1
   MCP_CLIENT_ID=your_client_ID_here
   HDT_CACHE_TTL=60
   HDT_RETRY_MAX=3
   ```

---

## Configuration

### External APIs (GameBus, Google Fit)
To fetch data from external sources, you must populate the `player_id` and `auth_bearer` fields in the `users.json` file (located in the `config` folder). 

- **GameBus API**:
  - Follow the instructions here to obtain your credentials: [GameBus Get Started Guide](https://devdocs.gamebus.eu/get-started/)

- **Google Fit API**:
  - Set up access and retrieve credentials following this guide: [Google Fit API Get Started](https://developers.google.com/fit/rest/v1/get-started)

These credentials are essential for the second round of API calls inside the HDT_API to fetch user-specific data.

---

### User Permissions
The file `user_permissions.json` defines the access permissions for different clients and endpoints. Modify this file to customize access levels.
In the future, this file should be replaced by a proper ui with advanced authentication measures, which each user can use to control access to their data and models.

---

## Usage

### Running the API
1. Start the Flask application:
   ```bash
   python -m HDT_CORE_INFRASTRUCTURE.HDT_API
   ```

2. The API will run on `http://localhost:5000`.

3. In another terminal, start the MCP façade (stdio on Windows):
```powershell
python -m HDT_MCP.server
```

4. Start the MCP Inspector:
- Simple dev mode:
```powershell
mcp dev HDT_MCP/server.py
```
- Or using the provided config:
```powershell
npx @modelcontextprotocol/inspector --config .\config\mcp.json --server hdt-mcp
```


### Interacting with the API
You can interact with API using MCP tools in the Inspector or via HTTP requests (e.g., Postman, cURL).
Example cURL request to fetch trivia data:
```bash
curl -X GET "http://localhost:5000/get_trivia_data?user_id=1" -H "X-API-KEY: your_key_here"
```
---

## How Components Interact

1. **Fetching Data**:
   - `HDT_API.py` endpoints call fetch functions from `GAMEBUS_DIABETES_fetch.py`, `GAMEBUS_WALK_fetch.py` or `GOOGLE_FIT_WALK_fetch.py`, based on user permissions and connected apps (retrieved from `users.json`).

2. **Parsing Data**:
   - Fetch functions parse raw API responses using `*_parse.py` files (e.g., `parse_json_trivia`).

3. **Virtual Twin Model calculations**:
   - `HDT_DIABETES_model.py`:
     - Fetches Trivia and SugarVita data via the HDT API endpoints (`get_trivia_data`, `get_sugarvita_data`).
     - Manipulates and normalizes metrics using `HDT_DIABETES_calculations.py`.
     - Calculates health literacy and player type scores.
     - Updates `diabetes_pt_hl_storage.json` with the results.

4. **API Endpoint Input/Output**:
   - **Model Developer APIs**:
     - Inputs: API key (header), optional query params (e.g., `user_id` for filtering).
     - Outputs: Processed metrics, latest activity info, or errors.
   - **App Developer APIs**:
     - Inputs: API key (header), `user_id` (query param).
     - Outputs:
       - `/get_sugarvita_player_types`: Latest player type scores for a user.
       - `/get_health_literacy_diabetes`: Latest health literacy score for a user.

---


## MCP Facade (Model Context Protocol)

This repository includes an MCP server (façade) that exposes the HDT API and a few convenience utilities as MCP tools and resources. You can run it over stdio (best for local tooling and the Inspector) or as an HTTP server.

### Overview
- Location: `HDT_MCP/server.py`
- Entrypoint (Windows, stdio):
  ```powershell
  python -m HDT_MCP.server
  ```
- Transport selection: set `MCP_TRANSPORT` environment variable to `"stdio"` (default) or `"streamable-http"`.
- Policy file: `config/policy.json` (see Policy contract below)
- Telemetry file: `HDT_MCP/telemetry/mcp-telemetry.jsonl`

### 1) Run the API first
Start the HDT API so the MCP façade can call it:
```powershell
python -m HDT_CORE_INFRASTRUCTURE.HDT_API
```
The API serves on `http://localhost:5000` by default.

### 2) Run the MCP server

#### A. Stdio transport (recommended for local dev and Inspector)
PowerShell (Windows):
```powershell
# Optional: ensure stdio (this is the default)
$env:MCP_TRANSPORT = "stdio"

# Optionally pass API base/key via environment variables
$env:HDT_API_BASE = "http://localhost:5000"
$env:HDT_API_KEY  = "YOUR_API_KEY"

# Start the server
python -m HDT_MCP.server
```

#### B. HTTP transport (for desktop agents / remote clients)
PowerShell (Windows):
```powershell
$env:MCP_TRANSPORT = "streamable-http"
$env:HDT_API_BASE  = "http://localhost:5000"
$env:HDT_API_KEY   = "YOUR_API_KEY"
python -m HDT_MCP.server
```
Notes:
- The HTTP transport is provided by `FastMCP`. Default host/port may be printed on launch by the library. If your agent needs a specific port/host, consult `mcp.server.fastmcp` docs for environment variables or wrapper options.
- For most model/dev workflows, stdio with the Inspector is simplest.

### 3) Inspector setup
You can use the MCP Inspector to explore and call tools.

Option 1 — Use the provided config file:
```powershell
# From the repo root (Windows)
# This uses config/mcp.json to start a stdio server via the Python MCP CLI
npx @modelcontextprotocol/inspector --config .\config\mcp.json --server hdt-mcp
```

Option 2 — Simple dev mode (no config):
```powershell
# Ensure the API is running, then in another terminal:
python -m HDT_MCP.server   # stdio server

# And start Inspector in dev mode, pointing at the Python entrypoint:
npx @modelcontextprotocol/inspector dev HDT_MCP/server.py
```

Tip: If you installed the Python `mcp` CLI, you can also use:
```powershell
mcp dev HDT_MCP/server.py
```

### 4) Environment variables
- `HDT_API_BASE` (default `http://localhost:5000`): Where the MCP façade sends API requests.
- `HDT_API_KEY`: API key forwarded in `X-API-KEY` and `Authorization: Bearer ...` headers.
- `MCP_TRANSPORT` (default `stdio`): `stdio` or `streamable-http`.
- `MCP_CLIENT_ID` (default `MODEL_DEVELOPER_1`): Used for policy evaluation (`clients` section).
- `HDT_ENABLE_POLICY_TOOLS` (default `0` in config/mcp.json; recommended `1` locally): Enables policy-aware envelopes and the `policy.evaluate@v1` tool.
- `HDT_CACHE_TTL` (seconds, default `15`): In-process GET cache TTL.
- `HDT_RETRY_MAX` (default `2`): Retries for API GETs.

---

## MCP Tools and Resources

All tools return a policy envelope when allowed: 
```json
{
  "allowed": true,
  "purpose": "analytics",
  "tool": "hdt.get_walk_data@v1",
  "data": { "example": "redacted payload from API" },
  "redactions_applied": ["records[].user_id"]
}
```
When a call is blocked by policy, you receive:
```json
{ "allowed": false, "purpose": "analytics", "tool": "hdt.get_walk_data@v1", "error": "Blocked by policy" }
```

### Tools
- `hdt.get_trivia_data@v1(user_id: str)`
  - Wraps `/get_trivia_data`. Example args:
    ```json
    { "user_id": "1" }
    ```
- `hdt.get_sugarvita_data@v1(user_id: str)`
  - Wraps `/get_sugarvita_data`. Example:
    ```json
    { "user_id": "1" }
    ```
- `hdt.get_walk_data@v1(user_id: str, purpose: "analytics"|"modeling"|"coaching" = "analytics")`
  - Wraps `/get_walk_data`. Example:
    ```json
    { "user_id": "1", "purpose": "analytics" }
    ```
- `hdt.get_sugarvita_player_types@v1(user_id: str, purpose = "analytics")`
  - Wraps `/get_sugarvita_player_types`. Example:
    ```json
    { "user_id": "1" }
    ```
- `hdt.get_health_literacy_diabetes@v1(user_id: str, purpose = "analytics")`
  - Wraps `/get_health_literacy_diabetes`. Example:
    ```json
    { "user_id": "1" }
    ```
- `policy.evaluate@v1(purpose = "analytics")`
  - Simple toggle to confirm if policy tools are enabled. Returns `{ purpose, allow, redact_fields, ... }`.
- `intervention_time@v1(local_tz = "Europe/Amsterdam", preferred_hours = [18,21], min_gap_hours = 6, last_prompt_iso = null)`
  - Returns a basic suggestion for next intervention window.

### Resources
- `vault://{user_id}/integrated`
  - Minimal integrated view combining walk records and rollups for a user.
- `hdt://{user_id}/sources`
  - Lists connected data sources for the user (from `config/users.json`).
- `registry://tools`
  - Returns a compact list of available tools.
- `telemetry://recent/{n}`
  - Returns the last `n` telemetry events recorded locally by the MCP façade.

---

## Policy file contract (`config/policy.json`)

The policy controls which tools are allowed and which fields are redacted in tool outputs. It supports three levels, with the following precedence:
1) Tool-specific overrides (`tools`)
2) Client-specific defaults (`clients`, keyed by `MCP_CLIENT_ID`)
3) Global defaults (`defaults`)

Each level maps a `purpose` to a rule object:
```json
{
  "allow": true,
  "redact": ["records[].user_id", "records[].steps"]
}
```
- `allow` (boolean): If false, the call returns `{ allowed: false, error: "Blocked by policy" }`.
- `redact` (array of dot-paths): Fields to replace with `***redacted***`. Works through objects and arrays (use `[]` to indicate array elements).

### Full example
```json
{
  "defaults": {
    "analytics": { "allow": true,  "redact": [] },
    "modeling":  { "allow": true,  "redact": ["records[].user_id"] },
    "coaching":  { "allow": false, "redact": [] }
  },
  "clients": {
    "MODEL_DEVELOPER_1": {
      "analytics": { "allow": true, "redact": [] },
      "coaching":  { "allow": true, "redact": ["records[].user_id", "records[].steps"] }
    }
  },
  "tools": {
    "hdt.get_walk_data@v1": {
      "analytics": { "allow": true, "redact": ["records[].user_id"] }
    },
    "hdt.get_trivia_data@v1": {
      "analytics": { "allow": true, "redact": ["data[].player_name"] }
    }
  }
}
```
In the example above:
- For `hdt.get_walk_data@v1` at purpose `analytics`, the `tools` rule applies and redacts `records[].user_id`.
- If no tool rule exists, the system falls back to the `clients` rule for the current `MCP_CLIENT_ID`, then to `defaults`.

### Enabling/Disabling policy features
- Set `HDT_ENABLE_POLICY_TOOLS=1` to enable policy-aware behavior and the `policy.evaluate@v1` tool.
- If disabled, `policy.evaluate@v1` returns `disabled: true`, and tools may bypass policy envelopes depending on configuration.

---

## End-to-end example (Windows)
1) Start API:
```powershell
python -m HDT_CORE_INFRASTRUCTURE.HDT_API
```
2) Start MCP (stdio):
```powershell
$env:HDT_API_BASE = "http://localhost:5000"
$env:HDT_API_KEY  = "YOUR_API_KEY"
$env:HDT_ENABLE_POLICY_TOOLS = "1"
python -m HDT_MCP.server
```
3) Launch Inspector:
```powershell
npx @modelcontextprotocol/inspector --config .\config\mcp.json --server hdt-mcp
```
4) In the Inspector, call the tool `hdt.get_walk_data@v1` with arguments:
```json
{ "user_id": "1", "purpose": "analytics" }
```
