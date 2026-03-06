from __future__ import annotations

from typing import Any, Mapping

from hdt_a2a.provider_a2a_client import fetch_contract_bundle
from hdt_a2a.llm.loop import LoopResult, synthesize_plan_with_repairs
from hdt_a2a.llm.ollama_client import OllamaClient


def synthesize_plan_via_provider(
    *,
    client: OllamaClient,
    provider_url: str,
    algo_id: str,
    algo_version: str,
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None = None,
    dataset_id: str | None = None,
    table_name: str | None = None,
    max_iters: int = 3,
    initial_candidates: int = 1,
    use_candidate_retrieval: bool = True,
    use_seed_hints: bool = True,
) -> LoopResult:
    bundle = fetch_contract_bundle(
        provider_url=provider_url,
        algo_id=algo_id,
        algo_version=algo_version,
    )

    contract = {"algo_id": algo_id, "algo_version": algo_version}
    return synthesize_plan_with_repairs(
        client=client,
        contract=contract,
        contract_input_schema=bundle["contract_input_schema"],
        vault_catalog=vault_catalog,
        allowed_ops_profile=allowed_ops_profile,
        dataset_id=dataset_id,
        table_name=table_name,
        max_iters=max_iters,
        initial_candidates=initial_candidates,
        use_candidate_retrieval=use_candidate_retrieval,
        use_seed_hints=use_seed_hints,
    )
