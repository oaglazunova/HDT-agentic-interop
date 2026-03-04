from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from hdt_mapping_plan.validate import compute_contract_schema_hash


class ContractNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class ContractKey:
    algo_id: str
    algo_version: str


class ContractRegistry:
    """
    Deterministic, file-backed registry for provider contracts.
    """

    def __init__(self) -> None:
        # Map (algo_id, algo_version) -> resource path within package
        self._index: dict[ContractKey, str] = {
            ContractKey("provider.obesityCoach", "0.1.0"): "contracts/provider_obesityCoach/0.1.0/input.schema.json",
        }

    def list_contracts(self) -> list[dict[str, str]]:
        return [
            {"algo_id": k.algo_id, "algo_version": k.algo_version}
            for k in sorted(self._index.keys(), key=lambda x: (x.algo_id, x.algo_version))
        ]

    def get_input_schema(self, *, algo_id: str, algo_version: str) -> dict[str, Any]:
        key = ContractKey(algo_id, algo_version)
        rel = self._index.get(key)
        if rel is None:
            raise ContractNotFoundError(f"Unknown contract: {algo_id}@{algo_version}")

        p = resources.files("hdt_provider_a2a").joinpath(rel)
        with p.open("r", encoding="utf-8-sig") as f:
            obj = json.load(f)

        if not isinstance(obj, dict):
            raise ValueError("Input schema must be a JSON object")
        return obj

    def get_contract_bundle(self, *, algo_id: str, algo_version: str) -> dict[str, Any]:
        schema = self.get_input_schema(algo_id=algo_id, algo_version=algo_version)
        expected_hash = compute_contract_schema_hash(schema)
        return {
            "contract": {"algo_id": algo_id, "algo_version": algo_version},
            "contract_input_schema": schema,
            "expected_contract_hash": expected_hash,
        }
