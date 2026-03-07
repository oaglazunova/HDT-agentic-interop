from __future__ import annotations

import ast
from typing import Any


def apply_limits_policy(
    plan: dict[str, Any],
    *,
    max_rows_cap: int = 10_000,
    batch_rows_cap: int = 2_000,
    max_record_bytes_cap: int = 8_192,
    max_total_output_bytes_cap: int = 10_000_000,
    default_max_total_output_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """
    Deterministic safety defaults + clamping.
    This reduces exfil surface and avoids 'permissive limits' warnings by default.
    """
    limits = plan.get("limits")
    if not isinstance(limits, dict):
        limits = {}
        plan["limits"] = limits

    def _int(v: Any, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return default

    # defaults (conservative)
    max_rows = _int(limits.get("max_rows"), max_rows_cap)
    max_record_bytes = _int(limits.get("max_record_bytes"), 4_096)
    batch_rows = _int(limits.get("batch_rows"), min(1_000, max_rows))
    max_total_output_bytes = _int(limits.get("max_total_output_bytes"), default_max_total_output_bytes)

    # clamp & sanity
    max_rows = max(1, min(max_rows, max_rows_cap))
    max_record_bytes = max(256, min(max_record_bytes, max_record_bytes_cap))

    batch_rows = max(1, min(batch_rows, batch_rows_cap))
    batch_rows = min(batch_rows, max_rows)  # cannot exceed max_rows

    # Output budget: clamp + never exceed theoretical per-row cap
    max_total_output_bytes = max(10_000, min(max_total_output_bytes, max_total_output_bytes_cap))
    theoretical_cap = max_rows * max_record_bytes
    max_total_output_bytes = min(max_total_output_bytes, theoretical_cap)

    limits.update(
        {
            "max_rows": max_rows,
            "batch_rows": batch_rows,
            "max_record_bytes": max_record_bytes,
            "max_total_output_bytes": max_total_output_bytes,
        }
    )
    return plan


def fill_contract_refs(
    plan: dict[str, Any],
    *,
    algo_id: str,
    algo_version: str,
    registry_base: str = "oci://local/contracts",
) -> dict[str, Any]:
    """
    Deterministically fill/override contract refs so plans are self-describing and auditable.
    This removes 'UNKNOWN' and prevents the LLM from inventing refs.
    """
    base = f"{registry_base.rstrip('/')}/{algo_id}/{algo_version}"

    contract = plan.get("contract")
    if not isinstance(contract, dict):
        contract = {}
        plan["contract"] = contract

    contract["contract_ref"] = base
    contract["input_schema_ref"] = f"{base}#input.schema.json"

    # Output schema ref is stored under output.result_schema_ref
    out = plan.get("output")
    if isinstance(out, dict):
        out["result_schema_ref"] = f"{base}#output.schema.json"

    return plan


# ---------------------------------------------------------------------------
# Expression normalization helpers
# ---------------------------------------------------------------------------

_EXPR_OPS = {
    "column",
    "const",
    "cast",
    "to_string",
    "parse_date",
    "parse_datetime",
    "scale",
    "round",
    "lower",
    "upper",
    "coalesce",
}


def _is_texty_type(t: str) -> bool:
    u = t.strip().upper()
    if not u:
        return False
    return "TEXT" in u or "CHAR" in u or "STRING" in u or "VARCHAR" in u or u in {"STR"}


def _is_numeric_type(t: str) -> bool:
    u = t.strip().upper()
    if not u:
        return False
    return (
        u in {"INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT"}
        or "INT" in u
        or "NUM" in u
        or "DEC" in u
        or "REAL" in u
        or "FLOAT" in u
        or "DOUBLE" in u
    )


def normalize_expr_shapes(plan: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fix-ups for common *expression-shape* mistakes in LLM output.

    Key schema rule:
      - For op="const", value MUST be a literal (string/number/bool/null),
        not another expression object.

    Normalize:
      {"op":"const","value":{"op":"parse_date", ...}}  ->  {"op":"parse_date", ...}
    """
    rm = plan.get("record_mapping")
    if isinstance(rm, dict):
        for k, expr in list(rm.items()):
            rm[k] = _normalize_expr(expr)

    rf = plan.get("row_filter")
    if isinstance(rf, dict):
        plan["row_filter"] = _normalize_expr(rf)

    return plan


def _normalize_expr(expr: Any) -> Any:
    if not isinstance(expr, dict):
        return expr

    op = expr.get("op")

    # --- NEW: unstringify const-wrapped expressions ---
    # Pattern seen in dumps:
    #   {"op":"const","value":{"const":"{'op':'parse_date', ... }"}}
    # or {"op":"const","value":"{'op':'column', ... }"}
    if op == "const":
        v = expr.get("value")

        # NEW: const.value must be a literal; normalize {"op":"null"} to literal None
        if isinstance(v, dict) and v.get("op") == "null":
            expr["value"] = None
            return expr

        # Case A: value is dict with a single string payload under "const" or "value"
        if isinstance(v, dict):
            s = None
            if isinstance(v.get("const"), str):
                s = v.get("const")
            elif isinstance(v.get("value"), str):
                s = v.get("value")

            if isinstance(s, str) and s.strip().startswith(("{", "[")):
                parsed = _try_literal_eval(s)
                if isinstance(parsed, dict) and isinstance(parsed.get("op"), str):
                    return _normalize_expr(parsed)

        # Case B: value is a stringified expression directly
        if isinstance(v, str) and v.strip().startswith(("{", "[")):
            parsed = _try_literal_eval(v)
            if isinstance(parsed, dict) and isinstance(parsed.get("op"), str):
                return _normalize_expr(parsed)

        # Existing rule: unwrap const(<expr>) where const.value is another expression object
        if isinstance(v, dict) and v.get("op") in _EXPR_OPS:
            return _normalize_expr(v)

    # Recurse into args
    args = expr.get("args")
    if isinstance(args, list):
        expr["args"] = [_normalize_expr(a) for a in args]

    return expr


def _try_literal_eval(s: str) -> Any:
    """
    Safely parse Python-literal-like strings that LLMs sometimes emit
    (single quotes, dict notation). Returns None on failure.
    """
    try:
        return ast.literal_eval(s)
    except Exception:
        return None


def coerce_date_columns(
    plan: dict[str, Any],
    *,
    contract_input_schema: dict[str, Any],
    dataset_column_types: dict[str, str] | None,
    date_format: str = "%Y-%m-%d",
) -> dict[str, Any]:
    """
    Ensure date-typed required pointers are produced as date expressions.

    If a required pointer expects format='date' and the mapping is a bare column:
      - TEXT-like column -> parse_date(column)
      - numeric-like column -> parse_date(to_string(column))

    This is deterministic and avoids TYPE_MISMATCH in common 'dob as int' schemas.
    """
    if not dataset_column_types:
        return plan

    rm = plan.get("record_mapping")
    if not isinstance(rm, dict):
        return plan

    expected_date_ptrs = _date_like_required_leaf_pointers(contract_input_schema)

    for ptr in expected_date_ptrs:
        expr = rm.get(ptr)
        if not isinstance(expr, dict) or expr.get("op") != "column":
            continue

        col = expr.get("name")
        if not isinstance(col, str) or not col:
            continue

        col_type = dataset_column_types.get(col)
        if not isinstance(col_type, str) or not col_type.strip():
            continue

        if _is_texty_type(col_type):
            inner = {"op": "column", "name": col}
        elif _is_numeric_type(col_type):
            # Convert numeric to string before parsing to date.
            # NOTE: requires 'to_string' to be allowed by your DSL/validator.
            inner = {"op": "to_string", "args": [{"op": "column", "name": col}]}
        else:
            # Unknown type: don't guess.
            continue

        rm[ptr] = {
            "op": "parse_date",
            "format": date_format,
            "args": [inner],
        }

    return plan


def _date_like_required_leaf_pointers(contract_input_schema: dict[str, Any]) -> set[str]:
    # Find required leaf pointers whose leaf schema has format="date".
    def rec(schema: Any, prefix: str = "") -> set[str]:
        if not isinstance(schema, dict):
            return set()
        props = schema.get("properties")
        if not isinstance(props, dict):
            return set()
        required = set(schema.get("required") or [])
        out: set[str] = set()
        for name, sub in props.items():
            p = f"{prefix}/{name}"
            if not isinstance(sub, dict):
                continue
            sub_props = sub.get("properties")
            if isinstance(sub_props, dict) and sub_props:
                if name in required:
                    out |= rec(sub, p)
            else:
                if name in required and sub.get("format") == "date":
                    out.add(p)
        return out

    return rec(contract_input_schema)
