from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from hdt_mapping_plan.hashing import sha256_hex_of_json


DSLType = str  # "string" | "int64" | "float64" | "bool" | "date" | "datetime"


def sqlite_decl_to_dsl_type(decl: str | None) -> DSLType:
    """
    SQLite type affinity mapping (best-effort).
    """
    t = (decl or "").strip().upper()

    # common date/time declarations
    if "DATETIME" in t or "TIMESTAMP" in t or ("TIME" in t and "DATE" in t):
        return "datetime"
    if "DATE" in t:
        return "date"

    # affinities
    if "INT" in t:
        return "int64"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "float64"
    if "BOOL" in t:
        return "bool"

    # NUMERIC can be int/float/decimal; safest default is float64 unless you enforce more metadata
    if "NUMERIC" in t or "DECIMAL" in t:
        return "float64"

    # default
    return "string"


def _list_tables(con: sqlite3.Connection) -> List[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _table_columns(con: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    # columns: cid, name, type, notnull, dflt_value, pk
    cols: List[Dict[str, Any]] = []
    for (_cid, name, decl_type, notnull, _dflt, pk) in rows:
        cols.append(
            {
                "name": str(name),
                "type": sqlite_decl_to_dsl_type(decl_type),
                "nullable": not bool(notnull),
                "primary_key": bool(pk),
                "decl_type": str(decl_type) if decl_type is not None else "",
            }
        )
    return cols


def generate_vault_catalog(
    *,
    vault_db_path: str,
    dataset_id: str,
    out_path: str | None = None,
    only_tables: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Introspect a vault SQLite DB and generate a catalog with column types.
    """
    dbp = Path(vault_db_path).expanduser().resolve()
    if not dbp.exists():
        raise FileNotFoundError(str(dbp))

    con = sqlite3.connect(str(dbp))
    try:
        tables = _list_tables(con)
        if only_tables:
            allow = set(only_tables)
            tables = [t for t in tables if t in allow]

        table_entries: List[Dict[str, Any]] = []
        for t in tables:
            cols = _table_columns(con, t)
            schema_hash = sha256_hex_of_json({"table": t, "columns": cols})
            table_entries.append(
                {
                    "table_name": t,
                    "columns": cols,
                    "schema_hash": schema_hash,
                }
            )

        catalog = {
            "vault_db": str(dbp),
            "datasets": [
                {
                    "dataset_id": dataset_id,
                    "tables": table_entries,
                }
            ],
        }
    finally:
        con.close()

    if out_path:
        op = Path(out_path).expanduser().resolve()
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")

    return catalog


def load_vault_catalog(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser().resolve()
    return json.loads(p.read_text(encoding="utf-8"))


def get_dataset_schema(
    catalog: Mapping[str, Any],
    *,
    dataset_id: str,
    table_name: str,
) -> Tuple[set[str], Dict[str, DSLType]]:
    """
    Returns (dataset_columns, dataset_column_types) for the given dataset/table.
    """
    datasets = catalog.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("vault_catalog.json: expected top-level key 'datasets' as a list")

    ds = next((d for d in datasets if isinstance(d, dict) and d.get("dataset_id") == dataset_id), None)
    if ds is None:
        raise KeyError(f"dataset_id not found: {dataset_id}")

    tables = ds.get("tables")
    if not isinstance(tables, list):
        raise ValueError(f"dataset {dataset_id}: expected 'tables' list")

    tb = next((t for t in tables if isinstance(t, dict) and t.get("table_name") == table_name), None)
    if tb is None:
        raise KeyError(f"table not found: {dataset_id}.{table_name}")

    cols = tb.get("columns")
    if not isinstance(cols, list):
        raise ValueError(f"{dataset_id}.{table_name}: expected 'columns' list")

    names: set[str] = set()
    types: Dict[str, DSLType] = {}
    for c in cols:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        typ = c.get("type")
        if isinstance(name, str) and name:
            names.add(name)
            if isinstance(typ, str) and typ:
                types[name] = typ

    return names, types
