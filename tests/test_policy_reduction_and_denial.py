import json
import types
import pytest

# Import your MCP server module (adjust if your module path differs)
import HDT_MCP.server as srv


# ---------- helpers ----------

def _write_policy(tmp_path, monkeypatch, policy_obj):
    """Write a temporary policy.json and make the server use it."""
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(policy_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setenv("HDT_POLICY_PATH", str(p))
    # Use in-memory override so tests don't depend on module-level cache/path timing
    monkeypatch.setattr(srv, "_POLICY_OVERRIDE", policy_obj, raising=False)
    srv._policy_reset_cache()
    return p


class _DummyStats:
    def __init__(self, days, total_steps, avg_steps):
        self.days = days
        self.total_steps = total_steps
        self.avg_steps = avg_steps


class _DummyRecord:
    def __init__(self, date, steps, kcalories=42.5, distance_meters=None, duration=None):
        self.date = date
        self.steps = steps
        self.kcalories = kcalories
        self.distance_meters = distance_meters
        self.duration = duration


class _DummyView:
    def __init__(self, records, source="vault"):
        self.records = records
        self.source = source
        total = sum(r.steps for r in records) if records else 0
        self.stats = _DummyStats(days=len(records), total_steps=total, avg_steps=(total // len(records)) if records else 0)


# ---------- tests ----------

def test_analytics_allow_redact_on_walk_stream(tmp_path, monkeypatch):
    """
    Policy: allow analytics but redact calorie values in hdt.walk.stream@v1.
    Verifies that records[*].kcalories are replaced by the redaction token,
    and the redaction counter is > 0.
    """
    policy = {
        "defaults": {"analytics": {"allow": True}},
        "tools": {
            "hdt.walk.stream@v1": {
                "analytics": {
                    "allow": True,
                    # dotted path targets: payload.records[*].kcalories
                    "redact": ["records.kcalories"]
                }
            }
        },
    }
    _write_policy(tmp_path, monkeypatch, policy)

    # Stub the domain to avoid network/real adapters
    dummy_records = [
        _DummyRecord("2025-11-01", steps=100, kcalories=10.0),
        _DummyRecord("2025-11-02", steps=500, kcalories=20.0),
    ]
    monkeypatch.setattr(
        srv, "_domain",
        types.SimpleNamespace(walk_stream=lambda *a, **k: _DummyView(dummy_records))
    )

    out = srv.hdt_walk_stream(user_id=1, prefer="vault")  # tool applies analytics policy
    # Redactions accounted
    meta = srv._policy_last_meta()
    assert meta.get("allowed") is True
    assert int(meta.get("redactions", 0)) >= 2  # one per record's kcalories

    # Verify kcalories redacted
    recs = out.get("records", [])
    assert len(recs) == 2
    assert recs[0]["kcalories"] == srv.REDACT_TOKEN
    assert recs[1]["kcalories"] == srv.REDACT_TOKEN


def test_modeling_deny_on_player_types(tmp_path, monkeypatch):
    """
    Policy: deny modeling lane for hdt.get_sugarvita_player_types@v1.
    Verifies that the tool returns the standardized denied_by_policy envelope.
    """
    policy = {
        "tools": {
            "hdt.get_sugarvita_player_types@v1": {
                "modeling": {"allow": False}
            }
        }
    }
    _write_policy(tmp_path, monkeypatch, policy)

    # Avoid real API: fake the cached fetcher output the tool would use
    monkeypatch.setattr(
        srv, "_cached_get",
        lambda path, params=None: {
            "user_id": int((params or {}).get("user_id", 0)),
            "latest_update": "2025-11-01T10:00:00Z",
            "player_types": {"Socializer": 0.7, "Competitive": 0.2, "Explorer": 0.1}
        }
    )

    res = srv.tool_get_sugarvita_player_types(user_id="1", purpose="modeling")
    assert isinstance(res, dict)
    assert "error" in res
    assert res["error"]["code"] == "denied_by_policy"

    meta = srv._policy_last_meta()
    assert meta.get("allowed") is False
    assert int(meta.get("redactions", 0)) == 0


def test_coaching_allow_minimal_on_player_types(tmp_path, monkeypatch):
    """
    Policy: coaching lane allowed but redact a non-essential field to enforce minimization.
    Verifies redaction occurs (and redaction count > 0) while allowed=True.
    """
    policy = {
        "tools": {
            "hdt.get_sugarvita_player_types@v1": {
                "coaching": {
                    "allow": True,
                    "redact": ["latest_update"]  # keep only the player_types for coaching
                }
            }
        }
    }
    _write_policy(tmp_path, monkeypatch, policy)

    # Fake underlying API output
    monkeypatch.setattr(
        srv, "_cached_get",
        lambda path, params=None: {
            "user_id": int((params or {}).get("user_id", 0)),
            "latest_update": "2025-11-01T10:00:00Z",
            "player_types": {"Socializer": 0.7, "Competitive": 0.2, "Explorer": 0.1}
        }
    )

    out = srv.tool_get_sugarvita_player_types(user_id="1", purpose="coaching")
    # Allowed
    meta = srv._policy_last_meta()
    assert meta.get("allowed") is True
    assert int(meta.get("redactions", 0)) >= 1

    # Only latest_update should be redacted; player_types should remain intact
    assert out["latest_update"] == srv.REDACT_TOKEN
    assert "player_types" in out
    assert out["player_types"]["Socializer"] == 0.7
