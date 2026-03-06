# if allowed_ops_profile is not provided, ops default to what the shipped JSON Schema allows (so no drift)

# If a provider schema includes fields like $id, title, description, or non-semantic metadata that changes frequently, the hash will change too.
# That’s not wrong, but can be annoying. If that becomes an issue, the next deterministic refinement is:
# normalize schema before hashing (drop description, maybe drop title, keep structural keywords)


# only when real provider schemas force it:
# TODO: Better contract schema traversal: current pointer/type extraction is MVP (properties + allOf + local refs). Extend to handle more patterns if provider schemas use them (anyOf/oneOf more robustly, nested refs, etc.).

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from importlib import resources
from jsonschema import Draft202012Validator
import re

from hdt_mapping_plan import errors as E
from hdt_mapping_plan.hashing import sha256_hex_of_structural_schema
from hdt_mapping_plan.vault_catalog import get_dataset_schema  # ok to import; no file I/O


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")

_FILTER_BOOL_OPS = {"and", "or", "not", "eq", "neq", "lt", "lte", "gt", "gte", "is_null", "not_null"}
_NUMERIC_KINDS = {"int64", "float64"}

_WINDOWS_ABS_PATH_RE = re.compile(r"^[a-zA-Z]:[\\/]")


@dataclass(frozen=True)
class CriticIssue:
    code: str  # e.g. "SCHEMA_INVALID"
    path: str  # JSON Pointer into the plan, e.g. "/contract/contract_hash"
    detail: str  # human-readable message
    severity: str = "error"  # "error" | "warning"
    hint: str | None = None


@dataclass(frozen=True)
class CriticReport:
    ok: bool
    errors: list[CriticIssue]
    warnings: list[CriticIssue]


# === helpers =============================================


def _load_mapping_plan_schema() -> dict[str, Any]:
    """Load MappingPlan JSON Schema shipped with the package."""
    p = resources.files("hdt_mapping_plan").joinpath("schema/mapping-plan.schema.json")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _json_pointer_from_path(parts: Iterable[Any]) -> str:
    """Convert jsonschema error path (deque) into a JSON Pointer string."""
    tokens: list[str] = []
    for part in parts:
        # JSON Pointer escaping: '~' -> '~0', '/' -> '~1'
        s = str(part).replace("~", "~0").replace("/", "~1")
        tokens.append(s)
    return "/" + "/".join(tokens) if tokens else ""


def _schema_default_expr_ops(schema: Mapping[str, Any]) -> set[str]:
    # Keep defaults in-sync with the shipped JSON Schema.
    return set(schema["$defs"]["expr"]["properties"]["op"]["enum"])  # type: ignore[index]


def _schema_default_filter_ops(schema: Mapping[str, Any]) -> set[str]:
    return set(schema["properties"]["row_filter"]["properties"]["op"]["enum"])  # type: ignore[index]


def _allowed_ops(profile: Mapping[str, Any] | None, *, schema: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """Return (expr_ops, filter_ops). If profile is missing/partial, fall back to schema defaults."""
    expr_ops = _schema_default_expr_ops(schema)
    filter_ops = _schema_default_filter_ops(schema)

    if profile:
        if isinstance(profile.get("expr_ops"), list):
            expr_ops = set(str(x) for x in profile["expr_ops"])
        if isinstance(profile.get("filter_ops"), list):
            filter_ops = set(str(x) for x in profile["filter_ops"])
    return expr_ops, filter_ops


def _walk_expr(node: Any, path_parts: list[Any]) -> Iterable[tuple[dict[str, Any], list[Any]]]:
    """Yield each expression dict node together with its JSON-Pointer path parts."""
    if not isinstance(node, dict):
        return
    if "op" not in node:
        return

    yield node, path_parts

    args = node.get("args")
    if isinstance(args, list):
        for i, child in enumerate(args):
            yield from _walk_expr(child, [*path_parts, "args", i])


def _walk_filter(node: Any, path_parts: list[Any]) -> Iterable[tuple[dict[str, Any], list[Any]]]:
    """Yield each filter dict node (row_filter or columnRef) with its JSON-Pointer path parts."""
    if not isinstance(node, dict):
        return
    if "op" not in node:
        return

    yield node, path_parts

    args = node.get("args")
    if isinstance(args, list):
        for i, child in enumerate(args):
            yield from _walk_filter(child, [*path_parts, "args", i])


def _profile_limits(profile: Mapping[str, Any] | None) -> dict[str, int]:
    """Complexity budgets. Works if no allowed_ops_profile.json exists."""
    defaults = {
        "max_record_mappings": 200,
        "max_expr_depth": 12,
        "max_expr_nodes_per_mapping": 80,
        "max_total_expr_nodes": 800,
        "max_filter_depth": 8,
        "max_filter_nodes": 80,
        "max_args": 6,
    }
    if not profile:
        return defaults
    limits = profile.get("limits")
    if not isinstance(limits, dict):
        return defaults

    out = dict(defaults)
    for k, v in limits.items():
        if k in out and isinstance(v, int) and v > 0:
            out[k] = v
    return out


def _expr_tree_stats(node: Any) -> tuple[int, int]:
    """Return (max_depth, node_count) for dict nodes that have 'op'."""
    if not isinstance(node, dict) or "op" not in node:
        return (0, 0)

    max_depth = 1
    nodes = 1

    args = node.get("args")
    if isinstance(args, list):
        for child in args:
            cd, cn = _expr_tree_stats(child)
            if cd > 0:
                max_depth = max(max_depth, 1 + cd)
            nodes += cn
    return (max_depth, nodes)


def _check_max_args(
    node: Any,
    *,
    max_args: int,
    base_path_parts: list[Any],
    issues: list[CriticIssue],
) -> None:
    """Walk expression/filter trees and enforce per-node args length budget."""
    if not isinstance(node, dict) or "op" not in node:
        return

    args = node.get("args")
    if isinstance(args, list):
        if len(args) > max_args:
            issues.append(
                CriticIssue(
                    code=E.MAX_ARGS_EXCEEDED,
                    path=_json_pointer_from_path([*base_path_parts, "args"]),
                    detail=f"args length {len(args)} exceeds max_args={max_args}",
                    severity="error",
                    hint="Simplify the expression/filter or split the plan.",
                )
            )
        for i, child in enumerate(args):
            _check_max_args(
                child,
                max_args=max_args,
                base_path_parts=[*base_path_parts, "args", i],
                issues=issues,
            )


def _pointer_unescape(token: str) -> str:
    # JSON Pointer decoding: ~1 => /, ~0 => ~
    return token.replace("~1", "/").replace("~0", "~")


def _split_json_pointer(ptr: str) -> list[str]:
    """Split a JSON Pointer into unescaped tokens. Raises ValueError if invalid."""
    if ptr == "":
        return []
    if not ptr.startswith("/"):
        raise ValueError("pointer must start with '/'")
    # Leading '/' means first token is after it
    raw_tokens = ptr.lstrip("/").split("/")
    return [_pointer_unescape(t) for t in raw_tokens]


def _resolve_local_ref(root_schema: Mapping[str, Any], ref: str) -> Any | None:
    """Resolve local $ref like '#/definitions/X' or '#/$defs/X'. Returns node or None."""
    if not ref.startswith("#"):
        return None
    frag = ref[1:]  # remove '#'
    try:
        tokens = _split_json_pointer(frag) if frag else []
    except ValueError:
        return None

    node: Any = root_schema
    for t in tokens:
        if isinstance(node, dict) and t in node:
            node = node[t]
        else:
            return None
    return node


def _deref(schema_root: Mapping[str, Any], node: Any, *, max_hops: int = 20) -> Any:
    """Follow local $ref chains (best-effort)."""
    cur = node
    hops = 0
    while isinstance(cur, dict) and "$ref" in cur and hops < max_hops:
        ref = cur.get("$ref")
        if not isinstance(ref, str):
            break
        resolved = _resolve_local_ref(schema_root, ref)
        if resolved is None:
            break
        cur = resolved
        hops += 1
    return cur


def _schema_has_property(schema_root: Mapping[str, Any], schema_node: Any, prop: str) -> Any | None:
    """
    Return the subschema for 'prop' if schema_node describes an object with that property.
    MVP traversal rules:
      - object properties via 'properties'
      - merge-ish support for allOf: property exists if any branch defines it
      - local $ref resolution
    """
    node = _deref(schema_root, schema_node)

    if isinstance(node, dict):
        # allOf: property may exist in any branch
        if "allOf" in node and isinstance(node["allOf"], list):
            for sub in node["allOf"]:
                found = _schema_has_property(schema_root, sub, prop)
                if found is not None:
                    return found

        props = node.get("properties")
        if isinstance(props, dict) and prop in props:
            return props[prop]

    return None


def _contract_pointer_exists(contract_input_schema: Mapping[str, Any], ptr: str) -> bool:
    """
    Check if ptr like '/person/birthDate' exists as a property chain in contract_input_schema.
    This treats ptr as a path through object properties.
    """
    tokens = _split_json_pointer(ptr)

    node: Any = contract_input_schema
    for t in tokens:
        nxt = _schema_has_property(contract_input_schema, node, t)
        if nxt is None:
            return False
        node = nxt
    return True


def _normalize_dataset_type(t: str) -> str:
    """
    Normalize dataset column type labels into:
      string | int64 | float64 | bool | date | datetime | unknown
    Works with SQLite decltypes and common catalog labels.
    """
    s = (t or "").strip().lower()

    if "bool" in s:
        return "bool"

    # datetime before date
    if "date-time" in s or "datetime" in s or "timestamp" in s:
        return "datetime"
    if s == "date" or s.endswith(" date") or s.endswith("date"):
        return "date"

    if "int" in s:
        return "int64"
    if any(x in s for x in ("real", "floa", "doub")):
        return "float64"
    if any(x in s for x in ("num", "dec")):
        return "float64"

    if any(x in s for x in ("char", "clob", "text", "varchar", "string")):
        return "string"

    return "unknown"


def _contract_pointer_subschema(contract_input_schema: Mapping[str, Any], ptr: str) -> Any | None:
    tokens = _split_json_pointer(ptr)
    node: Any = contract_input_schema
    for t in tokens:
        nxt = _schema_has_property(contract_input_schema, node, t)
        if nxt is None:
            return None
        node = nxt
    return _deref(contract_input_schema, node)


def _expected_scalar_kind_from_schema_node(schema_root: Mapping[str, Any], node: Any) -> str:
    """
    Return expected scalar kind: string|integer|number|boolean|date|datetime|unknown
    """
    n = _deref(schema_root, node)

    if not isinstance(n, dict):
        return "unknown"

    # Handle allOf: first matching scalar kind wins (simple MVP)
    if "allOf" in n and isinstance(n["allOf"], list):
        for sub in n["allOf"]:
            k = _expected_scalar_kind_from_schema_node(schema_root, sub)
            if k != "unknown":
                return k

    t = n.get("type")

    # nullable union like ["string","null"]
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        if len(non_null) == 1:
            t = non_null[0]
        else:
            return "unknown"

    if t == "string":
        fmt = n.get("format")
        if fmt == "date":
            return "date"
        if fmt == "date-time":
            return "datetime"
        return "string"
    if t == "integer":
        return "integer"
    if t == "number":
        return "number"
    if t == "boolean":
        return "boolean"

    return "unknown"


def _expected_kind_from_contract_node(schema_root: Mapping[str, Any], node: Any) -> str:
    """
    Map JSON Schema node to:
      string | int64 | float64 | bool | date | datetime | unknown
    """
    n = _deref(schema_root, node)
    if not isinstance(n, dict):
        return "unknown"

    # Handle allOf / anyOf / oneOf: pick first non-unknown consistent scalar
    for comb in ("allOf", "anyOf", "oneOf"):
        if comb in n and isinstance(n[comb], list):
            for sub in n[comb]:
                k = _expected_kind_from_contract_node(schema_root, sub)
                if k != "unknown":
                    return k

    t = n.get("type")

    # nullable union like ["string","null"]
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        if len(non_null) == 1:
            t = non_null[0]
        else:
            return "unknown"

    if t == "string":
        fmt = n.get("format")
        if fmt == "date":
            return "date"
        if fmt == "date-time":
            return "datetime"
        return "string"
    if t == "integer":
        return "int64"
    if t == "number":
        return "float64"
    if t == "boolean":
        return "bool"

    return "unknown"


def _is_kind_compatible(inferred: str, expected: str) -> bool:
    if expected == "unknown" or inferred == "unknown":
        return True  # Phase-1: don't fail when info is missing

    if inferred == expected:
        return True

    # int64 can flow to float64
    if inferred == "int64" and expected == "float64":
        return True

    # date/datetime are serialized as strings; allow them to satisfy expected string
    if expected == "string" and inferred in ("date", "datetime"):
        return True

    # Do NOT allow string -> date/datetime (forces parse_date/parse_datetime)
    return False


def _infer_expr_kind(
    expr: Any,
    *,
    dataset_column_types: Mapping[str, str] | None,
    issues: list[CriticIssue],
    path_parts: list[Any],
) -> str:
    if not isinstance(expr, dict) or "op" not in expr:
        return "unknown"

    op = str(expr.get("op"))

    def args_list() -> list[Any]:
        a = expr.get("args")
        return a if isinstance(a, list) else []

    def need_arity(min_n: int, max_n: int | None = None) -> list[Any]:
        a = args_list()
        ok = len(a) >= min_n and (max_n is None or len(a) <= max_n)
        if not ok:
            exp = f"{min_n}" if max_n == min_n else f"{min_n}..{max_n}"
            issues.append(
                CriticIssue(
                    code=E.ARITY_MISMATCH,
                    path=_json_pointer_from_path([*path_parts, "args"]),
                    detail=f"op '{op}' expects {exp} args; got {len(a)}",
                    severity="error",
                )
            )
        return a

    def require_kind(actual: str, expected_kinds: set[str], *, at: list[Any]) -> None:
        if actual == "unknown":
            return
        if actual not in expected_kinds:
            issues.append(
                CriticIssue(
                    code=E.ARG_TYPE_MISMATCH,
                    path=_json_pointer_from_path(at),
                    detail=f"op '{op}' argument type {actual} not in {sorted(expected_kinds)}",
                    severity="error",
                )
            )

    if op == "column":
        name = str(expr.get("name") or "")
        if not dataset_column_types:
            return "unknown"
        return _normalize_dataset_type(dataset_column_types.get(name, "unknown"))

    if op == "const":
        v = expr.get("value")
        if isinstance(v, bool):
            return "bool"
        if isinstance(v, int) and not isinstance(v, bool):
            return "int64"
        if isinstance(v, float):
            return "float64"
        if isinstance(v, str):
            return "string"
        return "unknown"  # null or other

    if op == "cast":
        a = need_arity(1, 1)
        _infer_expr_kind(
            a[0], dataset_column_types=dataset_column_types, issues=issues, path_parts=[*path_parts, "args", 0]
        )
        # cast target is definitive
        tgt = str(expr.get("type") or "")
        if tgt in ("string", "int64", "float64", "bool", "date", "datetime"):
            return tgt
        return "unknown"

    if op == "to_string":
        a = need_arity(1, 1)
        if a:
            _infer_expr_kind(
                a[0], dataset_column_types=dataset_column_types, issues=issues, path_parts=[*path_parts, "args", 0]
            )
        return "string"

    if op == "parse_date":
        a = need_arity(1, 1)
        if a:
            k = _infer_expr_kind(
                a[0], dataset_column_types=dataset_column_types, issues=issues, path_parts=[*path_parts, "args", 0]
            )
            require_kind(k, {"string", "date", "datetime"}, at=[*path_parts, "args", 0])
        return "date"

    if op == "parse_datetime":
        a = need_arity(1, 1)
        if a:
            k = _infer_expr_kind(
                a[0], dataset_column_types=dataset_column_types, issues=issues, path_parts=[*path_parts, "args", 0]
            )
            require_kind(k, {"string", "date", "datetime"}, at=[*path_parts, "args", 0])
        return "datetime"

    if op in ("lower", "upper"):
        a = need_arity(1, 1)
        if a:
            k = _infer_expr_kind(
                a[0], dataset_column_types=dataset_column_types, issues=issues, path_parts=[*path_parts, "args", 0]
            )
            require_kind(k, {"string"}, at=[*path_parts, "args", 0])
        return "string"

    if op == "scale":
        a = need_arity(1, 1)
        if a:
            k = _infer_expr_kind(
                a[0], dataset_column_types=dataset_column_types, issues=issues, path_parts=[*path_parts, "args", 0]
            )
            require_kind(k, {"int64", "float64"}, at=[*path_parts, "args", 0])
        return "float64"

    if op == "round":
        a = need_arity(1, 1)
        if a:
            k = _infer_expr_kind(
                a[0], dataset_column_types=dataset_column_types, issues=issues, path_parts=[*path_parts, "args", 0]
            )
            require_kind(k, {"int64", "float64"}, at=[*path_parts, "args", 0])
            # preserve int64 if rounding an int64 (optional)
            return "int64" if k == "int64" else "float64"
        return "float64"

    if op == "coalesce":
        a = need_arity(1, 8)
        kinds: list[str] = []
        for i, child in enumerate(a):
            k = _infer_expr_kind(
                child, dataset_column_types=dataset_column_types, issues=issues, path_parts=[*path_parts, "args", i]
            )
            if k != "unknown":
                kinds.append(k)

        if not kinds:
            return "unknown"

        # unify int64+float64 => float64
        if all(k == "int64" for k in kinds):
            return "int64"
        if all(k in ("int64", "float64") for k in kinds):
            return "float64"
        if all(k == "string" for k in kinds):
            return "string"
        if all(k == "bool" for k in kinds):
            return "bool"
        if all(k == "date" for k in kinds):
            return "date"
        if all(k == "datetime" for k in kinds):
            return "datetime"

        return "unknown"

    return "unknown"


def _infer_literal_kind(v: Any) -> str:
    """Infer scalar kind from a filter literal (primitive)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int) and not isinstance(v, bool):
        return "int64"
    if isinstance(v, float):
        return "float64"
    if isinstance(v, str):
        s = v.strip()
        if _DATE_RE.match(s):
            return "date"
        if _DATETIME_RE.match(s):
            return "datetime"
        return "string"
    return "unknown"


def _infer_columnref_kind(
    node: Mapping[str, Any],
    *,
    dataset_column_types: Mapping[str, str] | None,
) -> str:
    if not dataset_column_types:
        return "unknown"
    name = str(node.get("name") or "")
    if not name:
        return "unknown"
    # reuse your dataset normalizer from 1.5.1 if you have it; otherwise this minimal mapping:
    return _normalize_dataset_type(dataset_column_types.get(name, "unknown"))  # type: ignore[name-defined]


def _infer_filter_expr_kind(
    node: Any,
    *,
    dataset_column_types: Mapping[str, str] | None,
) -> str:
    """
    Infer kind of a filterExpr:
      - dict with op=='column' => column kind
      - dict with op in filter ops => bool (row_filter expression)
      - primitive literal => inferred literal kind
    """
    if isinstance(node, dict) and "op" in node:
        op = str(node.get("op"))
        if op == "column":
            return _infer_columnref_kind(node, dataset_column_types=dataset_column_types)
        if op in _FILTER_BOOL_OPS:
            return "bool"
        return "unknown"
    return _infer_literal_kind(node)


def _types_compatible_eq(a: str, b: str) -> bool:
    """Compatibility for eq/neq."""
    if "unknown" in (a, b):
        return True
    if a == b:
        return True
    if a in _NUMERIC_KINDS and b in _NUMERIC_KINDS:
        return True
    return False


def _types_compatible_order(a: str, b: str) -> bool:
    """Compatibility for lt/lte/gt/gte."""
    if "unknown" in (a, b):
        return True
    if a in _NUMERIC_KINDS and b in _NUMERIC_KINDS:
        return True
    if a == b and a in {"string", "date", "datetime"}:
        return True
    return False


def _validate_row_filter_types(
    rf: Any,
    *,
    dataset_column_types: Mapping[str, str] | None,
    issues: list[CriticIssue],
    warnings: list[CriticIssue],
    path_parts: list[Any],
) -> None:
    """
    Deterministic row_filter typing + arity validation.
    Traverses both dict nodes and primitive literals in args.
    """
    if not isinstance(rf, dict) or "op" not in rf:
        return

    op = str(rf.get("op"))
    args = rf.get("args")
    args_list = args if isinstance(args, list) else []

    # ---- arity rules ----
    def arity(expected: str) -> None:
        issues.append(
            CriticIssue(
                code=E.ARITY_MISMATCH,
                path=_json_pointer_from_path([*path_parts, "args"]),
                detail=f"row_filter op '{op}' expects {expected} args; got {len(args_list)}",
                severity="error",
            )
        )

    if op in {"not", "is_null", "not_null"}:
        if len(args_list) != 1:
            arity("1")
    elif op in {"eq", "neq", "lt", "lte", "gt", "gte"}:
        if len(args_list) != 2:
            arity("2")
    elif op in {"and", "or"}:
        if len(args_list) < 2:
            arity(">=2")

    # ---- recurse for nested filter expressions ----
    # Only recurse into dict children that are themselves row_filter objects,
    # so we validate arity/types all the way down.
    for i, child in enumerate(args_list):
        if isinstance(child, dict) and str(child.get("op")) in _FILTER_BOOL_OPS:
            _validate_row_filter_types(
                child,
                dataset_column_types=dataset_column_types,
                issues=issues,
                warnings=warnings,
                path_parts=[*path_parts, "args", i],
            )

    # ---- type checks by op category ----
    # Infer kinds of immediate args (including literals)
    kinds = [_infer_filter_expr_kind(a, dataset_column_types=dataset_column_types) for a in args_list]

    # Warn once if we see column refs but have no type info
    if dataset_column_types is None:
        if any(isinstance(a, dict) and str(a.get("op")) == "column" for a in args_list):
            warnings.append(
                CriticIssue(
                    code=E.TYPE_INFO_MISSING,
                    path="/dataset",
                    detail="dataset_column_types not provided; row_filter type checking is limited",
                    severity="warning",
                    hint="Pass column->type mapping from vault catalog introspection.",
                )
            )

    def arg_type_mismatch(i: int, expected: str) -> None:
        issues.append(
            CriticIssue(
                code=E.ARG_TYPE_MISMATCH,
                path=_json_pointer_from_path([*path_parts, "args", i]),
                detail=f"row_filter op '{op}' arg type {kinds[i]} is not compatible with {expected}",
                severity="error",
            )
        )

    def type_mismatch(detail: str) -> None:
        issues.append(
            CriticIssue(
                code=E.TYPE_MISMATCH,
                path=_json_pointer_from_path(path_parts),
                detail=detail,
                severity="error",
            )
        )

    if op in {"and", "or"}:
        for i, k in enumerate(kinds):
            if k not in ("bool", "unknown"):
                arg_type_mismatch(i, "bool")
        return

    if op == "not":
        if len(kinds) >= 1 and kinds[0] not in ("bool", "unknown"):
            arg_type_mismatch(0, "bool")
        return

    if op in {"is_null", "not_null"}:
        # accept any scalar (including bool). no additional type constraints
        return

    if op in {"eq", "neq"}:
        if len(kinds) >= 2 and not _types_compatible_eq(kinds[0], kinds[1]):
            type_mismatch(f"type mismatch in '{op}': {kinds[0]} vs {kinds[1]}")
        return

    if op in {"lt", "lte", "gt", "gte"}:
        # Disallow comparing booleans (unless unknown)
        if len(kinds) >= 2:
            for i, k in enumerate(kinds[:2]):
                if k == "bool":
                    arg_type_mismatch(i, "non-bool comparable")
            if not _types_compatible_order(kinds[0], kinds[1]):
                type_mismatch(f"type mismatch in '{op}': {kinds[0]} vs {kinds[1]}")
        return


def _output_policy(profile: Mapping[str, Any] | None) -> tuple[list[str], set[str]]:
    """
    Return (allowed_destination_prefixes, allowed_formats).
    Defaults are strict and match your schema.
    Optional overrides can be provided under profile["output"].
    """
    dest_prefixes = ["vault://"]
    formats = {"json", "jsonl", "parquet"}

    if not profile:
        return dest_prefixes, formats

    out = profile.get("output")
    if not isinstance(out, dict):
        return dest_prefixes, formats

    if isinstance(out.get("allowed_destination_prefixes"), list):
        dest_prefixes = [str(x) for x in out["allowed_destination_prefixes"] if str(x)]
    if isinstance(out.get("allowed_formats"), list):
        formats = {str(x) for x in out["allowed_formats"] if str(x)}

    return dest_prefixes, formats


def _is_safe_destination(dest: str, *, allowed_prefixes: list[str]) -> tuple[bool, str | None]:
    """
    Returns (ok, reason).
    Enforces: must match allowed prefixes + no traversal + no absolute paths + no whitespace.
    """
    if not dest or not isinstance(dest, str):
        return False, "destination is empty"

    d = dest.strip()
    if d != dest:
        return False, "destination has leading/trailing whitespace"

    if any(ch.isspace() for ch in dest):
        return False, "destination contains whitespace"

    if not any(dest.startswith(p) for p in allowed_prefixes):
        return False, f"destination must start with one of {allowed_prefixes}"

    # Reject URL-ish/OS path escapes even if prefix list changes later
    lowered = dest.lower()
    if lowered.startswith(("http://", "https://", "file://", "s3://", "gs://", "ftp://")):
        return False, "destination uses a non-vault URI scheme"

    # Reject absolute file paths
    if dest.startswith(("/", "\\")) or _WINDOWS_ABS_PATH_RE.match(dest):
        return False, "destination looks like an absolute filesystem path"

    # Reject traversal
    if "/../" in dest or dest.endswith("/..") or "\\..\\" in dest or dest.endswith("\\.."):
        return False, "destination contains path traversal '..'"

    return True, None


def _dedupe_issues(items: list[CriticIssue]) -> list[CriticIssue]:
    seen: set[tuple[str, str, str, str, str | None]] = set()
    out: list[CriticIssue] = []
    for it in items:
        key = (it.code, it.path, it.detail, it.severity, it.hint)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _typing_policy(profile: Mapping[str, Any] | None) -> str:
    """
    Returns typing mode:
      - "strict_dates" (default): unknown inference is error only for date/datetime expectations
      - "permissive": unknown inference is always a warning
      - "strict_all": unknown inference is always an error
    """
    if not profile:
        return "strict_dates"
    t = profile.get("typing")
    if not isinstance(t, dict):
        return "strict_dates"
    mode = str(t.get("mode") or "strict_dates")
    if mode not in {"strict_dates", "permissive", "strict_all"}:
        return "strict_dates"
    return mode


def _critic_limits(profile: Mapping[str, Any] | None) -> tuple[int, int]:
    """
    Returns (max_errors, max_warnings) for CriticReport payloads.
    Defaults: 50/50.
    """
    max_errors, max_warnings = 50, 50
    if not profile:
        return max_errors, max_warnings
    c = profile.get("critic")
    if not isinstance(c, dict):
        return max_errors, max_warnings
    me = c.get("max_errors")
    mw = c.get("max_warnings")
    if isinstance(me, int) and me > 0:
        max_errors = me
    if isinstance(mw, int) and mw > 0:
        max_warnings = mw
    return max_errors, max_warnings


def _required_leaf_contract_pointers(schema: Mapping[str, Any], prefix: str = "") -> list[str]:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    required = set(schema.get("required") or [])
    out: list[str] = []
    for name, sub in props.items():
        p = f"{prefix}/{name}"
        if isinstance(sub, dict) and isinstance(sub.get("properties"), dict):
            if name in required:
                out.extend(_required_leaf_contract_pointers(sub, p))
        else:
            if name in required:
                out.append(p)
    return out


# === end helpers ==================================================================================


def validate_plan_contract_required_fields(
    plan: dict[str, Any],
    *,
    contract_input_schema: Mapping[str, Any] | None,
) -> CriticReport:
    """S2 Contract completeness: required fields in input schema must be mapped."""
    if not contract_input_schema:
        return CriticReport(
            ok=False,
            errors=[
                CriticIssue(
                    code=E.CONTRACT_SCHEMA_MISSING,
                    path="/contract",
                    detail="contract_input_schema not provided; cannot validate required contract fields",
                    severity="error",
                    hint="Host must pass the provider input.schema.json dict.",
                )
            ],
            warnings=[],
        )

    required_ptrs = _required_leaf_contract_pointers(contract_input_schema)
    rm = plan.get("record_mapping") or {}
    rm_keys = set(rm.keys()) if isinstance(rm, dict) else set()

    missing = [p for p in required_ptrs if p not in rm_keys]
    issues: list[CriticIssue] = []
    for ptr in missing:
        issues.append(
            CriticIssue(
                code=E.CONTRACT_REQUIRED_FIELD_MISSING,
                path=_json_pointer_from_path(["record_mapping"]),
                detail=f"missing required contract field mapping: {ptr}",
                severity="error",
                hint="Add a record_mapping entry for this pointer (usually op:'column' with an existing dataset column).",
            )
        )

    return CriticReport(ok=(len(issues) == 0), errors=issues, warnings=[])


def validate_plan_schema(plan: dict[str, Any]) -> CriticReport:
    """
    S1 Structural validation: validate the plan against the JSON Schema.

    NOTE: This does *not* perform semantic checks (S2) yet.
    """
    schema = _load_mapping_plan_schema()
    v = Draft202012Validator(schema)

    errors: list[CriticIssue] = []
    for err in sorted(
        v.iter_errors(plan),
        key=lambda e: (list(e.absolute_path), e.validator, str(e.message)),
    ):
        errors.append(
            CriticIssue(
                code=E.SCHEMA_INVALID,
                path=_json_pointer_from_path(err.absolute_path),
                detail=err.message,
                severity="error",
            )
        )

    return CriticReport(ok=(len(errors) == 0), errors=errors, warnings=[])


def validate_plan_semantics(
    plan: dict[str, Any],
    *,
    dataset_columns: set[str] | None,
    dataset_column_types: Mapping[str, str] | None = None,
    allowed_ops_profile: Mapping[str, Any] | None = None,
) -> CriticReport:
    """S2 Semantic validation:

    - Column safety:
        * required_columns ⊆ dataset_columns
        * every referenced column exists in dataset_columns
        * every referenced column is declared in required_columns
    - Op allowlist (policy-layer):
        * expr ops and filter ops must be permitted by allowed_ops_profile
    """
    if not dataset_columns:
        return CriticReport(
            ok=False,
            errors=[
                CriticIssue(
                    code=E.DATASET_SCHEMA_MISSING,
                    path="/dataset",
                    detail="dataset_columns not provided; cannot validate column safety",
                    severity="error",
                    hint="Host must pass the dataset's column names from vault_catalog.json.",
                )
            ],
            warnings=[],
        )

    schema = _load_mapping_plan_schema()
    allowed_expr_ops, allowed_filter_ops = _allowed_ops(allowed_ops_profile, schema=schema)

    req_cols: list[str] = list(plan.get("required_columns") or [])
    req_set = set(req_cols)

    issues: list[CriticIssue] = []
    warnings: list[CriticIssue] = []

    limits = _profile_limits(allowed_ops_profile)

    # 1) required_columns must exist in dataset schema
    for i, col in enumerate(req_cols):
        if col not in dataset_columns:
            issues.append(
                CriticIssue(
                    code=E.UNKNOWN_COLUMN,
                    path=_json_pointer_from_path(["required_columns", i]),
                    detail=f"required_columns includes unknown column: {col}",
                    severity="error",
                    hint="Remove it from required_columns or fix the column name to match the dataset schema.",
                )
            )

    # 2) record_mapping expressions: op allowlist + column usage
    rm = plan.get("record_mapping") or {}
    if isinstance(rm, dict):
        # (A) record_mapping size budget
        if len(rm) > limits["max_record_mappings"]:
            issues.append(
                CriticIssue(
                    code=E.TOO_MANY_RECORD_MAPPINGS,
                    path="/record_mapping",
                    detail=f"record_mapping has {len(rm)} entries; max is {limits['max_record_mappings']}",
                    severity="error",
                    hint="Reduce mapped fields or split into multiple plans.",
                )
            )

        total_nodes = 0

        for out_ptr, expr in rm.items():
            # (B) per-mapping complexity budgets
            d, n = _expr_tree_stats(expr)
            total_nodes += n

            if d > limits["max_expr_depth"]:
                issues.append(
                    CriticIssue(
                        code=E.MAX_DEPTH_EXCEEDED,
                        path=_json_pointer_from_path(["record_mapping", out_ptr]),
                        detail=f"expression depth {d} exceeds max_expr_depth={limits['max_expr_depth']}",
                        severity="error",
                    )
                )

            if n > limits["max_expr_nodes_per_mapping"]:
                issues.append(
                    CriticIssue(
                        code=E.MAX_NODES_EXCEEDED,
                        path=_json_pointer_from_path(["record_mapping", out_ptr]),
                        detail=f"expression nodes {n} exceeds max_expr_nodes_per_mapping={limits['max_expr_nodes_per_mapping']}",
                        severity="error",
                    )
                )

            _check_max_args(
                expr,
                max_args=limits["max_args"],
                base_path_parts=["record_mapping", out_ptr],
                issues=issues,
            )

            # (C) existing semantic checks (ops + column refs)
            for node, pparts in _walk_expr(expr, ["record_mapping", out_ptr]):
                op = str(node.get("op"))
                if op not in allowed_expr_ops:
                    issues.append(
                        CriticIssue(
                            code=E.OP_NOT_ALLOWED,
                            path=_json_pointer_from_path([*pparts, "op"]),
                            detail=f"expr op not allowed by profile: {op}",
                            severity="error",
                        )
                    )
                if op == "column":
                    name = str(node.get("name") or "")
                    if name and name not in dataset_columns:
                        issues.append(
                            CriticIssue(
                                code=E.UNKNOWN_COLUMN,
                                path=_json_pointer_from_path([*pparts, "name"]),
                                detail=f"referenced unknown column: {name}",
                                severity="error",
                            )
                        )
                    if name and name not in req_set:
                        issues.append(
                            CriticIssue(
                                code=E.COLUMN_NOT_DECLARED,
                                path=_json_pointer_from_path([*pparts, "name"]),
                                detail=f"referenced column is not declared in required_columns: {name}",
                                severity="error",
                                hint="Add the column to required_columns (minimization) or change the expression.",
                            )
                        )

        # (D) total budget across all mappings
        if total_nodes > limits["max_total_expr_nodes"]:
            issues.append(
                CriticIssue(
                    code=E.MAX_NODES_EXCEEDED,
                    path="/record_mapping",
                    detail=f"total expression nodes {total_nodes} exceeds max_total_expr_nodes={limits['max_total_expr_nodes']}",
                    severity="error",
                    hint="Simplify mappings or split into multiple plans.",
                )
            )

    # 3) row_filter: filter op allowlist + column usage
    rf = plan.get("row_filter")
    if rf is not None:
        for node, pparts in _walk_filter(rf, ["row_filter"]):
            op = str(node.get("op"))
            if op == "column":
                name = str(node.get("name") or "")
                if name and name not in dataset_columns:
                    issues.append(
                        CriticIssue(
                            code=E.UNKNOWN_COLUMN,
                            path=_json_pointer_from_path([*pparts, "name"]),
                            detail=f"row_filter references unknown column: {name}",
                            severity="error",
                        )
                    )
                if name and name not in req_set:
                    issues.append(
                        CriticIssue(
                            code=E.COLUMN_NOT_DECLARED,
                            path=_json_pointer_from_path([*pparts, "name"]),
                            detail=f"row_filter references column not declared in required_columns: {name}",
                            severity="error",
                        )
                    )
            else:
                if op not in allowed_filter_ops:
                    issues.append(
                        CriticIssue(
                            code=E.FILTER_OP_NOT_ALLOWED,
                            path=_json_pointer_from_path([*pparts, "op"]),
                            detail=f"filter op not allowed by profile: {op}",
                            severity="error",
                        )
                    )
        d, n = _expr_tree_stats(rf)

        if d > limits["max_filter_depth"]:
            issues.append(
                CriticIssue(
                    code=E.MAX_DEPTH_EXCEEDED,
                    path="/row_filter",
                    detail=f"row_filter depth {d} exceeds max_filter_depth={limits['max_filter_depth']}",
                    severity="error",
                )
            )

        if n > limits["max_filter_nodes"]:
            issues.append(
                CriticIssue(
                    code=E.MAX_NODES_EXCEEDED,
                    path="/row_filter",
                    detail=f"row_filter nodes {n} exceeds max_filter_nodes={limits['max_filter_nodes']}",
                    severity="error",
                )
            )

        _check_max_args(
            rf,
            max_args=limits["max_args"],
            base_path_parts=["row_filter"],
            issues=issues,
        )

        _validate_row_filter_types(
            rf,
            dataset_column_types=dataset_column_types,
            issues=issues,
            warnings=warnings,
            path_parts=["row_filter"],
        )

    # 4) grouping: treat group_by/order_by as column references
    grp = plan.get("grouping")
    if isinstance(grp, dict):
        for key in ("group_by", "order_by"):
            cols = grp.get(key)
            if not isinstance(cols, list):
                continue
            for i, col in enumerate(cols):
                name = str(col)
                if name not in dataset_columns:
                    issues.append(
                        CriticIssue(
                            code=E.UNKNOWN_COLUMN,
                            path=_json_pointer_from_path(["grouping", key, i]),
                            detail=f"grouping.{key} references unknown column: {name}",
                            severity="error",
                        )
                    )
                if name not in req_set:
                    issues.append(
                        CriticIssue(
                            code=E.COLUMN_NOT_DECLARED,
                            path=_json_pointer_from_path(["grouping", key, i]),
                            detail=f"grouping.{key} references column not declared in required_columns: {name}",
                            severity="error",
                        )
                    )

    # 5) output confinement
    out = plan.get("output")
    if isinstance(out, dict):
        dest = out.get("destination")
        fmt = out.get("format")

        allowed_prefixes, allowed_formats = _output_policy(allowed_ops_profile)

        if not isinstance(dest, str) or not dest:
            issues.append(
                CriticIssue(
                    code=E.OUTPUT_DEST_MALFORMED,
                    path="/output/destination",
                    detail="output.destination missing or not a string",
                    severity="error",
                )
            )
        else:
            ok, reason = _is_safe_destination(dest, allowed_prefixes=allowed_prefixes)
            if not ok:
                issues.append(
                    CriticIssue(
                        code=E.OUTPUT_DEST_NOT_ALLOWED,
                        path="/output/destination",
                        detail=f"output.destination not allowed: {reason}",
                        severity="error",
                        hint="Use a vault:// destination within the user-owned vault namespace.",
                    )
                )

        if not isinstance(fmt, str) or not fmt:
            issues.append(
                CriticIssue(
                    code=E.OUTPUT_FORMAT_NOT_ALLOWED,
                    path="/output/format",
                    detail="output.format missing or not a string",
                    severity="error",
                )
            )
        else:
            if fmt not in allowed_formats:
                issues.append(
                    CriticIssue(
                        code=E.OUTPUT_FORMAT_NOT_ALLOWED,
                        path="/output/format",
                        detail=f"output.format '{fmt}' not allowed; allowed: {sorted(allowed_formats)}",
                        severity="error",
                    )
                )

    issues_sorted = sorted(issues, key=lambda e: (e.path, e.code, e.detail))
    warnings_sorted = sorted(warnings, key=lambda e: (e.path, e.code, e.detail))
    return CriticReport(ok=(len(issues_sorted) == 0), errors=issues_sorted, warnings=warnings_sorted)


def validate_plan_contract_pointers(
    plan: dict[str, Any],
    *,
    dataset_columns: set[str] | None = None,
    dataset_column_types: Mapping[str, str] | None = None,
    allowed_ops_profile: Mapping[str, Any] | None = None,
    contract_input_schema: Mapping[str, Any] | None = None,
) -> CriticReport:
    """S2 Contract pointer integrity: every record_mapping JSON pointer must exist in input schema."""
    if not contract_input_schema:
        return CriticReport(
            ok=False,
            errors=[
                CriticIssue(
                    code=E.CONTRACT_SCHEMA_MISSING,
                    path="/contract",
                    detail="contract_input_schema not provided; cannot validate record_mapping pointers",
                    severity="error",
                    hint="Host must pass the provider input.schema.json dict.",
                )
            ],
            warnings=[],
        )

    issues: list[CriticIssue] = []

    rm = plan.get("record_mapping") or {}
    if isinstance(rm, dict):
        for out_ptr in rm.keys():
            if not isinstance(out_ptr, str):
                continue

            # Validate pointer syntax early
            try:
                _split_json_pointer(out_ptr)
            except ValueError as ex:
                issues.append(
                    CriticIssue(
                        code=E.CONTRACT_POINTER_INVALID,
                        path=_json_pointer_from_path(["record_mapping", out_ptr]),
                        detail=f"record_mapping key is not a valid JSON Pointer: {out_ptr} ({ex})",
                        severity="error",
                    )
                )
                continue

            if not _contract_pointer_exists(contract_input_schema, out_ptr):
                issues.append(
                    CriticIssue(
                        code=E.UNKNOWN_CONTRACT_FIELD,
                        path=_json_pointer_from_path(["record_mapping", out_ptr]),
                        detail=f"record_mapping points to a field not present in contract input schema: {out_ptr}",
                        severity="error",
                        hint="Fix the pointer or update the provider input schema/contract version.",
                    )
                )

    issues_sorted = sorted(issues, key=lambda e: (e.path, e.code, e.detail))
    return CriticReport(ok=(len(issues_sorted) == 0), errors=issues_sorted, warnings=[])


def compute_contract_schema_hash(schema_obj: Mapping[str, Any]) -> str:
    """
    Compute a stable structural hash for a provider input schema.

    The hash ignores clearly cosmetic / annotation-only metadata such as:
      - $id
      - title
      - description
      - examples
      - default
      - $comment

    This keeps contract hashes stable across harmless presentation edits,
    while still changing when structural content changes.
    """
    return sha256_hex_of_structural_schema(schema_obj)


def validate_plan_contract_hash(
    plan: dict[str, Any],
    *,
    contract_input_schema: Mapping[str, Any] | None,
) -> CriticReport:
    """S2 Contract integrity: plan.contract.contract_hash must match provider input schema hash."""
    if not contract_input_schema:
        return CriticReport(
            ok=False,
            errors=[
                CriticIssue(
                    code=E.CONTRACT_SCHEMA_MISSING,
                    path="/contract",
                    detail="contract_input_schema not provided; cannot validate contract_hash",
                    severity="error",
                    hint="Host must pass the provider input.schema.json dict.",
                )
            ],
            warnings=[],
        )

    contract = plan.get("contract") or {}
    if not isinstance(contract, dict):
        # S1 should already prevent this, but keep it safe.
        return CriticReport(
            ok=False,
            errors=[
                CriticIssue(
                    code=E.CONTRACT_HASH_MISSING,
                    path="/contract",
                    detail="contract object missing; cannot read contract_hash",
                    severity="error",
                )
            ],
            warnings=[],
        )

    expected = contract.get("contract_hash")
    if not isinstance(expected, str) or not expected.strip():
        return CriticReport(
            ok=False,
            errors=[
                CriticIssue(
                    code=E.CONTRACT_HASH_MISSING,
                    path="/contract/contract_hash",
                    detail="contract_hash missing or empty",
                    severity="error",
                    hint="Plan must include contract_hash binding it to the provider input schema.",
                )
            ],
            warnings=[],
        )

    plan_hash = contract.get("contract_hash")
    computed_hash = compute_contract_schema_hash(contract_input_schema)

    if plan_hash != computed_hash:
        return CriticReport(
            ok=False,
            errors=[
                CriticIssue(
                    code=E.CONTRACT_HASH_MISMATCH,
                    path="/contract/contract_hash",
                    detail=f"contract_hash mismatch: plan has {plan_hash}, computed {computed_hash}",
                    severity="error",
                    hint="Update the plan to match the provider schema used, or fetch the correct schema version.",
                )
            ],
            warnings=[],
        )

    return CriticReport(ok=True, errors=[], warnings=[])


def validate_plan_type_compatibility(
    plan: dict[str, Any],
    *,
    dataset_column_types: Mapping[str, str] | None,
    contract_input_schema: Mapping[str, Any] | None,
    allowed_ops_profile: Mapping[str, Any] | None = None,
) -> CriticReport:
    if not contract_input_schema:
        return CriticReport(
            ok=False,
            errors=[
                CriticIssue(
                    code=E.CONTRACT_SCHEMA_MISSING,
                    path="/contract",
                    detail="contract_input_schema not provided; cannot validate type compatibility",
                    severity="error",
                )
            ],
            warnings=[],
        )

    warnings: list[CriticIssue] = []
    if not dataset_column_types:
        warnings.append(
            CriticIssue(
                code=E.TYPE_INFO_MISSING,
                path="/dataset",
                detail="dataset_column_types not provided; type inference will be limited",
                severity="warning",
                hint="Pass column->type mapping from vault catalog introspection (SQLite decltypes).",
            )
        )

    issues: list[CriticIssue] = []

    rm = plan.get("record_mapping") or {}
    if isinstance(rm, dict):
        for out_ptr, expr in rm.items():
            if not isinstance(out_ptr, str):
                continue

            subschema = _contract_pointer_subschema(contract_input_schema, out_ptr)
            if subschema is None:
                # should already be caught by 1.4.1
                continue

            expected = _expected_kind_from_contract_node(contract_input_schema, subschema)
            if expected == "unknown":
                warnings.append(
                    CriticIssue(
                        code=E.UNSUPPORTED_CONTRACT_TYPE,
                        path=_json_pointer_from_path(["record_mapping", out_ptr]),
                        detail=f"cannot derive expected scalar type from contract schema at {out_ptr}",
                        severity="warning",
                    )
                )
                continue

            inferred = _infer_expr_kind(
                expr,
                dataset_column_types=dataset_column_types,
                issues=issues,
                path_parts=["record_mapping", out_ptr],
            )

            # if inferred == "unknown":
            #     warnings.append(
            #         CriticIssue(
            #             code=E.TYPE_INFERENCE_FAILED,
            #             path=_json_pointer_from_path(["record_mapping", out_ptr]),
            #             detail=f"cannot infer expression type for mapping to {out_ptr}",
            #             severity="warning",
            #         )
            #     )
            #     continue

            mode = _typing_policy(None)  # temporary default
            # ...but actually pass allowed_ops_profile into validate_plan_type_compatibility:

            mode = _typing_policy(allowed_ops_profile)

            if inferred == "unknown":
                if mode == "strict_all":
                    issues.append(
                        CriticIssue(
                            code=E.TYPE_INFERENCE_REQUIRED,
                            path=_json_pointer_from_path(["record_mapping", out_ptr]),
                            detail=f"cannot infer expression type, but contract expects {expected}",
                            severity="error",
                            hint="Provide dataset_column_types, or make the expression explicit (cast/parse_date/parse_datetime).",
                        )
                    )
                elif mode == "strict_dates" and expected in {"date", "datetime"}:
                    issues.append(
                        CriticIssue(
                            code=E.TYPE_INFERENCE_REQUIRED,
                            path=_json_pointer_from_path(["record_mapping", out_ptr]),
                            detail=f"cannot infer expression type for {out_ptr}, but contract expects {expected}",
                            severity="error",
                            hint="Use parse_date/parse_datetime or cast to an explicit type, or pass dataset_column_types from the vault catalog.",
                        )
                    )
                else:
                    warnings.append(
                        CriticIssue(
                            code=E.TYPE_INFERENCE_FAILED,
                            path=_json_pointer_from_path(["record_mapping", out_ptr]),
                            detail=f"cannot infer expression type for mapping to {out_ptr} (expected {expected})",
                            severity="warning",
                        )
                    )
                continue

            if not _is_kind_compatible(inferred, expected):
                issues.append(
                    CriticIssue(
                        code=E.TYPE_MISMATCH,
                        path=_json_pointer_from_path(["record_mapping", out_ptr]),
                        detail=f"type mismatch: inferred {inferred}, expected {expected}",
                        severity="error",
                        hint="Adjust the expression (cast/parse) or use different source columns.",
                    )
                )

    issues_sorted = sorted(issues, key=lambda e: (e.path, e.code, e.detail))
    warnings_sorted = sorted(warnings, key=lambda e: (e.path, e.code, e.detail))
    return CriticReport(ok=(len(issues_sorted) == 0), errors=issues_sorted, warnings=warnings_sorted)


def merge_reports(reports: list[CriticReport], *, profile: Mapping[str, Any] | None = None) -> CriticReport:
    errors: list[CriticIssue] = []
    warnings: list[CriticIssue] = []

    for r in reports:
        if r.errors:
            errors.extend(r.errors)
        if r.warnings:
            warnings.extend(r.warnings)

    errors = _dedupe_issues(errors)
    warnings = _dedupe_issues(warnings)

    # Deterministic order so diffs/prompts are stable
    errors_sorted = sorted(
        errors,
        key=lambda e: (e.path, e.code, e.detail, e.severity, e.hint or ""),
    )
    warnings_sorted = sorted(
        warnings,
        key=lambda e: (e.path, e.code, e.detail, e.severity, e.hint or ""),
    )

    max_errors, max_warnings = _critic_limits(profile)

    truncated = False
    if len(errors_sorted) > max_errors:
        errors_sorted = errors_sorted[:max_errors]
        truncated = True
    if len(warnings_sorted) > max_warnings:
        warnings_sorted = warnings_sorted[:max_warnings]
        truncated = True

    if truncated:
        warnings_sorted.append(
            CriticIssue(
                code=E.REPORT_TRUNCATED,
                path="",
                detail=f"critic report truncated to max_errors={max_errors}, max_warnings={max_warnings}",
                severity="warning",
                hint="Fix issues iteratively; increase critic.max_errors/max_warnings in profile if needed.",
            )
        )

    return CriticReport(ok=(len(errors_sorted) == 0), errors=errors_sorted, warnings=warnings_sorted)


def resolve_dataset_schema_from_catalog(
    plan: Mapping[str, Any],
    *,
    vault_catalog: Mapping[str, Any],
) -> tuple[set[str], Mapping[str, str]]:
    ds = plan.get("dataset") or {}
    if not isinstance(ds, dict):
        raise ValueError("plan.dataset missing or invalid")

    dataset_id = ds.get("dataset_id")
    table_name = ds.get("table_name")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("plan.dataset.dataset_id missing/invalid")
    if not isinstance(table_name, str) or not table_name:
        raise ValueError("plan.dataset.table_name missing/invalid")

    return get_dataset_schema(vault_catalog, dataset_id=dataset_id, table_name=table_name)


def validate_plan(
    plan: dict[str, Any],
    *,
    dataset_columns: set[str] | None = None,
    dataset_column_types: Mapping[str, str] | None = None,
    allowed_ops_profile: Mapping[str, Any] | None = None,
    contract_input_schema: Mapping[str, Any] | None = None,
    vault_catalog: Mapping[str, Any] | None = None,
) -> CriticReport:
    reports: list[CriticReport] = []

    # S1: schema (hard gate)
    s1 = validate_plan_schema(plan)
    reports.append(s1)
    if not s1.ok:
        # Cannot safely run further validators if shape is wrong.
        return merge_reports(reports)

    # Optional: resolve dataset schema from vault catalog (no file I/O here)
    if vault_catalog is not None and (dataset_columns is None or dataset_column_types is None):
        try:
            cols, types = resolve_dataset_schema_from_catalog(plan, vault_catalog=vault_catalog)
            if dataset_columns is None:
                dataset_columns = cols
            if dataset_column_types is None:
                dataset_column_types = types
        except Exception as ex:
            # Keep deterministic: surface as an error so caller knows why column safety couldn't run
            reports.append(
                CriticReport(
                    ok=False,
                    errors=[
                        CriticIssue(
                            code=E.DATASET_SCHEMA_MISSING,
                            path="/dataset",
                            detail=f"failed to resolve dataset schema from vault_catalog: {ex}",
                            severity="error",
                            hint="Pass correct vault_catalog for plan.dataset.dataset_id/table_name, or pass dataset_columns/types directly.",
                        )
                    ],
                    warnings=[],
                )
            )

    # S2: semantic checks (column safety, op allowlist, budgets, row_filter typing, output confinement, grouping checks)
    s2 = validate_plan_semantics(
        plan,
        dataset_columns=dataset_columns,
        dataset_column_types=dataset_column_types,
        allowed_ops_profile=allowed_ops_profile,
    )
    reports.append(s2)

    # Contract checks (safe to run; they self-report CONTRACT_SCHEMA_MISSING if schema not provided)
    # s_ptr = validate_plan_contract_pointers(plan, contract_input_schema=contract_input_schema)
    # reports.append(s_ptr)
    # Contract checks (safe to run; they self-report CONTRACT_SCHEMA_MISSING if schema not provided)
    s_ptr = validate_plan_contract_pointers(plan, contract_input_schema=contract_input_schema)
    s_req = validate_plan_contract_required_fields(plan, contract_input_schema=contract_input_schema)
    reports.append(s_req)
    reports.append(s_ptr)

    s_hash = validate_plan_contract_hash(plan, contract_input_schema=contract_input_schema)
    reports.append(s_hash)

    # Type compatibility (record_mapping vs contract schema)
    # (This validator should skip pointers that don't resolve, so it's safe even if pointer check failed.)
    s_types = validate_plan_type_compatibility(
        plan,
        dataset_column_types=dataset_column_types,
        contract_input_schema=contract_input_schema,
        allowed_ops_profile=allowed_ops_profile,
    )
    reports.append(s_types)

    return merge_reports(reports, profile=allowed_ops_profile)


def validate_and_lint_plan(
    plan: dict[str, Any],
    *,
    dataset_columns: set[str] | None = None,
    dataset_column_types: Mapping[str, str] | None = None,
    allowed_ops_profile: Mapping[str, Any] | None = None,
    contract_input_schema: Mapping[str, Any] | None = None,
    vault_catalog: Mapping[str, Any] | None = None,
) -> CriticReport:
    rep_validate = validate_plan(
        plan,
        dataset_columns=dataset_columns,
        dataset_column_types=dataset_column_types,
        allowed_ops_profile=allowed_ops_profile,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
    )

    rep_lint = CriticReport(ok=True, errors=[], warnings=[])

    # Only lint if schema passed; otherwise linter assumptions may be noisy.
    if validate_plan_schema(plan).ok:
        from hdt_mapping_plan.lint import lint_plan  # local import avoids circular import

        rep_lint = lint_plan(plan, profile=allowed_ops_profile)

    return merge_reports([rep_validate, rep_lint], profile=allowed_ops_profile)
