from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from hdt_a2a.llm.ollama_client import OllamaClient
from hdt_a2a.llm.plan_synthesis import build_base_messages, generate_mapping_plan_candidate
from hdt_a2a.llm.repair import repair_mapping_plan_candidate
from hdt_mapping_plan.validate import CriticReport, validate_and_lint_plan, compute_contract_schema_hash
from hdt_mapping_plan.vault_catalog import get_dataset_schema

_IMMUTABLE_TOP_LEVEL = ("plan_version", "algo", "dataset", "contract")


@dataclass(frozen=True)
class LoopResult:
    ok: bool
    plan: dict[str, Any] | None
    report: CriticReport
    iterations: int
    # Optional: keep intermediate reports for debugging/telemetry
    reports: list[CriticReport]


# === helpers =========================

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


# === emd helpers ===========================


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

    if dataset_id is None or table_name is None:
        dataset_id, table_name = _infer_dataset_target(vault_catalog)

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
    )

    # 1) initial synthesis
    plan = generate_mapping_plan_candidate(
        client=client,
        base_messages=base_messages,
    )

    plan = _normalize_llm_plan_shape(plan)

    plan = _apply_immutables(
        plan,
        contract=contract,
        expected_hash=expected_hash,
        dataset_id=dataset_id,
        table_name=table_name,
    )

    plan = _normalize_llm_plan_shape(plan)  # <-- optional but safe (drops any extras)

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

        # Critical: re-apply immutables after every repair (model will try to “helpfully” change them)
        plan = _apply_immutables(
            plan,
            contract=contract,
            expected_hash=expected_hash,
            dataset_id=dataset_id,
            table_name=table_name,
        )