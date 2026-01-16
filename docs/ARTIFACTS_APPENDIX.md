# Artifact Appendix (IEEE Software)

## A. Artifact overview
This artifact contains a research prototype of a Human Digital Twin (HDT) integration layer that exposes an **agent-friendly tool surface** via the Model Context Protocol (MCP) and enforces **purpose-specific policy lanes** (e.g., coaching vs. analytics vs. modeling). The repository includes:

- MCP façade (gateway) with a small set of versioned tools (e.g., walk fetch and walk features).
- Lane-aware policy checks (deny / allow) and output shaping (data minimization) driven by JSON policy configuration.
- A local “seeded vault” mode that enables deterministic offline demos without external systems.
- Automated tests that verify lane behavior, policy contracts, and key tool schemas.
- A telemetry-driven **guardian (auditor) agent** demo that detects suspicious cross-lane tool use by querying telemetry through `hdt.telemetry.query.v1`.
- A filtered telemetry query tool (`hdt.telemetry.query.v1`) and optional privacy-preserving `subject_hash` support for per-citizen governance (enabled by `HDT_TELEMETRY_SUBJECT_SALT`).
- A **user-facing transparency agent** demo that produces a human-readable transparency report.
- 
## B. System requirements
- OS: Linux, macOS, or Windows.
- Python: 3.11+.
- Network: Optional. All demos can run offline when using the seeded vault.

## C. Installation
From the repository root:

```bash
python -m venv .venv
# activate venv (Linux/macOS)
source .venv/bin/activate
# or Windows PowerShell
# .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Telemetry governance (guardian demo)

Optional environment variable:

- `HDT_TELEMETRY_SUBJECT_SALT`: if set, telemetry records include `subject_hash`, derived from `user_id` using a one-way hash. This supports per-subject governance while keeping telemetry safe to share.

The guardian demo is run with:

```bash
HDT_POLICY_PATH=config/policy.guardian_demo.json MCP_CLIENT_ID=COACHING_AGENT HDT_TELEMETRY_SUBJECT_SALT=demo-salt python -u scripts/demo_coaching_agent_suspicious.py
HDT_POLICY_PATH=config/policy.guardian_demo.json MCP_CLIENT_ID=GUARDIAN_AGENT HDT_TELEMETRY_SUBJECT_SALT=demo-salt python -u scripts/demo_guardian_agent.py
```

## User-facing transparency agent (“What does the HDT know about me?”)

A small agent script that produces a human-readable transparency report by calling:

- HDT data-access tools (to summarize what data exists / is available)
- Telemetry tools (to summarize which tools were accessed, by whom, and under which purpose/lane)

This demonstrates that the same MCP tool surface used for interoperability and governance can also support user-facing transparency without privileged filesystem access.
