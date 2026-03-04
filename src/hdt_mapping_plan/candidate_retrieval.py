from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


_PROVIDER_SEED_POINTER_CANDIDATES: dict[str, dict[str, list[str]]] = {
    "provider.obesityCoach": {
        "/recordId": ["txn_id"],
        "/person/birthDate": ["dob"],
        "/day/date": ["date"],
        "/activity/steps": ["steps"],
        "/nutrition/caloriesIn": ["calories_in"],
        "/hydration/waterMl": ["water_ml"],
        "/sleep/minutes": ["sleep_minutes"],
    }
}


def provider_seed_pointer_candidates(algo_id: str) -> dict[str, list[str]]:
    """
    Optional deterministic per-provider hints.

    Returned as a copy so callers can safely mutate.
    """
    base = _PROVIDER_SEED_POINTER_CANDIDATES.get(algo_id, {})
    return {ptr: list(cols) for ptr, cols in base.items()}


def _snakeish(name: str) -> str:
    """
    Very small camelCase/PascalCase -> snake_case normalizer.
    """
    out: list[str] = []
    for ch in name:
        if ch.isupper():
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out).lstrip("_")


def _compact(name: str) -> str:
    """
    Lowercase alphanumeric-only representation for fuzzy equality checks.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _split_tokens(name: str) -> set[str]:
    """
    Tokenize a column / field name after light normalization.
    """
    snake = _snakeish(name)
    parts = re.split(r"[^a-z0-9]+", snake.lower())
    return {p for p in parts if p}


def _pointer_leaf(ptr: str) -> str:
    if not ptr:
        return ""
    return ptr.rsplit("/", 1)[-1]


def _contract_pointer_subschema(schema: Mapping[str, Any], ptr: str) -> dict[str, Any] | None:
    """
    Minimal JSON Pointer traversal for object properties only.
    Good enough for your current contract shape.
    """
    if not isinstance(schema, dict):
        return None
    if not isinstance(ptr, str) or not ptr.startswith("/"):
        return None

    node: dict[str, Any] = dict(schema)
    parts = [p.replace("~1", "/").replace("~0", "~") for p in ptr.split("/")[1:]]

    for part in parts:
        props = node.get("properties")
        if not isinstance(props, dict):
            return None
        child = props.get(part)
        if not isinstance(child, dict):
            return None
        node = child

    return node


def _expected_kind_for_pointer(
    contract_input_schema: Mapping[str, Any] | None,
    ptr: str,
) -> str:
    """
    Very lightweight target-type signal for ranking only.
    Returns: numeric | dateish | string | unknown
    """
    if not contract_input_schema:
        return "unknown"

    subschema = _contract_pointer_subschema(contract_input_schema, ptr)
    if not isinstance(subschema, dict):
        return "unknown"

    fmt = str(subschema.get("format") or "").lower()
    typ = str(subschema.get("type") or "").lower()

    if fmt in {"date", "date-time"}:
        return "dateish"
    if typ in {"integer", "number"}:
        return "numeric"
    if typ == "string":
        return "string"
    return "unknown"


def _column_kind(declared_type: str | None) -> str:
    """
    Lightweight DB-ish type classification.
    Returns: numeric | dateish | string | unknown
    """
    t = str(declared_type or "").lower()

    if any(tok in t for tok in ("int", "real", "float", "double", "decimal", "numeric")):
        return "numeric"
    if "date" in t or "time" in t:
        return "dateish"
    if any(tok in t for tok in ("char", "text", "str", "string", "clob")):
        return "string"
    return "unknown"


def rank_candidate_columns_for_pointer(
    *,
    pointer: str,
    dataset_columns: Sequence[str] | set[str],
    dataset_column_types: Mapping[str, str] | None = None,
    contract_input_schema: Mapping[str, Any] | None = None,
    algo_id: str = "",
    top_k: int = 3,
) -> list[str]:
    """
    Deterministically rank likely source columns for one contract pointer.

    Scoring combines:
    - provider seed hints (strong boost)
    - exact / normalized name matches
    - token overlap
    - light type preference
    """
    cols = sorted({str(c) for c in dataset_columns if isinstance(c, str) and c})
    if not cols:
        return []

    top_k = max(int(top_k), 1)

    leaf = _pointer_leaf(pointer)
    leaf_lower = leaf.lower()
    leaf_snake = _snakeish(leaf)
    leaf_compact = _compact(leaf)
    leaf_tokens = _split_tokens(leaf)

    expected_kind = _expected_kind_for_pointer(contract_input_schema, pointer)

    seed_map = provider_seed_pointer_candidates(algo_id)
    seeded = seed_map.get(pointer, [])
    seed_bonus = {name: 100 - idx for idx, name in enumerate(seeded)}

    scored: list[tuple[int, str]] = []

    for col in cols:
        score = 0

        # Strong deterministic boost for curated per-provider hints
        score += seed_bonus.get(col, 0)

        col_lower = col.lower()
        col_snake = _snakeish(col)
        col_compact = _compact(col)
        col_tokens = _split_tokens(col)

        # Exact and normalized name alignment
        if col == leaf:
            score += 40
        if col_lower == leaf_lower:
            score += 20
        if col_snake == leaf_snake:
            score += 35
        if col_compact == leaf_compact:
            score += 30

        # Partial containment after normalization
        if leaf_compact and (leaf_compact in col_compact or col_compact in leaf_compact):
            score += 12

        # Token overlap
        overlap = len(leaf_tokens & col_tokens)
        if overlap:
            score += overlap * 8

        # Very light type preference (ranking only, not hard filtering)
        col_kind = _column_kind((dataset_column_types or {}).get(col))
        if expected_kind == "numeric":
            if col_kind == "numeric":
                score += 8
            elif col_kind in {"dateish", "string"}:
                score -= 3
        elif expected_kind == "dateish":
            if col_kind in {"dateish", "string"}:
                score += 5

        if score > 0:
            scored.append((score, col))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [col for _, col in scored[:top_k]]


def build_pointer_candidate_cols(
    *,
    required_pointers: Sequence[str],
    dataset_columns: Sequence[str] | set[str],
    dataset_column_types: Mapping[str, str] | None = None,
    contract_input_schema: Mapping[str, Any] | None = None,
    algo_id: str = "",
    top_k: int = 3,
) -> dict[str, list[str]]:
    """
    Build pointer -> ranked candidate columns for required contract pointers only.
    Only includes pointers with at least one candidate.
    """
    out: dict[str, list[str]] = {}

    for ptr in required_pointers:
        ranked = rank_candidate_columns_for_pointer(
            pointer=ptr,
            dataset_columns=dataset_columns,
            dataset_column_types=dataset_column_types,
            contract_input_schema=contract_input_schema,
            algo_id=algo_id,
            top_k=top_k,
        )
        if ranked:
            out[ptr] = ranked

    return out