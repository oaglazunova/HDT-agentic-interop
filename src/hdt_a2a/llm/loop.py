# TODO: Prompt cleanup (stop biasing the model toward must_include / rules)
# TODO: Lock down glue tests (without live servers)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from hdt_a2a.llm.ollama_client import OllamaClient
from hdt_a2a.llm.repair import repair_mapping_plan_candidate
from hdt_mapping_plan.validate import CriticReport, validate_and_lint_plan, compute_contract_schema_hash
from hdt_mapping_plan.vault_catalog import get_dataset_schema
from hdt_mapping_plan.normalize import apply_limits_policy, fill_contract_refs
from hdt_a2a.llm.plan_synthesis import (
    build_base_messages,
    generate_mapping_plan_candidate,
    generate_mapping_plan_candidates,
)
from hdt_mapping_plan.select import select_best_plan


@dataclass(frozen=True)
class LoopResult:
    ok: bool
    plan: dict[str, Any] | None
    report: CriticReport
    iterations: int
    # Optional: keep intermediate reports for debugging/telemetry
    reports: list[CriticReport]


# === helpers: =========================

def _apply_immutables(
    plan: dict[str, Any],
    *,
    contract: Mapping[str, Any],
    expected_hash: str,
    dataset_id: str,
    table_name: str,
    contract_ref: str | None = None,
    input_schema_ref: str | None = None,
) -> dict[str, Any]:
    # Ensure required fixed structure exists and is consistent
    plan["plan_version"] = "1.0"

    # algo (from host)
    plan["algo"] = {
        "algo_id": str(contract.get("algo_id", "")),
        "algo_version": str(contract.get("algo_version", "")),
    }

    # dataset (from host)
    plan["dataset"] = {"dataset_id": dataset_id, "table_name": table_name}

    # contract (from host)
    # If you don't have refs yet, still force stable placeholders (schema requires non-empty strings)
    plan["contract"] = {
        "contract_ref": contract_ref or "oci://local/contracts/UNKNOWN",
        "input_schema_ref": input_schema_ref or "oci://local/contracts/UNKNOWN#input.schema.json",
        "contract_hash": expected_hash,
    }
    return plan


def _infer_dataset_target(vault_catalog: Mapping[str, Any]) -> tuple[str, str]:
    datasets = vault_catalog.get("datasets") or []
    if not isinstance(datasets, list) or len(datasets) != 1 or not isinstance(datasets[0], dict):
        raise ValueError("vault_catalog ambiguous: pass dataset_id and table_name explicitly")
    ds = datasets[0]
    dataset_id = str(ds.get("dataset_id") or "")
    tables = ds.get("tables") or []
    if not dataset_id or not isinstance(tables, list) or len(tables) != 1 or not isinstance(tables[0], dict):
        raise ValueError("vault_catalog ambiguous: pass dataset_id and table_name explicitly")
    table_name = str(tables[0].get("table_name") or "")
    if not table_name:
        raise ValueError("vault_catalog missing table_name")
    return dataset_id, table_name


def _normalize_llm_plan_shape(plan: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic fix-ups for common LLM output mistakes:
    - If model wraps required keys under must_include, lift them to root.
    - Drop helper keys that are not allowed by schema (additionalProperties=false).
    """
    mi = plan.get("must_include")
    if isinstance(mi, dict):
        for k in ("limits", "output", "record_mapping", "required_columns"):
            if k not in plan and k in mi:
                plan[k] = mi[k]
        plan.pop("must_include", None)

    # These are prompt scaffolding / helper keys and must not be in the final plan
    for k in ("rules", "task", "immutables"):
        plan.pop(k, None)

    return plan

def _required_leaf_pointers(schema: Mapping[str, Any], prefix: str = "") -> list[str]:
    """
    Collect required leaf JSON Pointers from a JSON Schema (object-only traversal).
    Matches your prompt logic: only recurse into an object if that object is required at this level.
    """
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    required = set(schema.get("required") or [])
    out: list[str] = []
    for name, sub in props.items():
        p = f"{prefix}/{name}"
        if isinstance(sub, dict) and isinstance(sub.get("properties"), dict):
            if name in required:
                out.extend(_required_leaf_pointers(sub, p))
        else:
            if name in required:
                out.append(p)
    return out


def _collect_column_names_from_expr(expr: Any) -> set[str]:
    cols: set[str] = set()
    if not isinstance(expr, dict):
        return cols
    op = expr.get("op")
    if op == "column":
        name = expr.get("name")
        if isinstance(name, str) and name:
            cols.add(name)
    args = expr.get("args")
    if isinstance(args, list):
        for a in args:
            cols |= _collect_column_names_from_expr(a)
    return cols


def _collect_column_names(plan: Mapping[str, Any]) -> set[str]:
    cols: set[str] = set()

    rm = plan.get("record_mapping")
    if isinstance(rm, dict):
        for _, expr in rm.items():
            cols |= _collect_column_names_from_expr(expr)

    rf = plan.get("row_filter")
    if isinstance(rf, dict):
        cols |= _collect_column_names_from_expr(rf)

    grp = plan.get("grouping")
    if isinstance(grp, dict):
        for key in ("group_by", "order_by"):
            v = grp.get(key)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item:
                        cols.add(item)

    return cols


def _obesitycoach_pointer_candidates() -> dict[str, list[str]]:
    # Deterministic per-contract hints (same idea as your prompt payload).
    return {
        "/recordId": ["txn_id"],
        "/person/birthDate": ["dob"],
        "/day/date": ["date"],
        "/activity/steps": ["steps"],
        "/nutrition/caloriesIn": ["calories_in"],
        "/hydration/waterMl": ["water_ml"],
        "/sleep/minutes": ["sleep_minutes"],
    }


def _snakeish(s: str) -> str:
    # Minimal camel->snake for common cases
    out = []
    for ch in s:
        if ch.isupper():
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out).lstrip("_")


def _fallback_candidate_for_pointer(ptr: str, dataset_columns: set[str]) -> str | None:
    # Very small heuristic fallback if not in the curated dict.
    # Use last token and try direct / snake_case matches.
    last = ptr.rsplit("/", 1)[-1]
    if not last:
        return None
    cands = [last, _snakeish(last)]
    for c in cands:
        if c in dataset_columns:
            return c
    return None


def _ensure_required_contract_mappings(
    plan: dict[str, Any],
    *,
    contract_input_schema: Mapping[str, Any],
    dataset_columns: set[str],
    algo_id: str,
) -> dict[str, Any]:
    """
    Deterministically ensure that every required leaf pointer has a record_mapping entry.
    This prevents LLM "forgetfulness" from breaking strict validation.
    """
    required_ptrs = _required_leaf_pointers(contract_input_schema)
    rm = plan.get("record_mapping")
    if not isinstance(rm, dict):
        rm = {}
        plan["record_mapping"] = rm

    # Choose deterministic candidate map (per algo)
    pointer_to_cols: dict[str, list[str]] = {}
    if algo_id == "provider.obesityCoach":
        pointer_to_cols = _obesitycoach_pointer_candidates()

    for ptr in required_ptrs:
        if ptr in rm:
            continue

        # 1) Preferred: curated candidate list
        chosen: str | None = None
        for c in pointer_to_cols.get(ptr, []):
            if c in dataset_columns:
                chosen = c
                break

        # 2) Fallback: simple heuristic
        if chosen is None:
            chosen = _fallback_candidate_for_pointer(ptr, dataset_columns)

        # 3) Create deterministic expression (with date parsing for known date pointers)
        if chosen is not None:
            if ptr in ("/day/date", "/person/birthDate"):
                rm[ptr] = {
                    "op": "parse_date",
                    "format": "%Y-%m-%d",
                    "args": [{"op": "column", "name": chosen}],
                }
            else:
                rm[ptr] = {"op": "column", "name": chosen}
        else:
            # Last resort: const (typed-ish). Keep it simple; validator will still catch if wrong.
            if ptr in ("/day/date", "/person/birthDate"):
                rm[ptr] = {
                    "op": "parse_date",
                    "format": "%Y-%m-%d",
                    "args": [{"op": "const", "value": "1970-01-01"}],
                }
            else:
                rm[ptr] = {"op": "const", "value": 0}

    return plan


def _recompute_required_columns(plan: dict[str, Any]) -> dict[str, Any]:
    cols = sorted(_collect_column_names(plan))
    plan["required_columns"] = cols
    return plan


def _enforce_plan_invariants(
    plan: dict[str, Any],
    *,
    contract_input_schema: Mapping[str, Any],
    dataset_columns: set[str],
    algo_id: str,
) -> dict[str, Any]:
    # 1) ensure required pointers exist
    plan = _ensure_required_contract_mappings(
        plan,
        contract_input_schema=contract_input_schema,
        dataset_columns=dataset_columns,
        algo_id=algo_id,
    )
    # 2) required_columns must match actual referenced columns (minimized)
    plan = _recompute_required_columns(plan)
    return plan


def _postprocess_generated_plan(
    plan: dict[str, Any],
    *,
    contract: Mapping[str, Any],
    expected_hash: str,
    dataset_id: str,
    table_name: str,
    algo_id: str,
    algo_version: str,
    contract_input_schema: Mapping[str, Any],
    dataset_columns: set[str],
) -> dict[str, Any]:
    """
    Apply the deterministic host-side post-processing pipeline to a newly
    generated or repaired candidate.
    """
    plan = _normalize_llm_plan_shape(plan)

    plan = _apply_immutables(
        plan,
        contract=contract,
        expected_hash=expected_hash,
        dataset_id=dataset_id,
        table_name=table_name,
    )

    plan = fill_contract_refs(plan, algo_id=algo_id, algo_version=algo_version)
    plan = apply_limits_policy(plan)
    plan = _normalize_llm_plan_shape(plan)

    plan = _enforce_plan_invariants(
        plan,
        contract_input_schema=contract_input_schema,
        dataset_columns=dataset_columns,
        algo_id=algo_id,
    )

    return plan

# === end helpers ===========================


def synthesize_plan_with_repairs(
        *,
        client: OllamaClient,
        contract: Mapping[str, Any],
        contract_input_schema: Mapping[str, Any],
        vault_catalog: Mapping[str, Any],
        allowed_ops_profile: Mapping[str, Any] | None = None,
        dataset_id: str | None = None,
        table_name: str | None = None,
        dataset_columns: set[str] | None = None,
        dataset_column_types: Mapping[str, str] | None = None,
        contract_hash_strict: bool = True,
        max_iters: int = 3,
        initial_candidates: int = 1,
        use_candidate_retrieval: bool = True,
        use_seed_hints: bool = True,
) -> LoopResult:
    """
    Generate a MappingPlan candidate via structured output and repair using deterministic validation.

    - Uses the same base prompt context (contract schema + vault catalog).
    - Deterministic validator is the source of truth.
    - Stops when report.ok or max_iters reached.

    contract_hash_strict:
      If True, the validator will fail if contract_input_schema is missing or contract_hash mismatches.
      If False, we still pass contract_input_schema to validators if available, but caller may choose to
      tolerate missing schema earlier (not recommended for strict mode).
    """
    expected_hash = compute_contract_schema_hash(contract_input_schema)

    # Infer missing dataset/table WITHOUT overwriting provided values
    if dataset_id is None and table_name is None:
        dataset_id, table_name = _infer_dataset_target(vault_catalog)
    elif dataset_id is None and table_name is not None:
        # If there's exactly one dataset, use it; otherwise require explicit dataset_id
        datasets = vault_catalog.get("datasets") or []
        if not isinstance(datasets, list) or len(datasets) != 1 or not isinstance(datasets[0], dict):
            raise ValueError("vault_catalog ambiguous: pass dataset_id explicitly")
        dataset_id = str(datasets[0].get("dataset_id") or "")
        if not dataset_id:
            raise ValueError("vault_catalog missing dataset_id")
    elif dataset_id is not None and table_name is None:
        # If dataset has exactly one table, use it; otherwise require explicit table_name
        ds = next((d for d in (vault_catalog.get("datasets") or []) if
                   isinstance(d, dict) and d.get("dataset_id") == dataset_id), None)
        if not isinstance(ds, dict):
            raise ValueError(f"dataset_id not found in vault_catalog: {dataset_id}")
        tables = [t for t in (ds.get("tables") or []) if isinstance(t, dict)]
        if len(tables) != 1:
            raise ValueError("vault_catalog ambiguous: pass table_name explicitly")
        table_name = str(tables[0].get("table_name") or "")
        if not table_name:
            raise ValueError("vault_catalog missing table_name")

    # Validate that the chosen table exists (fails fast instead of silently drifting)
    _ = get_dataset_schema(vault_catalog, dataset_id=dataset_id, table_name=table_name)

    # If caller didn't provide column metadata, derive it deterministically from vault_catalog
    if dataset_columns is None or dataset_column_types is None:
        cols, types = get_dataset_schema(vault_catalog, dataset_id=dataset_id, table_name=table_name)
        if dataset_columns is None:
            dataset_columns = cols
        if dataset_column_types is None:
            dataset_column_types = types

    base_messages = build_base_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=allowed_ops_profile,
        expected_contract_hash=expected_hash,
        dataset_id=dataset_id,
        table_name=table_name,
        dataset_columns=dataset_columns,
        dataset_column_types=dataset_column_types,
        use_candidate_retrieval=use_candidate_retrieval,
        use_seed_hints=use_seed_hints,
    )

    algo_id = str(contract.get("algo_id") or "")
    algo_version = str(contract.get("algo_version") or "")
    if not algo_id or not algo_version:
        raise ValueError("contract must include algo_id and algo_version")

    # 1) initial synthesis: generate one or more candidates, then deterministically
    # select the best valid one (if any) before entering the repair loop.
    initial_candidates = max(int(initial_candidates), 1)

    raw_candidates = generate_mapping_plan_candidates(
        client=client,
        base_messages=base_messages,
        n=initial_candidates,
    )

    candidates = [
        _postprocess_generated_plan(
            p,
            contract=contract,
            expected_hash=expected_hash,
            dataset_id=dataset_id,
            table_name=table_name,
            algo_id=algo_id,
            algo_version=algo_version,
            contract_input_schema=contract_input_schema,
            dataset_columns=dataset_columns,
        )
        for p in raw_candidates
    ]

    # Fallback seed if none are immediately valid.
    plan = candidates[0]

    if len(candidates) > 1:
        selection = select_best_plan(
            candidates,
            dataset_columns=dataset_columns,
            dataset_column_types=dataset_column_types,
            allowed_ops_profile=allowed_ops_profile,
            contract_input_schema=contract_input_schema,
        )

        if selection.best_plan is not None:
            assert selection.best_report is not None
            return LoopResult(
                ok=True,
                plan=selection.best_plan,
                report=selection.best_report,
                iterations=1,
                reports=[selection.best_report],
            )

    reports: list[CriticReport] = []
    iterations = 0

    while True:
        iterations += 1

        report = validate_and_lint_plan(
            plan,
            dataset_columns=dataset_columns,
            dataset_column_types=dataset_column_types,
            allowed_ops_profile=allowed_ops_profile,
            contract_input_schema=contract_input_schema,
        )
        reports.append(report)

        if not report.errors:
            return LoopResult(ok=True, plan=plan, report=report, iterations=iterations, reports=reports)

        if iterations >= max_iters:
            return LoopResult(ok=False, plan=plan, report=report, iterations=iterations, reports=reports)

        # 3) repair using critic report
        plan = repair_mapping_plan_candidate(
            client=client,
            base_messages=base_messages,
            previous_plan=plan,
            critic_report=report,
        )

        plan = _postprocess_generated_plan(
            plan,
            contract=contract,
            expected_hash=expected_hash,
            dataset_id=dataset_id,
            table_name=table_name,
            algo_id=algo_id,
            algo_version=algo_version,
            contract_input_schema=contract_input_schema,
            dataset_columns=dataset_columns,
        )
