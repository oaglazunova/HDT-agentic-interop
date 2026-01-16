from __future__ import annotations

import json
from pathlib import Path

import pytest

from hdt_common.errors import REDACT_TOKEN
import hdt_mcp.policy.engine as pe


def test_apply_policy_safe_redacts_in_nested_lists_without_mutating_input(monkeypatch):
    """Redaction must work on dicts nested inside lists, and safe variant must not mutate input."""
    policy = {
        "tools": {
            "hdt.walk.fetch.v1": {
                "analytics": {"allow": True, "redact": ["records.token", "records.email"]},
            }
        }
    }

    monkeypatch.setattr(pe, "_POLICY_OVERRIDE", policy, raising=False)

    payload = {"records": [{"token": "T1", "email": "e@x", "keep": 1}]}
    original = json.loads(json.dumps(payload))

    out = pe.apply_policy_safe("analytics", "hdt.walk.fetch.v1", payload, client_id="ANY")
    assert "error" not in out
    assert payload == original  # unchanged

    assert out["records"][0]["token"] == REDACT_TOKEN
    assert out["records"][0]["email"] == REDACT_TOKEN
    assert out["records"][0]["keep"] == 1


def test_apply_policy_denies_and_does_not_mutate_payload(monkeypatch):
    policy = {"tools": {"hdt.walk.fetch.v1": {"modeling": {"allow": False}}}}
    monkeypatch.setattr(pe, "_POLICY_OVERRIDE", policy, raising=False)

    payload = {"records": [{"token": "SECRET"}]}
    out = pe.apply_policy("modeling", "hdt.walk.fetch.v1", payload, client_id="ANY")
    assert "error" in out
    assert out["error"]["code"] == "denied_by_policy"
    assert payload["records"][0]["token"] == "SECRET"  # not touched


def test_apply_policy_metrics_counts_redactions(monkeypatch):
    policy = {"tools": {"hdt.walk.fetch.v1": {"analytics": {"allow": True, "redact": ["a", "b.c"]}}}}
    monkeypatch.setattr(pe, "_POLICY_OVERRIDE", policy, raising=False)

    payload = {"a": "x", "b": {"c": "y"}}
    out, redactions = pe.apply_policy_metrics("analytics", "hdt.walk.fetch.v1", payload, client_id="ANY")
    assert "error" not in out
    assert out["a"] == REDACT_TOKEN
    assert out["b"]["c"] == REDACT_TOKEN
    assert redactions == 2


def test_explain_policy_file_loading_and_cache_paths(tmp_path: Path, monkeypatch):
    """Cover file load, missing-file, and exception-in-load branches."""
    # 1) Load from a real file
    pol = {"tools": {"hdt.walk.fetch.v1": {"analytics": {"allow": True, "redact": ["x"]}}}}
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(pol), encoding="utf-8")

    monkeypatch.setattr(pe, "_POLICY_OVERRIDE", None, raising=False)
    monkeypatch.setattr(pe, "_POLICY_PATH", p, raising=False)
    pe.policy_reset_cache()

    exp = pe.explain_policy("analytics", "hdt.walk.fetch.v1", client_id="ANY")
    assert exp["resolved"]["allow"] is True
    assert "x" in exp["resolved"]["redact"]

    # 2) Missing file -> empty policy (allow by default)
    monkeypatch.setattr(pe, "_POLICY_PATH", tmp_path / "missing.json", raising=False)
    pe.policy_reset_cache()
    exp2 = pe.explain_policy("analytics", "hdt.walk.fetch.v1", client_id="ANY")
    assert exp2["resolved"]["allow"] is True

    # 3) Load exception (path is a directory)
    monkeypatch.setattr(pe, "_POLICY_PATH", tmp_path, raising=False)
    pe.policy_reset_cache()
    exp3 = pe.explain_policy("analytics", "hdt.walk.fetch.v1", client_id="ANY")
    assert exp3["resolved"]["allow"] is True


def test_redact_path_edge_cases_do_not_crash(monkeypatch):
    policy = {"tools": {"hdt.walk.fetch.v1": {"analytics": {"allow": True, "redact": ["", None, 123]}}}}
    monkeypatch.setattr(pe, "_POLICY_OVERRIDE", policy, raising=False)
    payload = {"a": {"b": "x"}}
    out = pe.apply_policy_safe("analytics", "hdt.walk.fetch.v1", payload, client_id="ANY")
    assert "error" not in out
    # Invalid paths are ignored; payload should remain unchanged.
    assert out["a"]["b"] == "x"
