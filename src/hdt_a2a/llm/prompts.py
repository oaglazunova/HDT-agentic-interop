from __future__ import annotations

import json
from typing import Any, Mapping, Sequence
from importlib import resources

from hdt_mapping_plan.validate import compute_contract_schema_hash


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def _pick_dataset(vault_catalog: Mapping[str, Any]) -> tuple[str, str]:
    # Best-effort: first dataset + first table; fallback to your MVP defaults
    try:
        ds = (vault_catalog.get("datasets") or [])[0]
        dataset_id = ds.get("dataset_id") or "vault_dataset_A"
        table = (ds.get("tables") or [])[0]
        table_name = table.get("table_name") or "transactions"
        return str(dataset_id), str(table_name)
    except Exception:
        return "vault_dataset_A", "transactions"


def load_mapping_plan_schema() -> dict[str, Any]:
    p = resources.files("hdt_mapping_plan").joinpath("schema/mapping-plan.schema.json")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def negotiation_system_prompt() -> str:
    # Keep it short + strict. The schema enforcement does most of the work.
    return (
        "You produce MappingPlan JSON that will be executed deterministically.\n"
        "Return ONLY JSON that matches the provided JSON Schema.\n"
        "Do not include explanations or extra keys.\n"
        "Minimize required_columns and keep expressions simple.\n"
    )


def build_user_prompt(
    *,
    contract: Mapping[str, Any],
    contract_input_schema: Mapping[str, Any],
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None,
) -> str:
    """
    The LLM sees metadata only: contract ref + input schema + vault catalog (metadata).
    It must output a MappingPlan that maps contract fields to vault columns.
    """
    parts = [
        "You are generating a MappingPlan for a provider algorithm contract.",
        "You must use ONLY columns present in the vault catalog.",
        "You must declare every used column in required_columns.",
        "You must map record_mapping pointers that exist in the contract input schema.",
        "",
        "CONTRACT (metadata):",
        _json(contract),
        "",
        "CONTRACT INPUT SCHEMA (JSON Schema):",
        _json(contract_input_schema),
        "",
        "VAULT CATALOG (metadata only):",
        _json(vault_catalog),
    ]
    if allowed_ops_profile is not None:
        parts += ["", "ALLOWED OPS PROFILE:", _json(allowed_ops_profile)]
    return "\n".join(parts)


def build_messages(
    *,
    contract: Mapping[str, Any],
    contract_input_schema: Mapping[str, Any],
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": negotiation_system_prompt()},
        {
            "role": "user",
            "content": build_user_prompt(
                contract=contract,
                contract_input_schema=contract_input_schema,
                vault_catalog=vault_catalog,
                allowed_ops_profile=allowed_ops_profile,
            ),
        },
    ]


def build_base_messages(
    *,
    contract: Mapping[str, Any],
    contract_input_schema: Mapping[str, Any],
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None,
    expected_contract_hash: str | None = None,
    dataset_id: str | None = None,
    table_name: str | None = None,
    dataset_columns: set[str] | None = None,
    dataset_column_types: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    if expected_contract_hash is None:
        expected_contract_hash = compute_contract_schema_hash(contract_input_schema)

    if dataset_id is None or table_name is None:
        ds_id, tb = _pick_dataset(vault_catalog)
        dataset_id = dataset_id or ds_id
        table_name = table_name or tb

    cols = sorted(dataset_columns or [])
    types = {k: dataset_column_types[k] for k in sorted(dataset_column_types or {})}

    return [
        {
            "role": "system",
            "content": (
                "You output ONLY a single JSON object. No markdown, no comments, no extra keys. "
                "All expressions in record_mapping MUST be objects like "
                '{"op":"column","name":"dob"} (never strings like ${dob}).'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Create a Mapping Plan JSON that will pass deterministic validation.",
                    "immutables": {
                        "plan_version": "1.0",
                        "algo": {
                            "algo_id": contract["algo_id"],
                            "algo_version": contract["algo_version"],
                        },
                        "dataset": {"dataset_id": dataset_id, "table_name": table_name},
                        "contract": {
                            "contract_hash": expected_contract_hash,
                            "contract_ref": "oci://local/contracts/UNKNOWN",
                            "input_schema_ref": "oci://local/contracts/UNKNOWN#input.schema.json",
                        },
                    },
                    "dataset_columns": cols,
                    "dataset_column_types": types,
                    "must_include": {
                        "required_columns": ["dob"],
                        "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
                        "output": {
                            "destination": "vault://results/job_${JOB_ID}.jsonl",
                            "format": "jsonl",
                            "result_schema_ref": "oci://local/contracts/UNKNOWN#output.schema.json",
                        },
                        "limits": {
                            "max_rows": 100000,
                            "batch_rows": 5000,
                            "max_record_bytes": 16384,
                            "max_total_output_bytes": 200000000,
                        },
                    },
                    "rules": [
                        "required_columns must contain every referenced column, and only those needed.",
                        "record_mapping keys MUST be JSON Pointers like /person/birthDate.",
                        "record_mapping values MUST be expression objects with 'op'.",
                        f"contract.contract_hash MUST equal exactly {expected_contract_hash}.",
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]