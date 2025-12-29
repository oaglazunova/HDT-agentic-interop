# Artifact Appendix (IEEE Software)

## A. Artifact overview
This artifact contains a research prototype of a Human Digital Twin (HDT) integration layer that exposes an **agent-friendly tool surface** via the Model Context Protocol (MCP) and enforces **purpose-specific policy lanes** (e.g., coaching vs. analytics vs. modeling). The repository includes:

- MCP façade (gateway) with a small set of versioned tools (e.g., walk fetch and walk features).
- Lane-aware policy checks (deny / allow) and output shaping (data minimization) driven by JSON policy configuration.
- A local “seeded vault” mode that enables deterministic offline demos without external systems.
- Automated tests that verify lane behavior, policy contracts, and key tool schemas.

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
# .\\.venv\\Scripts\\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
