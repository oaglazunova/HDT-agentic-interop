from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from hdt_a2a.llm.loop import synthesize_plan_with_repairs
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "mapping_plan_golden"


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("case_*.json"))


class SequenceOllama(OllamaClient):
    def __init__(self, *, outputs: list[dict[str, Any]]) -> None:
        super().__init__(OllamaConfig(model="dummy"))
        self._outputs = [copy.deepcopy(x) for x in outputs]
        self.calls = 0

    def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
        if not self._outputs:
            raise AssertionError("No fake LLM outputs configured")

        idx = self.calls if self.calls < len(self._outputs) else len(self._outputs) - 1
        self.calls += 1
        return copy.deepcopy(self._outputs[idx])


def _read_case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case_path", _fixture_paths(), ids=lambda p: p.stem)
def test_golden_mapping_plan_cases(case_path: Path) -> None:
    case = _read_case(case_path)

    client = SequenceOllama(outputs=case["llm_outputs"])

    res = synthesize_plan_with_repairs(
        client=client,
        contract=case["contract"],
        contract_input_schema=case["contract_input_schema"],
        vault_catalog=case["vault_catalog"],
        allowed_ops_profile=case.get("allowed_ops_profile"),
        dataset_id=case.get("dataset_id"),
        table_name=case.get("table_name"),
        max_iters=int(case["expected"]["max_iters"]),
    )

    expected = case["expected"]

    assert res.ok is expected["ok"]
    assert res.iterations == expected["iterations"]
    assert res.iterations <= expected["max_iters"]

    if expected["ok"]:
        assert res.plan is not None
        assert res.report.errors == []
        assert res.plan["dataset"] == expected["dataset"]
        assert res.plan["required_columns"] == expected["required_columns"]

        for ptr, expected_op in expected["pointer_to_op"].items():
            expr = res.plan["record_mapping"][ptr]
            assert expr["op"] == expected_op

        for ptr, expected_col in expected["pointer_to_column"].items():
            expr = res.plan["record_mapping"][ptr]
            if expr["op"] == "column":
                assert expr["name"] == expected_col
            else:
                assert expr["args"][0]["op"] == "column"
                assert expr["args"][0]["name"] == expected_col