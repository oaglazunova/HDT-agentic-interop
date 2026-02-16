from __future__ import annotations

import json
from importlib import resources
from typing import Any, Mapping

from hdt_a2a.llm.ollama_client import OllamaClient
from hdt_a2a.llm.prompts import build_messages


def load_mapping_plan_schema() -> dict[str, Any]:
    p = resources.files("hdt_mapping_plan").joinpath("schema/mapping-plan.schema.json")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_base_messages(
    *,
    contract: Mapping[str, Any],
    contract_input_schema: Mapping[str, Any],
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    return build_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=allowed_ops_profile,
    )


def generate_mapping_plan_candidate(
    *,
    client: OllamaClient,
    contract: Mapping[str, Any],
    contract_input_schema: Mapping[str, Any],
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Calls Ollama structured output to produce a MappingPlan candidate dict.
    No validation here; the host/validator does that.
    """
    schema = load_mapping_plan_schema()
    messages = build_base_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=allowed_ops_profile,
    )
    return client.chat_json(messages, json_schema=schema)


