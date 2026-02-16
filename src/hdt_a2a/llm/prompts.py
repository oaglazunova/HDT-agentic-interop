from __future__ import annotations

import json
from typing import Any, Mapping, Sequence


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


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
