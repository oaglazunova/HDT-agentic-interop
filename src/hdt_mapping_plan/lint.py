# TODO: Keep linter thresholds in sync with validator budgets: now we mirror some defaults; either centralize defaults (shared config) or document that lint budgets intentionally track validator limits.

# Optional, only if/after recurring “valid but bad” plans appear:
# TODO: Contract-aware lint (postponable): warn on “valid but suspicious” mismatches that require contract knowledge (e.g., grouping used but contract has no aggregated fields; mapping to date-format fields but using string casts; coalesce across semantically different sources).
# TODO: more suspicious-pattern rules (postponable): deep but valid nesting, heavy string normalization, repeated coalesce, excessive parsing, etc. (only if you see these in practice).

from __future__ import annotations

from typing import Any, Mapping

from hdt_mapping_plan import errors as E
from hdt_mapping_plan.validate import CriticIssue, CriticReport  # reuse your existing dataclasses


def _json_pointer(path_parts: list[Any]) -> str:
    # Minimal JSON Pointer builder (same escaping rules as your validator)
    tokens: list[str] = []
    for part in path_parts:
        s = str(part).replace("~", "~0").replace("/", "~1")
        tokens.append(s)
    return "/" + "/".join(tokens) if tokens else ""


def _walk_expr_ops(expr: Any) -> list[str]:
    """Return a flat list of op names in an expr tree."""
    ops: list[str] = []
    if not isinstance(expr, dict) or "op" not in expr:
        return ops
    ops.append(str(expr.get("op")))
    args = expr.get("args")
    if isinstance(args, list):
        for child in args:
            ops.extend(_walk_expr_ops(child))
    return ops


def _count_casts_in_plan(plan: Mapping[str, Any]) -> int:
    rm = plan.get("record_mapping")
    if not isinstance(rm, dict):
        return 0
    casts = 0
    for _out_ptr, expr in rm.items():
        for op in _walk_expr_ops(expr):
            if op == "cast":
                casts += 1
    return casts


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


def _count_ops_in_expr(expr: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(expr, dict) or "op" not in expr:
        return counts
    op = str(expr.get("op"))
    counts[op] = counts.get(op, 0) + 1
    args = expr.get("args")
    if isinstance(args, list):
        for child in args:
            cc = _count_ops_in_expr(child)
            for k, v in cc.items():
                counts[k] = counts.get(k, 0) + v
    return counts


def _plan_expr_metrics(plan: Mapping[str, Any]) -> tuple[int, int, dict[str, int]]:
    """
    Return:
      - total_nodes across all record_mapping expr trees
      - max_depth across all record_mapping expr trees
      - aggregated op counts across all record_mapping expr trees
    """
    rm = plan.get("record_mapping")
    if not isinstance(rm, dict):
        return (0, 0, {})

    total_nodes = 0
    max_depth = 0
    op_counts: dict[str, int] = {}

    for _out_ptr, expr in rm.items():
        d, n = _expr_tree_stats(expr)
        total_nodes += n
        max_depth = max(max_depth, d)
        cc = _count_ops_in_expr(expr)
        for k, v in cc.items():
            op_counts[k] = op_counts.get(k, 0) + v

    return (total_nodes, max_depth, op_counts)


def _lint_thresholds(profile: Mapping[str, Any] | None) -> dict[str, float]:
    """
    Thresholds are ratios or counts; deterministic defaults.
    All are warnings, not errors.
    """
    defaults: dict[str, float] = {
        # warn if usage >= this fraction of budget
        "near_budget_ratio": 0.8,

        # warn if stringy ops >= this count
        "string_ops_warn": 10.0,

        # warn if coalesce >= this count
        "coalesce_warn": 5.0,

        # output suspicion heuristic
        "max_total_output_bytes_warn_ratio": 0.9,  # near the max_total_output_bytes cap in plan
    }
    if not profile:
        return defaults
    lint_cfg = profile.get("lint")
    if not isinstance(lint_cfg, dict):
        return defaults

    out = dict(defaults)
    for k, v in lint_cfg.items():
        if k in out and isinstance(v, (int, float)) and v > 0:
            out[k] = float(v)
    return out


def _semantic_budgets(profile: Mapping[str, Any] | None) -> dict[str, int]:
    """
    Mirrors your validator defaults. Keep these in sync manually (OK for Phase-1).
    """
    budgets = {
        "max_expr_depth": 12,
        "max_total_expr_nodes": 800,
    }
    if not profile:
        return budgets
    limits = profile.get("limits") if isinstance(profile, dict) else None
    if isinstance(limits, dict):
        for k in list(budgets.keys()):
            v = limits.get(k)
            if isinstance(v, int) and v > 0:
                budgets[k] = v
    return budgets



# === end helpers ==============================

def lint_plan(
    plan: Mapping[str, Any],
    *,
    profile: Mapping[str, Any] | None = None,
) -> CriticReport:
    """
    Deterministic linter: emits warnings only (never errors).
    This assumes S1 schema validation already passed.
    """
    warnings: list[CriticIssue] = []

    # Simple, deterministic heuristics (MVP)
    if isinstance(plan.get("grouping"), dict):
        warnings.append(
            CriticIssue(
                code=E.LINT_GROUPING_USED,
                path="/grouping",
                detail="grouping is used; this increases complexity and potential privacy surface",
                severity="warning",
                hint="Avoid grouping unless the provider contract explicitly requires aggregates.",
            )
        )

    if plan.get("row_filter") is not None:
        warnings.append(
            CriticIssue(
                code=E.LINT_ROW_FILTER_USED,
                path="/row_filter",
                detail="row_filter is used; ensure it is necessary and as simple as possible",
                severity="warning",
                hint="Prefer simple predicates; avoid deep boolean nesting.",
            )
        )

    # “many casts” threshold can be tuned via profile["lint"]["cast_warn_threshold"]
    lint_cfg = profile.get("lint") if isinstance(profile, dict) else None
    cast_warn_threshold = 3
    if isinstance(lint_cfg, dict) and isinstance(lint_cfg.get("cast_warn_threshold"), int):
        cast_warn_threshold = max(1, int(lint_cfg["cast_warn_threshold"]))

    cast_count = _count_casts_in_plan(plan)
    if cast_count >= cast_warn_threshold:
        warnings.append(
            CriticIssue(
                code=E.LINT_MANY_CASTS,
                path="/record_mapping",
                detail=f"plan uses {cast_count} casts; excessive casting can hide semantic mismatches",
                severity="warning",
                hint="Prefer using correctly typed source columns or fewer casts.",
            )
        )

    # ---- complexity-aware lint (warnings only) ----
    th = _lint_thresholds(profile)
    budgets = _semantic_budgets(profile)

    total_nodes, max_depth, op_counts = _plan_expr_metrics(plan)

    near_ratio = th["near_budget_ratio"]
    if budgets["max_total_expr_nodes"] > 0 and total_nodes >= near_ratio * budgets["max_total_expr_nodes"]:
        warnings.append(
            CriticIssue(
                code=E.LINT_NEAR_BUDGET,
                path="/record_mapping",
                detail=f"total expr nodes {total_nodes} is near budget max_total_expr_nodes={budgets['max_total_expr_nodes']}",
                severity="warning",
                hint="Prefer a simpler plan; consider splitting or removing redundant transforms.",
            )
        )

    if budgets["max_expr_depth"] > 0 and max_depth >= near_ratio * budgets["max_expr_depth"]:
        warnings.append(
            CriticIssue(
                code=E.LINT_NEAR_BUDGET,
                path="/record_mapping",
                detail=f"max expr depth {max_depth} is near budget max_expr_depth={budgets['max_expr_depth']}",
                severity="warning",
                hint="Flatten nested expressions; avoid deep coalesce/cast chains.",
            )
        )

    string_ops = op_counts.get("lower", 0) + op_counts.get("upper", 0) + op_counts.get("to_string", 0)
    if string_ops >= th["string_ops_warn"]:
        warnings.append(
            CriticIssue(
                code=E.LINT_STRING_HEAVY,
                path="/record_mapping",
                detail=f"plan uses {int(string_ops)} string-normalization ops (lower/upper/to_string)",
                severity="warning",
                hint="String-heavy plans can hide semantic mistakes; prefer typed columns and minimal formatting.",
            )
        )

    coalesce_count = op_counts.get("coalesce", 0)
    if coalesce_count >= th["coalesce_warn"]:
        warnings.append(
            CriticIssue(
                code=E.LINT_MANY_COALESCE,
                path="/record_mapping",
                detail=f"plan uses {coalesce_count} coalesce ops",
                severity="warning",
                hint="Excessive coalesce often indicates uncertain mappings; prefer a single authoritative source.",
            )
        )

    # ---- output limits suspicion (heuristic) ----
    limits = plan.get("limits") if isinstance(plan.get("limits"), dict) else {}
    if isinstance(limits, dict):
        max_total = limits.get("max_total_output_bytes")
        max_record = limits.get("max_record_bytes")
        max_rows = limits.get("max_rows")
        if isinstance(max_total, int) and isinstance(max_record, int) and isinstance(max_rows, int):
            # if max_total is extremely close to the theoretical worst case, warn
            worst_case = max_rows * max_record
            # warn when max_total is near the theoretical worst-case output budget
            if worst_case > 0 and max_total >= th["max_total_output_bytes_warn_ratio"] * worst_case:
                warnings.append(
                    CriticIssue(
                        code=E.LINT_OUTPUT_LIMITS_SUSPICIOUS,
                        path="/limits",
                        detail="output limits look permissive relative to max_rows and max_record_bytes",
                        severity="warning",
                        hint="Tighten limits where possible to reduce exfil surface and resource usage.",
                    )
                )

    warnings_sorted = sorted(warnings, key=lambda w: (w.path, w.code, w.detail))
    return CriticReport(ok=True, errors=[], warnings=warnings_sorted)


def score_plan(
    plan: Mapping[str, Any],
    *,
    profile: Mapping[str, Any] | None = None,
) -> int:
    """
    Deterministic “simplicity” score. Lower is better.
    Uses actual expression complexity (nodes/depth) + surface area.
    """
    rm = plan.get("record_mapping")
    mapping_count = len(rm) if isinstance(rm, dict) else 0

    total_nodes, max_depth, op_counts = _plan_expr_metrics(plan)
    cast_count = op_counts.get("cast", 0)
    string_ops = op_counts.get("lower", 0) + op_counts.get("upper", 0) + op_counts.get("to_string", 0)
    coalesce_count = op_counts.get("coalesce", 0)

    has_grouping = 1 if isinstance(plan.get("grouping"), dict) else 0
    has_row_filter = 1 if plan.get("row_filter") is not None else 0

    # Fixed weights for now (postpone tuning unless you need it)
    return (
        1 * mapping_count
        + 1 * total_nodes
        + 10 * max_depth
        + 5 * cast_count
        + 2 * string_ops
        + 3 * coalesce_count
        + 50 * has_grouping
        + 10 * has_row_filter
    )
