from __future__ import annotations

from types import SimpleNamespace
import pytest

import hdt_user_a2a.user_executor as ue


def test_parse_ollama_overrides_accepts_multiple_shapes() -> None:
    url, model = ue._parse_ollama_overrides({"ollama_url": "http://x:11434", "ollama_model": "m1"})
    assert url == "http://x:11434"
    assert model == "m1"

    url, model = ue._parse_ollama_overrides({"ollama": {"base_url": "http://y:11434", "model": "m2"}})
    assert url == "http://y:11434"
    assert model == "m2"

    url, model = ue._parse_ollama_overrides({"ollama": {"url": "http://z:11434"}, "model": "m3"})
    assert url == "http://z:11434"
    assert model == "m3"


class _FakeMessage:
    def __init__(self, data: dict):
        self._data = data

    def model_dump(self, mode: str = "json", exclude_none: bool = True) -> dict:
        # matches what _parse_request expects: {"parts":[{"type":"data","data":{...}}]}
        return {"parts": [{"type": "data", "data": self._data}]}


class _FakeContext:
    def __init__(self, req: dict):
        self.message = _FakeMessage(req)
        self.context_id = "ctx-1"
        self.task_id = "task-1"


class _FakeEventQueue:
    def __init__(self):
        self.events = []
        self.closed = False

    async def enqueue_event(self, msg) -> None:
        self.events.append(msg)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_execute_forwards_ops_profile_and_ollama_overrides(monkeypatch) -> None:
    # Env defaults should be ignored when overrides are present
    monkeypatch.setenv("OLLAMA_URL", "http://env:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "env-model")

    captured: dict[str, object] = {}

    class FakeOllamaClient:
        def __init__(self, cfg: ue.OllamaConfig):
            captured["cfg"] = cfg

    def fake_synthesize_plan_via_provider(
        *,
        client,
        provider_url: str,
        algo_id: str,
        algo_version: str,
        vault_catalog: dict,
        allowed_ops_profile=None,
        dataset_id=None,
        table_name=None,
        max_iters: int = 3,
        initial_candidates: int = 1,
        use_candidate_retrieval: bool = True,
        use_seed_hints: bool = True,
    ):
        captured["initial_candidates"] = initial_candidates
        captured["use_candidate_retrieval"] = use_candidate_retrieval
        captured["use_seed_hints"] = use_seed_hints
        captured["provider_url"] = provider_url
        captured["algo_id"] = algo_id
        captured["algo_version"] = algo_version
        captured["allowed_ops_profile"] = allowed_ops_profile

        report = SimpleNamespace(ok=True, errors=[], warnings=[])
        return SimpleNamespace(ok=True, iterations=1, plan={"plan_id": "p1"}, report=report)

    monkeypatch.setattr(ue, "OllamaClient", FakeOllamaClient)
    monkeypatch.setattr(ue, "synthesize_plan_via_provider", fake_synthesize_plan_via_provider)

    req = {
        "op": "mapping_plan.synthesize",
        "provider_url": "http://provider:9100/",
        "algo_id": "provider.obesityCoach",
        "algo_version": "0.1.0",
        "vault_catalog": {"datasets": []},
        "allowed_ops_profile": {"ops": ["column", "const"]},
        "ollama_url": "http://override:11434",
        "ollama_model": "override-model",
        "dataset_id": "vault_dataset_A",
        "table_name": "transactions",
        "max_iters": 2,
        "initial_candidates": 3,
        "use_candidate_retrieval": False,
        "use_seed_hints": False,
    }

    executor = ue.UserAgentExecutor()
    q = _FakeEventQueue()
    await executor.execute(_FakeContext(req), q)

    # Assert overrides were applied
    cfg = captured["cfg"]
    assert isinstance(cfg, ue.OllamaConfig)
    assert cfg.base_url == "http://override:11434"
    assert cfg.model == "override-model"

    # Assert allowlist was forwarded
    assert captured["allowed_ops_profile"] == {"ops": ["column", "const"]}

    # Basic sanity: executor responded and closed the queue
    assert len(q.events) == 1
    assert q.closed is True

    assert captured["initial_candidates"] == 3
    assert captured["use_candidate_retrieval"] is False
    assert captured["use_seed_hints"] is False
