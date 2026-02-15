# when start producing multiple candidates or need observability:
# TODO: Telemetry + explainability: return per-candidate evaluation summaries (score, warning count, top error codes, maybe plan_id) for telemetry logs

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from hdt_mapping_plan.validate import CriticReport, validate_and_lint_plan
from hdt_mapping_plan.lint import score_plan


@dataclass(frozen=True)
class SelectionResult:
    best_plan: dict[str, Any] | None
    best_report: CriticReport | None
    best_score: int | None
    # For debugging / telemetry
    evaluated: int
    valid: int


def _stable_plan_key(plan: Mapping[str, Any]) -> str:
    """
    Deterministic tie-breaker key. Prefer plan_id if present, else stable JSON.
    """
    pid = plan.get("plan_id")
    if isinstance(pid, str) and pid:
        return pid
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def select_best_plan(
    candidates: Sequence[dict[str, Any]],
    *,
    dataset_columns: set[str] | None = None,
    dataset_column_types: Mapping[str, str] | None = None,
    allowed_ops_profile: Mapping[str, Any] | None = None,
    contract_input_schema: Mapping[str, Any] | None = None,
) -> SelectionResult:
    """
    Evaluate candidates deterministically and select the best valid one.
    Lower score is better. Warnings are tie-breakers.
    """
    best_plan: dict[str, Any] | None = None
    best_report: CriticReport | None = None
    best_score: int | None = None

    evaluated = 0
    valid = 0

    for plan in candidates:
        evaluated += 1

        rep = validate_and_lint_plan(
            plan,
            dataset_columns=dataset_columns,
            dataset_column_types=dataset_column_types,
            allowed_ops_profile=allowed_ops_profile,
            contract_input_schema=contract_input_schema,
        )

        if not rep.ok:
            continue

        valid += 1

        sc = score_plan(plan, profile=allowed_ops_profile)
        warn_count = len(rep.warnings)

        if best_plan is None:
            best_plan, best_report, best_score = plan, rep, sc
            best_warn_count = warn_count
            best_key = _stable_plan_key(plan)
            continue

        assert best_score is not None
        assert best_report is not None

        # primary: lower score
        if sc < best_score:
            best_plan, best_report, best_score = plan, rep, sc
            best_warn_count = warn_count
            best_key = _stable_plan_key(plan)
            continue

        if sc > best_score:
            continue

        # tie 1: fewer warnings
        if warn_count < best_warn_count:
            best_plan, best_report, best_score = plan, rep, sc
            best_warn_count = warn_count
            best_key = _stable_plan_key(plan)
            continue

        if warn_count > best_warn_count:
            continue

        # tie 2: stable key (plan_id or stable JSON)
        key = _stable_plan_key(plan)
        if key < best_key:
            best_plan, best_report, best_score = plan, rep, sc
            best_warn_count = warn_count
            best_key = key

    return SelectionResult(
        best_plan=best_plan,
        best_report=best_report,
        best_score=best_score,
        evaluated=evaluated,
        valid=valid,
    )
