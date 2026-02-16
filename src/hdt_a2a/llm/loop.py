from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from hdt_a2a.llm.ollama_client import OllamaClient
from hdt_a2a.llm.plan_synthesis import build_base_messages, generate_mapping_plan_candidate
from hdt_a2a.llm.repair import repair_mapping_plan_candidate
from hdt_mapping_plan.validate import CriticReport, validate_and_lint_plan


@dataclass(frozen=True)
class LoopResult:
    ok: bool
    plan: dict[str, Any] | None
    report: CriticReport
    iterations: int
    # Optional: keep intermediate reports for debugging/telemetry
    reports: list[CriticReport]


def synthesize_plan_with_repairs(
    *,
    client: OllamaClient,
    contract: Mapping[str, Any],
    contract_input_schema: Mapping[str, Any],
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None = None,
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
    base_messages = build_base_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=allowed_ops_profile,
    )

    # 1) initial synthesis
    plan = generate_mapping_plan_candidate(
        client=client,
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=allowed_ops_profile,
    )

    reports: list[CriticReport] = []
    iterations = 0

    while True:
        iterations += 1

        # 2) validate + lint deterministically
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
