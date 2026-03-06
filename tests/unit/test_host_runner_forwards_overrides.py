from __future__ import annotations

import hdt_a2a.host.run_negotiation as hn


def test_call_user_agent_synthesize_forwards_ops_and_ollama(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            # simulate a2a response envelope the host parses
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "parts": [
                        {
                            "type": "data",
                            "data": {
                                "ok": True,
                                "iterations": 1,
                                "plan": {"plan_id": "p1"},
                                "report": {"ok": True, "errors": [], "warnings": []},
                            },
                        }
                    ]
                },
            }

    class FakeClient:
        def __init__(self, timeout=None):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            captured["url"] = url
            captured["body"] = json
            return FakeResp()

    # IMPORTANT: host uses httpx.Client(), not httpx.post()
    monkeypatch.setattr(hn.httpx, "Client", FakeClient)

    hn.call_user_agent_synthesize(
        user_url="http://user:9200/",
        provider_url="http://provider:9100/",
        algo_id="provider.obesityCoach",
        algo_version="0.1.0",
        vault_catalog={"datasets": []},
        allowed_ops_profile={"ops": ["column"]},
        dataset_id="vault_dataset_A",
        table_name="transactions",
        max_iters=3,
        initial_candidates=3,
        use_candidate_retrieval=False,
        use_seed_hints=False,
        ollama_url="http://localhost:11434",
        ollama_model="qwen2.5:7b-instruct-q4_0",
        timeout_s=123.0,
    )

    body = captured["body"]
    parts = body["params"]["message"]["parts"]
    data = parts[0]["data"]

    assert data["allowed_ops_profile"] == {"ops": ["column"]}
    assert data["ollama_url"] == "http://localhost:11434"
    assert data["ollama_model"] == "qwen2.5:7b-instruct-q4_0"
    assert data["dataset_id"] == "vault_dataset_A"
    assert data["table_name"] == "transactions"
    assert data["initial_candidates"] == 3
    assert data["use_candidate_retrieval"] is False
    assert data["use_seed_hints"] is False

    t = captured["timeout"]
    assert getattr(t, "read") == 123.0
