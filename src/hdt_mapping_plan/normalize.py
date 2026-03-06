from __future__ import annotations

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
