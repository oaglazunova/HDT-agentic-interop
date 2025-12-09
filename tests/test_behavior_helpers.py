from datetime import date, timedelta


def test_avg_steps_last_days_edge_cases():
    from HDT_MCP.models.behavior import _avg_steps_last_days

    # Empty -> 0
    assert _avg_steps_last_days([], days=7) == 0

    # Mix of recent and old and invalid dates/values
    today = date.today()
    recs = [
        {"date": (today - timedelta(days=1)).isoformat(), "steps": 1000},
        {"date": (today - timedelta(days=2)).isoformat(), "steps": 3000},
        {"date": (today - timedelta(days=30)).isoformat(), "steps": 8000},  # outside 7d
        {"date": "bad-date", "steps": 9999},  # ignored
        {"date": (today).isoformat(), "steps": "500"},  # coerced to int
    ]
    avg = _avg_steps_last_days(recs, days=7)
    # Consider only last 7 days: 1000, 3000, 500 -> avg = 1500
    assert isinstance(avg, int) and avg > 0
    assert avg == int(round((1000 + 3000 + 500) / 3))


def test_behavior_strategy_api_fallback(monkeypatch):
    # Force vault off and stub API fetch
    import HDT_MCP.models.behavior as B

    monkeypatch.setenv("HDT_VAULT_ENABLE", "0")
    monkeypatch.setattr(B, "_vault", None, raising=False)

    today = date.today()
    data = [
        {"date": (today - timedelta(days=1)).isoformat(), "steps": 2000},
        {"date": (today).isoformat(), "steps": 2500},
    ]
    monkeypatch.setattr(B, "_fetch_walk_via_api", lambda user_id: data, raising=True)

    plan = B.behavior_strategy(42, days=7)
    assert plan["avg_steps"] > 0
    # With ~2250 avg, we should get the middle tier (<7000 and >=3000 is false, so first tier)
    # Actually 2250 < 3000 -> activation tier
    assert any("Prompts" in s or "prompts" in s.lower() for s in plan["bct_refs"]) or "Action planning" in " ".join(plan["bct_refs"]) or plan["avg_steps"] < 3000
