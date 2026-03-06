from __future__ import annotations

from types import SimpleNamespace

import hdt_a2a.llm.loop_from_provider as lfp


def test_synthesize_plan_via_provider_forwards_knobs(monkeypatch) -> None:
    captured = {}

    def fake_fetch_contract_bundle(*, provider_url: str, algo_id: str, algo_version: str):
        return {"contract_input_schema": {"type": "object", "properties": {}}}

    def fake_synthesize_plan_with_repairs(**kwargs):
        captured.update(kwargs)
        report = SimpleNamespace(ok=True, errors=[], warnings=[])
        return SimpleNamespace(ok=True, iterations=1, plan={"plan_id": "p1"}, report=report)

    monkeypatch.setattr(lfp, "fetch_contract_bundle", fake_fetch_contract_bundle)
    monkeypatch.setattr(lfp, "synthesize_plan_with_repairs", fake_synthesize_plan_with_repairs)

    client = SimpleNamespace()

    res = lfp.synthesize_plan_via_provider(
        client=client,
        provider_url="http://provider:9100/",
        algo_id="provider.generic",
        algo_version="0.1.0",
        vault_catalog={"datasets": []},
        max_iters=2,
        initial_candidates=4,
        use_candidate_retrieval=False,
        use_seed_hints=False,
    )

    assert res.ok is True
    assert captured["max_iters"] == 2
    assert captured["initial_candidates"] == 4
    assert captured["use_candidate_retrieval"] is False
    assert captured["use_seed_hints"] is False
